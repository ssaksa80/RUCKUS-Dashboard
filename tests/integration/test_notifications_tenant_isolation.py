"""PB3 route-level tenant isolation for notification config.

Two app users in two tenants drive the real /api/notifications/config routes
with the app-user gate ON. Each tenant sees ONLY its own config; tenant A can
never read tenant B's SMTP host / recipients / password through the route.
"""
from __future__ import annotations

import pytest

from ruckus_dashboard.app import create_app
from ruckus_dashboard.db import session_scope
from ruckus_dashboard.db.models import Tenant
from ruckus_dashboard.auth import users as users_mod


@pytest.fixture
def app(tmp_path):
    db_file = tmp_path / "ruckus.db"
    app = create_app({
        "SECRET_KEY": "t",
        "RUCKUS_ENABLE_NEW_UI": True,
        "RUCKUS_AUTH_REQUIRED": True,
        "RUCKUS_DATABASE_URL": f"sqlite:///{db_file.as_posix()}",
        "RUCKUS_ADMIN_PASSWORD": "Admin-Seed-Pw-1",
    })
    # Second tenant + one operator per tenant.
    with session_scope(app) as s:
        default = s.query(Tenant).filter_by(name="default").one()
        other = Tenant(name="tenantB")
        s.add(other)
        s.flush()
        users_mod.create_user(s, tenant_id=default.id, email="a@x",
                              password="Passw0rd-A", role="operator")
        users_mod.create_user(s, tenant_id=other.id, email="b@x",
                              password="Passw0rd-B", role="operator")
    return app


def _login_and_connect(c, email, password):
    """Log in an app user (Layer 1) and fake a controller connection (Layer 2)."""
    c.get("/login")
    with c.session_transaction() as s:
        csrf = s["csrf_token"]
    r = c.post("/login", data={"email": email, "password": password,
                               "csrf_token": csrf})
    assert r.status_code in (302, 303), r.get_data(as_text=True)
    # The notification routes gate on session["auth"] (controller connection);
    # set it directly (Layer 2 is out of scope for this isolation test).
    with c.session_transaction() as s:
        s["auth"] = True
        s["connection_ids"] = []
        csrf = s["csrf_token"]
    return csrf


def test_config_is_isolated_between_tenants_via_routes(app):
    # Tenant A saves its config.
    with app.test_client() as ca:
        csrf_a = _login_and_connect(ca, "a@x", "Passw0rd-A")
        r = ca.post("/api/notifications/config",
                    json={"smtp": {"host": "a.mail", "password": "secretA"},
                          "alerts": {"recipients": ["a-noc@x"]}},
                    headers={"X-CSRF-Token": csrf_a})
        assert r.status_code == 200

    # Tenant B saves a DIFFERENT config.
    with app.test_client() as cb:
        csrf_b = _login_and_connect(cb, "b@x", "Passw0rd-B")
        r = cb.post("/api/notifications/config",
                    json={"smtp": {"host": "b.mail", "password": "secretB"},
                          "alerts": {"recipients": ["b-noc@x"]}},
                    headers={"X-CSRF-Token": csrf_b})
        assert r.status_code == 200

    # Tenant A reads back ONLY its own config.
    with app.test_client() as ca:
        _login_and_connect(ca, "a@x", "Passw0rd-A")
        got = ca.get("/api/notifications/config").get_json()
        assert got["smtp"]["host"] == "a.mail"
        assert got["alerts"]["recipients"] == ["a-noc@x"]
        # Never leaks tenant B's host or any plaintext password.
        assert "b.mail" not in ca.get("/api/notifications/config").get_data(as_text=True)

    # Tenant B reads back ONLY its own config.
    with app.test_client() as cb:
        _login_and_connect(cb, "b@x", "Passw0rd-B")
        got = cb.get("/api/notifications/config").get_json()
        assert got["smtp"]["host"] == "b.mail"
        assert got["alerts"]["recipients"] == ["b-noc@x"]
