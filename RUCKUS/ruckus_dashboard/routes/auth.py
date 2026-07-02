"""App-user auth blueprint (Phase B, PB1): local login/logout + admin user CRUD.

Layer 1 of the two-layer auth model — *who the operator is* — distinct from the
controller connection (Layer 2, ``routes/connect.py``). Local break-glass login
verifies an argon2id password, rotates the session (fixation guard, mirroring the
controller-connect ``session.clear()``), and audits every attempt. Admin user
management is gated by ``@require_role("admin")``.

OIDC (PB2) will add ``/login/oidc`` + ``/auth/callback`` alongside this; the
local path always remains as the air-gapped break-glass.
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..auth.audit import record_audit
from ..auth.csrf import validate_csrf
from ..auth import oidc as oidc_mod
from ..auth import users as users_mod
from ..db import session_scope
from ..db.models import Role, Tenant, User

LOG = logging.getLogger("ruckus_dashboard.auth")

bp = Blueprint("auth", __name__)


def _rate_key(email: str) -> str:
    ip = request.remote_addr or "?"
    return f"{ip}|{(email or '').strip().lower()}"


def _safe_next(raw: str | None) -> str:
    """Only allow same-site relative redirects (avoid open-redirect).

    Rejects absolute URLs, scheme-relative ``//host``, and the backslash variant
    ``/\\host`` — browsers normalise ``\\`` → ``/`` in the authority, so
    ``/\\evil.com`` would otherwise resolve to ``//evil.com`` (a protocol-relative
    redirect to an external host). Also rejects any control character, and
    confirms via ``urlparse`` that the target carries no scheme and no netloc.
    """
    if not raw:
        return url_for("pages.index")
    if "\\" in raw or any(ord(ch) < 0x20 for ch in raw):
        return url_for("pages.index")
    if raw.startswith("/") and not raw.startswith("//"):
        parsed = urlparse(raw)
        if not parsed.scheme and not parsed.netloc:
            return raw
    return url_for("pages.index")


@bp.get("/login")
def login():
    # Exempt from the user gate; ensure a csrf token exists for the POST.
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template(
        "auth_login.html",
        csrf_token=session.get("csrf_token", ""),
        # PB2: only advertise the SSO button when OIDC is fully configured.
        oidc_enabled=oidc_mod.oidc_enabled(current_app),
    )


@bp.post("/login")
def login_post():
    validate_csrf()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    limiter = current_app.login_rate_limiter
    key = _rate_key(email)

    if limiter.is_locked(key):
        record_audit(current_app, action="login_ratelimited",
                     detail={"email": email})
        flash("Too many failed attempts. Try again later.", "error")
        return _login_error(status=429)

    # Resolve the user + verdict in one scope, capturing plain values so all
    # auditing happens AFTER the scope closes (record_audit opens its own
    # session; nesting the same thread-local scoped session would close it out
    # from under this block).
    with session_scope(current_app) as s:
        user = users_mod.get_by_email(s, email)
        ok = (
            user is not None
            and user.is_active
            and users_mod.verify_password(user, password)
        )
        if ok:
            users_mod.record_login(s, user)
        uid = user.id if user else None
        tid = user.tenant_id if user else None
        role = user.role if user else None
        if user is None:
            reason = "unknown_user"
        elif not user.is_active:
            reason = "inactive"
        else:
            reason = None  # success or bad password

    if not ok:
        limiter.register_failure(key)
        record_audit(current_app, action="login_failure", user_id=uid,
                     tenant_id=tid,
                     detail={"email": email, "reason": reason or "bad_password"})
        flash("Invalid credentials.", "error")
        return _login_error(status=401)

    limiter.reset(key)
    _rotate_session_for_login(uid, tid, role)
    record_audit(current_app, action="login_success", user_id=uid,
                 tenant_id=tid, detail={"email": email})
    return redirect(_safe_next(request.form.get("next") or request.args.get("next")))


def _login_error(status: int):
    """Re-render the login page with the given status (failed/locked out)."""
    return (
        render_template("auth_login.html", csrf_token=session.get("csrf_token", "")),
        status,
    )


def _rotate_session_for_login(user_id: int, tenant_id: int, role: str) -> None:
    """Session-fixation guard: clear then set identity (mirrors controller connect).

    Preserves the csrf token across the rotation so the very next POST still
    validates, exactly like ``routes/connect.py``.
    """
    csrf_token = session.get("csrf_token", secrets.token_urlsafe(32))
    session.clear()
    session["csrf_token"] = csrf_token
    session["user_id"] = user_id
    session["tenant_id"] = tenant_id
    session["role"] = role
    session.permanent = True


@bp.post("/logout/app")
def logout_app():
    """App-user logout — distinct from the controller ``/logout``.

    Clears the app-user identity but preserves the csrf token. Does not touch
    live controller connections (that is the controller logout's job).
    """
    validate_csrf()
    uid = session.get("user_id")
    tid = session.get("tenant_id")
    csrf_token = session.get("csrf_token", secrets.token_urlsafe(32))
    session.clear()
    session["csrf_token"] = csrf_token
    if uid is not None:
        record_audit(current_app, action="logout", user_id=uid, tenant_id=tid)
    return redirect(url_for("auth.login"))


# ── OIDC SSO (PB2) ───────────────────────────────────────────────────────────
#
# These paths are gate-exempt (``/login/*`` + ``/auth/*``). The local
# break-glass login above always remains available; OIDC is opt-in via config
# and stays fully disabled unless issuer+client id+secret are all set.

# Generic, deliberately non-specific message for every OIDC failure — never
# leaks whether the error was validation, network, mapping, or user-declined.
_OIDC_ERROR_FLASH = "Single sign-on failed. Please try again or use a local login."


@bp.get("/login/oidc")
def login_oidc():
    """Kick off the OIDC authorization-code flow (redirect to the IdP).

    Disabled → flash + bounce to the local login (no crash). Enabled → remember
    a validated ``next`` target in the session and hand off to Authlib, which
    stores state+nonce and 302s to the IdP authorize endpoint.
    """
    if not oidc_mod.oidc_enabled(current_app):
        flash("Single sign-on is not configured.", "error")
        return redirect(url_for("auth.login"))

    # Stash where to land after login (validated on the way back out).
    nxt = request.args.get("next")
    if nxt:
        session["next"] = nxt

    redirect_uri = url_for("auth.oidc_callback", _external=True)
    try:
        return oidc_mod.begin_login(current_app, redirect_uri)
    except Exception:  # noqa: BLE001 - discovery/build failure must not 500
        LOG.warning("OIDC authorize redirect failed", exc_info=True)
        record_audit(current_app, action="login_failure",
                     detail={"method": "oidc", "stage": "authorize"})
        flash(_OIDC_ERROR_FLASH, "error")
        return redirect(url_for("auth.login"))


@bp.get("/auth/callback")
def oidc_callback():
    """OIDC redirect target: exchange the code, provision the user, log them in.

    Authlib validates state/nonce/iss/aud/signature/expiry inside
    ``complete_login``. On success we map the IdP groups to a role, JIT-provision
    (or update) the user, rotate the session (fixation guard, mirroring the
    local path), audit ``login_success method=oidc`` and honour the stored
    ``next``. On ANY error we audit a generic ``login_failure`` and redirect to
    the local login — never surfacing token or exception detail.
    """
    if not oidc_mod.oidc_enabled(current_app):
        flash("Single sign-on is not configured.", "error")
        return redirect(url_for("auth.login"))

    try:
        claims = oidc_mod.complete_login(current_app)
        subject, email, display_name, groups = oidc_mod.extract_claims(
            current_app, claims
        )
        role = oidc_mod.map_groups_to_role(groups, current_app.config)
        user = users_mod.upsert_oidc_user(
            current_app, subject=subject, email=email,
            display_name=display_name, role=role,
        )
        uid, tid, role_name = user.id, user.tenant_id, user.role
    except users_mod.OidcEmailConflict:
        # The inbound email claim collides with a different existing account.
        # Refuse the login (never auto-link/overwrite by an unverified email —
        # that would be account takeover). Audit generically WITHOUT revealing
        # which email conflicted, and show the same generic OIDC error.
        LOG.warning("OIDC callback refused: email claim conflicts with an "
                    "existing account")
        record_audit(current_app, action="login_failure",
                     detail={"method": "oidc", "stage": "callback",
                             "reason": "email_conflict"})
        flash(_OIDC_ERROR_FLASH, "error")
        return redirect(url_for("auth.login"))
    except Exception:  # noqa: BLE001 - any OIDC failure is a generic login error
        # Do NOT log/flash the token or the raw exception message. exc_info goes
        # only to the server log, never to the user or the audit detail.
        LOG.warning("OIDC callback failed", exc_info=True)
        record_audit(current_app, action="login_failure",
                     detail={"method": "oidc", "stage": "callback"})
        flash(_OIDC_ERROR_FLASH, "error")
        return redirect(url_for("auth.login"))

    # Read the stored next BEFORE rotating — session.clear() would wipe it.
    dest = _safe_next(session.pop("next", None))
    _rotate_session_for_login(uid, tid, role_name)
    record_audit(current_app, action="login_success", user_id=uid,
                 tenant_id=tid, detail={"method": "oidc", "email": email})
    return redirect(dest)


# ── admin user management ────────────────────────────────────────────────────

from ..auth.rbac import require_role  # noqa: E402 - after bp defined


@bp.get("/admin/users")
@require_role("admin")
def admin_users():
    with session_scope(current_app) as s:
        rows = (
            s.query(User)
            .filter(User.tenant_id == g.tenant_id)
            .order_by(User.email)
            .all()
        )
        # Detach a plain view for the template (session closes on scope exit).
        view = [
            {
                "id": u.id, "email": u.email, "role": u.role,
                "is_active": u.is_active, "display_name": u.display_name,
                "last_login_at": u.last_login_at,
            }
            for u in rows
        ]
    return render_template(
        "admin_users.html", users=view, roles=[r.name for r in Role],
        csrf_token=session.get("csrf_token", ""),
    )


@bp.post("/admin/users")
@require_role("admin")
def admin_users_post():
    validate_csrf()
    action = (request.form.get("action") or "").strip()
    if action == "create":
        return _admin_create_user()
    if action == "deactivate":
        return _admin_deactivate_user()
    flash("Unknown action.", "error")
    return redirect(url_for("auth.admin_users"))


def _admin_create_user():
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    role = (request.form.get("role") or "").strip()
    if not email or not password or not role:
        flash("Email, password and role are required.", "error")
        return redirect(url_for("auth.admin_users"))
    try:
        Role.coerce(role)
    except (KeyError, ValueError):
        flash("Invalid role.", "error")
        return redirect(url_for("auth.admin_users"))

    with session_scope(current_app) as s:
        if users_mod.get_by_email(s, email) is not None:
            flash("A user with that email already exists.", "error")
            return redirect(url_for("auth.admin_users"))
        created = users_mod.create_user(
            s, tenant_id=g.tenant_id, email=email, password=password, role=role
        )
        new_id = created.id
    record_audit(current_app, action="user_create", user_id=g.user_id,
                 tenant_id=g.tenant_id,
                 detail={"created_user_id": new_id, "email": email.lower(),
                         "role": role})
    flash(f"Created user {email}.", "success")
    return redirect(url_for("auth.admin_users"))


def _admin_deactivate_user():
    raw_id = (request.form.get("user_id") or "").strip()
    try:
        target_id = int(raw_id)
    except ValueError:
        flash("Invalid user id.", "error")
        return redirect(url_for("auth.admin_users"))

    with session_scope(current_app) as s:
        target = s.query(User).filter(
            User.id == target_id, User.tenant_id == g.tenant_id
        ).one_or_none()
        if target is None:
            flash("User not found.", "error")
            return redirect(url_for("auth.admin_users"))
        target.is_active = False
        s.add(target)
    record_audit(current_app, action="user_deactivate", user_id=g.user_id,
                 tenant_id=g.tenant_id, detail={"target_user_id": target_id})
    flash("User deactivated.", "success")
    return redirect(url_for("auth.admin_users"))


def seed_identity(app) -> None:
    """Startup seed: ensure a default Tenant + break-glass admin exist.

    Idempotent. Called from create_app after init_db. Surfaces a generated
    break-glass password once (WARNING log) when none was configured.
    """
    with session_scope(app) as s:
        tenant = s.query(Tenant).filter_by(name="default").one_or_none()
        if tenant is None:
            tenant = Tenant(name="default")
            s.add(tenant)
            s.flush()
        tenant_id = tenant.id
        admin, generated = users_mod.bootstrap_admin(
            s, tenant_id=tenant_id,
            password=app.config.get("RUCKUS_ADMIN_PASSWORD") or None,
        )
    if generated:
        # One-time surfacing of the break-glass password (never persisted plain).
        LOG.warning(
            "BREAK-GLASS ADMIN CREATED — username 'admin', one-time password: %s "
            "(set RUCKUS_ADMIN_PASSWORD to control this; store it now, it will "
            "not be shown again).",
            generated,
        )
