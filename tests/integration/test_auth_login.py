"""Integration: local login/logout, the user gate, admin user CRUD, audit rows.

These are the PB1 tests that explicitly turn the app-user gate ON
(RUCKUS_AUTH_REQUIRED=True) against a temp-file SQLite DB, and drive the real
routes/auth.py blueprint + before_request wiring.
"""
from __future__ import annotations

import pytest

from ruckus_dashboard.app import create_app
from ruckus_dashboard.db import session_scope
from ruckus_dashboard.db.models import AuditLog, Role, Tenant, User
from ruckus_dashboard.auth import users as users_mod


@pytest.fixture
def app(tmp_path):
    """Auth-ON app on a temp-file SQLite DB with a seeded break-glass admin."""
    db_file = tmp_path / "ruckus.db"
    app = create_app({
        "SECRET_KEY": "t",
        "RUCKUS_ENABLE_NEW_UI": True,
        "RUCKUS_AUTH_REQUIRED": True,
        "RUCKUS_DATABASE_URL": f"sqlite:///{db_file.as_posix()}",
        "RUCKUS_ADMIN_PASSWORD": "Admin-Seed-Pw-1",
    })
    return app


def _csrf(c):
    # GET /login is exempt from the gate; it seeds a csrf token in the session.
    c.get("/login")
    with c.session_transaction() as s:
        return s.get("csrf_token", "")


def test_safe_next_rejects_open_redirects(app):
    """_safe_next must fall back to the index for any non-same-site target,
    including the backslash variant browsers normalise to //host."""
    from ruckus_dashboard.routes.auth import _safe_next
    with app.test_request_context("/login"):
        index = _safe_next(None)
        for bad in (
            "//evil.com",
            "/\\evil.com",       # browsers read \ as / -> //evil.com
            "/\\/evil.com",
            "\\/evil.com",
            "https://evil.com",
            "http://evil.com",
            "javascript:alert(1)",
            "/\tinjected",       # control char
        ):
            assert _safe_next(bad) == index, f"open-redirect not blocked: {bad!r}"
        # legitimate same-site relative paths pass through unchanged
        assert _safe_next("/m/aps") == "/m/aps"
        assert _safe_next("/m/aps?zone=HQ") == "/m/aps?zone=HQ"


def _add_user(app, email, password, role, tenant_name="default"):
    with session_scope(app) as s:
        tenant = s.query(Tenant).filter_by(name=tenant_name).one()
        users_mod.create_user(s, tenant_id=tenant.id, email=email,
                             password=password, role=role)


# ── startup seeding ──────────────────────────────────────────────────────────

def test_default_tenant_and_admin_seeded(app):
    with session_scope(app) as s:
        assert s.query(Tenant).filter_by(name="default").count() == 1
        admin = s.query(User).filter_by(role=Role.admin.name).one()
        assert admin.email == "admin"


def test_seeded_admin_uses_env_password(app):
    with session_scope(app) as s:
        admin = users_mod.get_by_email(s, "admin")
        assert users_mod.verify_password(admin, "Admin-Seed-Pw-1") is True


# ── user gate ────────────────────────────────────────────────────────────────

def test_gate_html_unauth_redirects_to_login(app):
    with app.test_client() as c:
        r = c.get("/")
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]


def test_gate_api_unauth_returns_401(app):
    with app.test_client() as c:
        r = c.get("/api/notifications/config")
        assert r.status_code == 401


def test_gate_exempts_healthz_and_readyz(app):
    with app.test_client() as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/readyz").status_code == 200


def test_gate_exempts_login_get(app):
    with app.test_client() as c:
        assert c.get("/login").status_code == 200


def test_gate_allows_static(app):
    with app.test_client() as c:
        # static file may or may not exist, but must NOT be a 302 login bounce
        r = c.get("/static/styles.css")
        assert r.status_code in (200, 304, 404)


# ── local login ──────────────────────────────────────────────────────────────

def test_login_success_sets_session_and_audits(app):
    with app.test_client() as c:
        token = _csrf(c)
        r = c.post("/login", data={"email": "admin", "password": "Admin-Seed-Pw-1",
                                  "csrf_token": token})
        assert r.status_code in (302, 303)
        with c.session_transaction() as s:
            assert s.get("user_id") is not None
            assert s.get("role") == Role.admin.name
            assert s.get("tenant_id") is not None
    with session_scope(app) as s:
        actions = [a.action for a in s.query(AuditLog).all()]
        assert "login_success" in actions


def test_login_rotates_session_id_fixation_guard(app):
    with app.test_client() as c:
        # seed a pre-login session value; it must NOT survive a successful login
        with c.session_transaction() as s:
            s["planted"] = "attacker"
        token = _csrf(c)
        c.post("/login", data={"email": "admin", "password": "Admin-Seed-Pw-1",
                              "csrf_token": token})
        with c.session_transaction() as s:
            assert "planted" not in s  # session.clear() ran on privilege change
            assert s.get("user_id") is not None


def test_login_wrong_password_fails_and_audits(app):
    with app.test_client() as c:
        token = _csrf(c)
        c.post("/login", data={"email": "admin", "password": "WRONG",
                              "csrf_token": token}, follow_redirects=False)
        # stays on login (no user_id in session)
        with c.session_transaction() as s:
            assert s.get("user_id") is None
    with session_scope(app) as s:
        actions = [a.action for a in s.query(AuditLog).all()]
        assert "login_failure" in actions


