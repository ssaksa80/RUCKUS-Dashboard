"""auth.rbac — require_user / require_role decorators + Role ordering.

Exercised on a throwaway Flask app with decorated test routes; g.user/g.role
are seeded by a before_request shim so we don't need the full login stack.
"""
from __future__ import annotations

import pytest
from flask import Flask, g, jsonify

from ruckus_dashboard.auth import rbac
from ruckus_dashboard.db.models import Role


def _make_app(role: str | None):
    """App whose before_request sets g.user/g.role to simulate a logged-in user."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "t"

    @app.before_request
    def _seed():
        if role is None:
            g.user = None
            g.role = None
        else:
            g.user = object()  # truthy stand-in
            g.role = role

    @app.get("/html-protected")
    @rbac.require_user
    def html_protected():
        return "ok-html"

    @app.get("/api/protected")
    @rbac.require_user
    def api_protected():
        return jsonify(ok=True)

    @app.get("/api/viewer")
    @rbac.require_role("viewer")
    def api_viewer():
        return jsonify(area="viewer")

    @app.get("/api/operator")
    @rbac.require_role("operator")
    def api_operator():
        return jsonify(area="operator")

    @app.get("/api/admin")
    @rbac.require_role("admin")
    def api_admin():
        return jsonify(area="admin")

    return app


# ── Role ordering ────────────────────────────────────────────────────────────

def test_role_meets_ordering():
    assert rbac.role_meets(Role.admin, Role.viewer) is True
    assert rbac.role_meets(Role.operator, Role.operator) is True
    assert rbac.role_meets(Role.viewer, Role.operator) is False
    # accepts names too
    assert rbac.role_meets("admin", "operator") is True
    assert rbac.role_meets("viewer", "admin") is False


# ── require_user ─────────────────────────────────────────────────────────────

def test_require_user_allows_authenticated():
    app = _make_app("viewer")
    with app.test_client() as c:
        assert c.get("/html-protected").data == b"ok-html"
        assert c.get("/api/protected").get_json() == {"ok": True}


def test_require_user_html_unauth_redirects_302_to_login():
    app = _make_app(None)
    with app.test_client() as c:
        r = c.get("/html-protected")
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]


def test_require_user_api_unauth_returns_401_json():
    app = _make_app(None)
    with app.test_client() as c:
        r = c.get("/api/protected")
        assert r.status_code == 401
        assert r.is_json
        assert "error" in r.get_json()


# ── require_role matrix (viewer < operator < admin) ─────────────────────────

@pytest.mark.parametrize(
    "role,path,expect",
    [
        # viewer route
        ("viewer", "/api/viewer", 200),
        ("operator", "/api/viewer", 200),
        ("admin", "/api/viewer", 200),
        # operator route
        ("viewer", "/api/operator", 403),
        ("operator", "/api/operator", 200),
        ("admin", "/api/operator", 200),
        # admin route
        ("viewer", "/api/admin", 403),
        ("operator", "/api/admin", 403),
        ("admin", "/api/admin", 200),
    ],
)
def test_require_role_matrix(role, path, expect):
    app = _make_app(role)
    with app.test_client() as c:
        assert c.get(path).status_code == expect


def test_require_role_unauth_html_redirects():
    app = _make_app(None)

    @app.get("/admin/page")
    @rbac.require_role("admin")
    def admin_page():
        return "secret"

    with app.test_client() as c:
        r = c.get("/admin/page")
        # unauthenticated -> login redirect (not 403), even on a role-gated route
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]


def test_require_role_api_insufficient_returns_403_json():
    app = _make_app("viewer")
    with app.test_client() as c:
        r = c.get("/api/admin")
        assert r.status_code == 403
        assert r.is_json
