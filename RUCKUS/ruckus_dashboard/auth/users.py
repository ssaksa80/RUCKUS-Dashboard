"""App-user store over the ``db`` layer (Phase B, PB1).

Local/break-glass users authenticate with an **argon2id** hash (via passlib);
OIDC-only users (PB2) carry ``password_hash=None`` and never pass local verify.
Plaintext passwords are never stored or logged.

Most functions take an explicit SQLAlchemy ``Session`` so they are trivially
testable and tenant-scoped by the caller. They do NOT commit — the caller owns
the transaction boundary (request teardown / ``session_scope``). The one
exception is :func:`upsert_oidc_user` (PB2 JIT provisioning), which is called
from the OIDC callback with the ``app`` and owns its own scope.
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional

from passlib.context import CryptContext
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import session_scope
from ..db.models import Role, Tenant, User

LOG = logging.getLogger("ruckus_dashboard.auth.users")

# argon2id only. passlib picks sane argon2 defaults; we pin the type to id.
_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


class OidcEmailConflict(Exception):
    """An OIDC login's email claim collides with a different existing account.

    Raised by :func:`upsert_oidc_user` when no user matches the OIDC
    ``subject`` yet the inbound ``email`` claim is already owned by another
    account. Because ``email`` is an attacker-influenceable IdP claim (Authlib
    validates iss/aud/exp/nonce/signature — never email ownership), we refuse
    to auto-link or overwrite by email: doing so would let any IdP account take
    over a privileged local/OIDC user (e.g. the break-glass ``admin``). The
    OIDC callback catches this and rejects the login with a generic error.
    """

    def __init__(self, email: str):
        self.email = email
        super().__init__("OIDC email claim conflicts with an existing account")


def hash_password(plaintext: str) -> str:
    """Return an argon2id hash for ``plaintext`` (never store the plaintext)."""
    return _pwd_context.hash(plaintext)


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def get_by_email(session: Session, email: str) -> Optional[User]:
    """Case-insensitive lookup; ``None`` if absent."""
    norm = _normalize_email(email)
    if not norm:
        return None
    return (
        session.query(User)
        .filter(func.lower(User.email) == norm)
        .one_or_none()
    )


def create_user(
    session: Session,
    *,
    tenant_id: int,
    email: str,
    password: Optional[str],
    role: "str | Role",
    display_name: Optional[str] = None,
    oidc_subject: Optional[str] = None,
    is_active: bool = True,
) -> User:
    """Create (and ``add``) a user. Validates the role; hashes the password.

    ``password=None`` yields an OIDC-only account (no local login). Raises
    ``KeyError``/``ValueError`` for an unknown role (caller treats as invalid).
    """
    role_member = Role.coerce(role)  # raises on unknown role
    user = User(
        tenant_id=tenant_id,
        email=_normalize_email(email),
        display_name=display_name,
        password_hash=hash_password(password) if password else None,
        role=role_member.name,
        oidc_subject=oidc_subject,
        is_active=is_active,
    )
    session.add(user)
    session.flush()  # assign PK without committing
    return user


def set_password(user: User, plaintext: str) -> None:
    """Replace the user's password hash (argon2id). Caller commits."""
    user.password_hash = hash_password(plaintext)


def verify_password(user: User, plaintext: str) -> bool:
    """True iff ``plaintext`` matches the user's argon2 hash.

    Always False for OIDC-only users (no hash) or an empty candidate. Uses
    passlib's constant-time verify; malformed stored hashes fail closed.
    """
    if user is None or not user.password_hash or not plaintext:
        return False
    try:
        return _pwd_context.verify(plaintext, user.password_hash)
    except (ValueError, TypeError):  # malformed/unknown hash -> deny
        return False


def record_login(session: Session, user: User) -> None:
    """Stamp ``last_login_at`` = now. Caller commits."""
    from ..db.models import _utcnow

    user.last_login_at = _utcnow()
    session.add(user)


