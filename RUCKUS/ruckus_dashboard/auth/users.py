"""App-user store over the ``db`` layer (Phase B, PB1).

Local/break-glass users authenticate with an **argon2id** hash (via passlib);
OIDC-only users (PB2) carry ``password_hash=None`` and never pass local verify.
Plaintext passwords are never stored or logged.

All functions take an explicit SQLAlchemy ``Session`` so they are trivially
testable and tenant-scoped by the caller. They do NOT commit — the caller owns
the transaction boundary (request teardown / ``session_scope``).
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional

from passlib.context import CryptContext
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db.models import Role, User

LOG = logging.getLogger("ruckus_dashboard.auth.users")

# argon2id only. passlib picks sane argon2 defaults; we pin the type to id.
_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


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