def test_login_unknown_user_fails(app):
    with app.test_client() as c:
        token = _csrf(c)
        c.post("/login", data={"email": "ghost@x.y", "password": "x",
                              "csrf_token": token})
        with c.session_transaction() as s:
            assert s.get("user_id") is None


def test_login_bad_csrf_rejected(app):
    with app.test_client() as c:
        _csrf(c)
        r = c.post("/login", data={"email": "admin", "password": "Admin-Seed-Pw-1",
                                  "csrf_token": "bogus"})
        assert r.status_code == 400


def test_login_then_access_protected_page(app):
    with app.test_client() as c:
        token = _csrf(c)
        c.post("/login", data={"email": "admin", "password": "Admin-Seed-Pw-1",
                              "csrf_token": token})
        r = c.get("/")
        assert r.status_code == 200  # gate now satisfied


def test_login_deactivated_user_denied(app):
    _add_user(app, "off@x.y", "Deact-Pw-123", "viewer")
    with session_scope(app) as s:
        u = users_mod.get_by_email(s, "off@x.y")
        u.is_active = False
    with app.test_client() as c:
        token = _csrf(c)
        c.post("/login", data={"email": "off@x.y", "password": "Deact-Pw-123",
                              "csrf_token": token})
        with c.session_transaction() as s:
            assert s.get("user_id") is None


# ── logout ───────────────────────────────────────────────────────────────────

def test_logout_clears_user_and_audits(app):
    with app.test_client() as c:
        token = _csrf(c)
        c.post("/login", data={"email": "admin", "password": "Admin-Seed-Pw-1",
                              "csrf_token": token})
        with c.session_transaction() as s:
            token2 = s["csrf_token"]
        r = c.post("/logout/app", data={"csrf_token": token2})
        assert r.status_code in (302, 303)
        with c.session_transaction() as s:
            assert s.get("user_id") is None
    with session_scope(app) as s:
        actions = [a.action for a in s.query(AuditLog).all()]
        assert "logout" in actions


# ── admin user CRUD ──────────────────────────────────────────────────────────

def _login(c, email, password):
    c.get("/login")
    with c.session_transaction() as s:
        token = s["csrf_token"]
    c.post("/login", data={"email": email, "password": password, "csrf_token": token})
    with c.session_transaction() as s:
        return s["csrf_token"]


def test_admin_users_list_requires_admin(app):
    _add_user(app, "op@x.y", "Operator-Pw-1", "operator")
    with app.test_client() as c:
        _login(c, "op@x.y", "Operator-Pw-1")
        assert c.get("/admin/users").status_code == 403


def test_viewer_cannot_reach_admin_users(app):
    _add_user(app, "view@x.y", "Viewer-Pw-12", "viewer")
    with app.test_client() as c:
        _login(c, "view@x.y", "Viewer-Pw-12")
        assert c.get("/admin/users").status_code == 403


def test_admin_can_list_users(app):
    with app.test_client() as c:
        _login(c, "admin", "Admin-Seed-Pw-1")
        r = c.get("/admin/users")
        assert r.status_code == 200
        assert b"admin" in r.data


def test_admin_can_create_user(app):
    with app.test_client() as c:
        token = _login(c, "admin", "Admin-Seed-Pw-1")
        r = c.post("/admin/users", data={
            "action": "create", "email": "new@x.y", "password": "New-User-Pw-1",
            "role": "operator", "csrf_token": token,
        })
        assert r.status_code in (200, 302, 303)
    with session_scope(app) as s:
        u = users_mod.get_by_email(s, "new@x.y")
        assert u is not None and u.role == Role.operator.name
        actions = [a.action for a in s.query(AuditLog).all()]
        assert "user_create" in actions


def test_admin_create_user_is_audited_and_gated(app):
    # operator POST to create must be forbidden
    _add_user(app, "op2@x.y", "Operator2-Pw-1", "operator")
    with app.test_client() as c:
        token = _login(c, "op2@x.y", "Operator2-Pw-1")
        r = c.post("/admin/users", data={
            "action": "create", "email": "sneak@x.y", "password": "Sneak-Pw-123",
            "role": "admin", "csrf_token": token,
        })
        assert r.status_code == 403
    with session_scope(app) as s:
        assert users_mod.get_by_email(s, "sneak@x.y") is None


def test_admin_can_deactivate_user(app):
    _add_user(app, "target@x.y", "Target-Pw-123", "viewer")
    with session_scope(app) as s:
        target_id = users_mod.get_by_email(s, "target@x.y").id
    with app.test_client() as c:
        token = _login(c, "admin", "Admin-Seed-Pw-1")
        r = c.post("/admin/users", data={
            "action": "deactivate", "user_id": str(target_id), "csrf_token": token,
        })
        assert r.status_code in (200, 302, 303)
    with session_scope(app) as s:
        u = s.get(User, target_id)
        assert u.is_active is False
        actions = [a.action for a in s.query(AuditLog).all()]
        assert "user_deactivate" in actions


def test_admin_users_post_requires_csrf(app):
    with app.test_client() as c:
        _login(c, "admin", "Admin-Seed-Pw-1")
        r = c.post("/admin/users", data={
            "action": "create", "email": "x@x.y", "password": "pw",
            "role": "viewer", "csrf_token": "bad",
        })
        assert r.status_code == 400