def bootstrap_admin(
    session: Session,
    *,
    tenant_id: int,
    password: Optional[str],
) -> tuple[Optional[User], Optional[str]]:
    """First-boot break-glass admin seed.

    If **no users exist at all**, create a local ``admin`` user in the given
    tenant. The password comes from ``password`` (typically
    ``RUCKUS_ADMIN_PASSWORD``); if that is empty a strong random password is
    generated and **returned** so the caller can surface it once (console/log).

    Returns ``(user, generated_password)``:
      * fresh seed with env password  -> ``(user, None)``
      * fresh seed with random password -> ``(user, "<the password>")``
      * users already exist (idempotent) -> ``(None, None)``

    Idempotent: never seeds a second admin. Never logs the password.
    """
    if session.query(User).first() is not None:
        return None, None

    generated: Optional[str] = None
    pw = password
    if not pw:
        generated = secrets.token_urlsafe(18)  # ~24 chars, high entropy
        pw = generated

    admin = create_user(
        session,
        tenant_id=tenant_id,
        email="admin",
        password=pw,
        role=Role.admin,
        display_name="Break-glass admin",
    )
    LOG.warning(
        "bootstrap: seeded break-glass admin user 'admin' (tenant %s)", tenant_id
    )
    return admin, generated


def _default_tenant_id(session: Session) -> int:
    """Resolve the tenant new OIDC users land in (PB1's single tenant).

    Prefers the ``default`` tenant seeded at boot; falls back to the
    lowest-id tenant if it was renamed. Raises if no tenant exists at all
    (the identity layer always seeds one, so this is defensive).
    """
    tenant = session.query(Tenant).filter_by(name="default").one_or_none()
    if tenant is None:
        tenant = session.query(Tenant).order_by(Tenant.id).first()
    if tenant is None:  # pragma: no cover - seed_identity always creates one
        raise RuntimeError("no tenant exists; identity layer not seeded")
    return tenant.id


def upsert_oidc_user(
    app,
    *,
    subject: str,
    email: str,
    display_name: Optional[str],
    role: "str | Role",
) -> User:
    """Just-in-time provision (or update) the app user for an OIDC login.

    The join key is **strictly** the OIDC ``subject`` — never the ``email``
    claim, which the IdP/attacker controls and Authlib does not verify for
    ownership. Resolution:

      1. If a user's ``oidc_subject`` already matches ``subject``: update
         ``display_name``/``role`` (from the group→role map)/``last_login_at``
         and return it.
      2. Otherwise (subject unknown):

         * If the inbound ``email`` is already owned by a different account
           (any row with that email — its subject is ``None`` or some other
           subject), **refuse**: raise :class:`OidcEmailConflict`. This blocks
           account takeover by an inbound email claim (e.g. the break-glass
           ``admin``) and avoids a ``User.email`` unique-constraint crash. No
           row is created or modified.
         * Else create a fresh OIDC-only user (``password_hash=None``) in the
           default tenant.

    A password is **never** set here. Opens its own transactional scope and
    returns the committed User; because the session factory uses
    ``expire_on_commit=False`` the returned instance's attributes stay readable
    after the scope closes, so the caller can set the session identity from it.
    """
    role_name = Role.coerce(role).name  # raises on unknown role
    norm_email = _normalize_email(email)
    with session_scope(app) as s:
        user = (
            s.query(User).filter(User.oidc_subject == subject).one_or_none()
        )
        if user is None:
            # Subject unknown. Do NOT match/attach by the email claim — refuse
            # if that email is already taken by any other account, else JIT.
            if norm_email and get_by_email(s, norm_email) is not None:
                raise OidcEmailConflict(norm_email)
            user = User(
                tenant_id=_default_tenant_id(s),
                email=norm_email,
                display_name=display_name,
                password_hash=None,  # OIDC-only: never a local password
                role=role_name,
                oidc_subject=subject,
                is_active=True,
            )
            s.add(user)
        else:
            # Known subject — refresh from the IdP on each login.
            if display_name is not None:
                user.display_name = display_name
            user.role = role_name
            s.add(user)

        record_login(s, user)
        s.flush()  # assign PK before the scope commits
    return user
