"""PB3 scheduler tenant-awareness.

The daemon thread has no request/g.tenant_id. It captures the app-user tenant
of its active connection (set on /connect) and loads THAT tenant's config from
the DB; with no connection/tenant it falls back to the default tenant. This is
the single-node behaviour — no multi-tenant fan-out.
"""
from __future__ import annotations

import pytest
from flask import Flask

from ruckus_dashboard import db as dbmod
from ruckus_dashboard.db.models import Tenant
from ruckus_dashboard.notify.config import NotificationConfigStore
from ruckus_dashboard.notify.scheduler import NotifyScheduler


class FakeSecrets:
    def encrypt(self, s):
        return f"enc:{s}"

    def decrypt(self, s):
        return s[4:] if s.startswith("enc:") else s


@pytest.fixture
def app(tmp_instance):
    app = Flask(__name__)
    app.instance_path = tmp_instance
    app.config["RUCKUS_DATABASE_URL"] = "sqlite:///:memory:"
    dbmod.init_db(app)
    with dbmod.session_scope(app) as s:
        s.add_all([Tenant(name="default"), Tenant(name="tenantB")])
    app.secrets_manager = FakeSecrets()
    # Distinct configs per tenant so we can tell which one the scheduler loaded.
    store = NotificationConfigStore(app, default_tenant_id=1)
    store.save_config({"smtp": {"host": "default.mail"},
                       "alerts": {"enabled": True, "check_seconds": 111,
                                  "recipients": ["default@x"]}},
                      app.secrets_manager, tenant_id=1)
    store.save_config({"smtp": {"host": "b.mail"},
                       "alerts": {"enabled": True, "check_seconds": 222,
                                  "recipients": ["b@x"]}},
                      app.secrets_manager, tenant_id=2)
    return app


def _sched(app, **kw):
    return NotifyScheduler(app.instance_path, dict(app.config),
                           app.secrets_manager, app=app, **kw)


def test_loads_default_tenant_config_when_no_connection(app):
    s = _sched(app, default_tenant_id=1)
    cfg = s._load_config()
    assert cfg["smtp"]["host"] == "default.mail"
    assert cfg["alerts"]["check_seconds"] == 111


def test_loads_active_connection_tenant_config(app):
    s = _sched(app, default_tenant_id=1)
    # set_connection captures the app-user tenant (tenant B here).
    s.set_connection(object(), tenant_id=2)
    cfg = s._load_config()
    assert cfg["smtp"]["host"] == "b.mail"
    assert cfg["alerts"]["check_seconds"] == 222


def test_clear_connection_reverts_to_default_tenant(app):
    s = _sched(app, default_tenant_id=1)
    s.set_connection(object(), tenant_id=2)
    assert s._load_config()["smtp"]["host"] == "b.mail"
    s.clear_connection()
    # After clearing, falls back to the default tenant's config.
    assert s._load_config()["smtp"]["host"] == "default.mail"


def test_set_connection_without_tenant_uses_default(app):
    s = _sched(app, default_tenant_id=1)
    # No tenant_id passed (e.g. auth off, g.tenant_id None) -> default tenant.
    s.set_connection(object())
    assert s._load_config()["smtp"]["host"] == "default.mail"


def test_no_app_falls_back_to_file_config(tmp_instance):
    """Backward-compat: constructed without an app, the scheduler still reads
    the file-based config (the existing due-logic unit tests rely on this)."""
    from ruckus_dashboard.notify.config import save_config
    save_config(tmp_instance, {"smtp": {"host": "file.mail"},
                               "alerts": {"enabled": True}}, FakeSecrets())
    s = NotifyScheduler(tmp_instance, {}, FakeSecrets())
    cfg = s._load_config()
    assert cfg["smtp"]["host"] == "file.mail"


# ── /connect wires the app-user tenant into the daemon ───────────────────────

def _connect_smartzone(c, token):
    return c.post("/connect", data={
        "csrf_token": token,
        "platform": "smartzone",
        "smartzone_host": "sz.example.com",
        "smartzone_username": "admin",
        "smartzone_password": "hunter2",
        "smartzone_api_version": "auto",
    })


def test_connect_captures_logged_in_user_tenant(tmp_path, monkeypatch):
    """Auth ON: a logged-in operator's tenant is captured by the scheduler on
    /connect, so the daemon loads THAT tenant's config."""
    from ruckus_dashboard.app import create_app
    import ruckus_dashboard.clients.smartzone as sz_mod

    def fake_request_json(method, url, config, **kwargs):
        if url.endswith("/apiInfo"):
            return {"apiSupportVersions": ["v11_0"]}
        if url.endswith("/serviceTicket"):
            return {"serviceTicket": "TKT", "controllerVersion": "6.1.0"}
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(sz_mod, "request_json", fake_request_json)
    monkeypatch.setattr(
        "ruckus_dashboard.net.allowlist.assert_host_allowed",
        lambda host, config: None,
    )

    db_file = tmp_path / "ruckus.db"
    app = create_app({
        "SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True,
        "RUCKUS_AUTH_REQUIRED": True,
        "RUCKUS_DATABASE_URL": f"sqlite:///{db_file.as_posix()}",
        "RUCKUS_ADMIN_PASSWORD": "Admin-Seed-Pw-1",
        "RUCKUS_VERIFY_TLS": False, "SESSION_COOKIE_SECURE": False,
    })
    # Operator in a NON-default tenant.
    with dbmod.session_scope(app) as s:
        other = Tenant(name="tenantB")
        s.add(other)
        s.flush()
        from ruckus_dashboard.auth import users as users_mod
        users_mod.create_user(s, tenant_id=other.id, email="op@x",
                              password="Passw0rd-1", role="operator")
        other_id = other.id

    with app.test_client() as c:
        c.get("/login")
        with c.session_transaction() as s:
            csrf = s["csrf_token"]
        c.post("/login", data={"email": "op@x", "password": "Passw0rd-1",
                               "csrf_token": csrf})
        with c.session_transaction() as s:
            csrf = s["csrf_token"]
        r = _connect_smartzone(c, csrf)
        assert r.status_code == 302
    # The daemon captured the operator's tenant (not the default tenant).
    assert app.notify_scheduler._tenant_id == other_id


def test_logout_clears_scheduler_tenant(tmp_path, monkeypatch):
    """Controller /logout clears the captured tenant back to default."""
    from ruckus_dashboard.app import create_app
    import ruckus_dashboard.clients.smartzone as sz_mod

    monkeypatch.setattr(sz_mod, "request_json",
                        lambda *a, **kw: {"apiSupportVersions": ["v11_0"]}
                        if a[1].endswith("/apiInfo")
                        else {"serviceTicket": "T", "controllerVersion": "6"})
    monkeypatch.setattr(
        "ruckus_dashboard.net.allowlist.assert_host_allowed",
        lambda host, config: None,
    )
    monkeypatch.setattr(sz_mod, "disconnect_smartzone", lambda *a, **kw: None)

    app = create_app({
        "SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True,
        "RUCKUS_VERIFY_TLS": False, "SESSION_COOKIE_SECURE": False,
    })
    with app.test_client() as c:
        c.get("/")
        with c.session_transaction() as s:
            csrf = s["csrf_token"]
        _connect_smartzone(c, csrf)
        # Simulate an active tenant capture.
        app.notify_scheduler._tenant_id = 2
        with c.session_transaction() as s:
            csrf = s["csrf_token"]
        c.post("/logout", data={"csrf_token": csrf})
    assert app.notify_scheduler._tenant_id is None
