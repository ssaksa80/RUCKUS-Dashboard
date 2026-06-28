"""Login flow: GET /, POST /connect, POST /logout.

Tests run against the real app factory; SmartZone HTTP I/O is monkeypatched
at the ``request_json`` boundary so we exercise the route + form handling
without speaking to a controller.
"""
from __future__ import annotations


from ruckus_dashboard.app import create_app
from ruckus_dashboard.auth.session_store import ConnectionConfig


def make_app(**overrides):
    cfg = {
        "SECRET_KEY": "test-secret",
        "RUCKUS_ENABLE_NEW_UI": True,
        "SESSION_COOKIE_SECURE": False,
        "RUCKUS_VERIFY_TLS": False,
        "RUCKUS_CAPABILITY_DISCOVERY": False,
    }
    cfg.update(overrides)
    return create_app(cfg)


def seed_csrf(client):
    """GET / to seed the csrf_token in the session, return the token."""
    client.get("/")
    with client.session_transaction() as s:
        return s["csrf_token"]


# ─────────────────────────────────────────────────────────────────────────────
# GET /  (login vs overview)
# ─────────────────────────────────────────────────────────────────────────────
def test_login_page_renders_when_unauthenticated_new_ui():
    app = make_app()
    with app.test_client() as c:
        r = c.get("/")
        assert r.status_code == 200
        assert b'name="platform"' in r.data
        assert b'name="smartzone_host"' in r.data
        assert b'name="tenant_id"' in r.data
        assert b'name="csrf_token"' in r.data


def test_overview_renders_when_authenticated():
    app = make_app()
    with app.test_client() as c:
        # Seed an authenticated session pointing at a stored connection.
        conn = ConnectionConfig(
            platform="smartzone",
            api_base="https://sz.example.com:8443/wsg/api/public",
            display_name="SmartZone test",
            auth_token="ticket",
            verify_tls=False,
            api_version="v9_0",
        )
        cid = app.connection_store.put(conn)
        with c.session_transaction() as s:
            s["auth"] = True
            s["connection_ids"] = [cid]
        r = c.get("/")
        assert r.status_code == 200
        assert b"DSO Overview" in r.data
        # login form must NOT be present once authenticated
        assert b'name="smartzone_host"' not in r.data


# ─────────────────────────────────────────────────────────────────────────────
# POST /connect
# ─────────────────────────────────────────────────────────────────────────────
def test_connect_post_smartzone_happy(monkeypatch):
    app = make_app()

    def fake_request_json(method, url, config, **kwargs):
        if url.endswith("/apiInfo"):
            return {"apiSupportVersions": ["v9_0", "v10_0", "v11_0"]}
        if url.endswith("/serviceTicket"):
            return {"serviceTicket": "TICKET-XYZ", "controllerVersion": "6.1.0"}
        raise AssertionError(f"unexpected URL: {url}")

    import ruckus_dashboard.clients.smartzone as sz_mod
    monkeypatch.setattr(sz_mod, "request_json", fake_request_json)
    monkeypatch.setattr(
        "ruckus_dashboard.net.allowlist.assert_host_allowed",
        lambda host, config: None,
    )

    with app.test_client() as c:
        token = seed_csrf(c)
        r = c.post(
            "/connect",
            data={
                "csrf_token": token,
                "platform": "smartzone",
                "smartzone_host": "sz.example.com",
                "smartzone_username": "admin",
                "smartzone_password": "hunter2",
                "smartzone_api_version": "auto",
            },
        )
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/")
        with c.session_transaction() as s:
            assert s.get("auth") is True
            assert len(s.get("connection_ids", [])) == 1
        assert app.connection_store.count() == 1


def test_connect_post_missing_csrf_400():
    app = make_app()
    with app.test_client() as c:
        seed_csrf(c)
        r = c.post("/connect", data={"platform": "smartzone"})
        assert r.status_code == 400


def test_connect_post_invalid_platform_flashes_and_redirects():
    app = make_app()
    with app.test_client() as c:
        token = seed_csrf(c)
        r = c.post(
            "/connect",
            data={"csrf_token": token, "platform": "unknown"},
        )
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/")
        with c.session_transaction() as s:
            assert not s.get("auth")


# ─────────────────────────────────────────────────────────────────────────────
# POST /logout
# ─────────────────────────────────────────────────────────────────────────────
def test_logout_clears_session(monkeypatch):
    app = make_app()
    app.available_ops = {("GET", "/rkszones")}
    with app.test_client() as c:
        # seed an authenticated session
        conn = ConnectionConfig(
            platform="smartzone",
            api_base="https://sz.example.com:8443/wsg/api/public",
            display_name="SmartZone test",
            auth_token="TICKET",
            verify_tls=False,
            api_version="v9_0",
        )
        cid = app.connection_store.put(conn)
        token = seed_csrf(c)
        with c.session_transaction() as s:
            s["auth"] = True
            s["connection_ids"] = [cid]

        # avoid real HTTP in disconnect_smartzone
        import ruckus_dashboard.clients.smartzone as sz_mod
        monkeypatch.setattr(sz_mod, "request_json", lambda *a, **kw: {})

        r = c.post("/logout", data={"csrf_token": token})
        assert r.status_code == 302
        with c.session_transaction() as s:
            assert not s.get("auth")
            assert not s.get("connection_ids")
        assert app.connection_store.count() == 0
        assert app.available_ops == set()


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end: connect, then hit a module endpoint
# ─────────────────────────────────────────────────────────────────────────────
def test_module_data_after_connect_returns_envelope_not_401(monkeypatch):
    app = make_app()

    def fake_request_json(method, url, config, **kwargs):
        if url.endswith("/apiInfo"):
            return {"apiSupportVersions": ["v9_0"]}
        if url.endswith("/serviceTicket"):
            return {"serviceTicket": "T", "controllerVersion": "6.1"}
        # No openapi doc available -> capability discovery records nothing.
        from ruckus_dashboard.clients.base import RuckusClientError
        raise RuckusClientError("not found", 404)

    import ruckus_dashboard.clients.smartzone as sz_mod
    monkeypatch.setattr(sz_mod, "request_json", fake_request_json)
    monkeypatch.setattr(
        "ruckus_dashboard.net.allowlist.assert_host_allowed",
        lambda host, config: None,
    )

    with app.test_client() as c:
        token = seed_csrf(c)
        r = c.post(
            "/connect",
            data={
                "csrf_token": token,
                "platform": "smartzone",
                "smartzone_host": "sz.example.com",
                "smartzone_username": "admin",
                "smartzone_password": "pw",
            },
        )
        assert r.status_code == 302
        # Now request module data. APs requires ("POST","/query/ap") cap.
        # Discovery failed -> available_ops is empty -> disabled envelope.
        r2 = c.get("/api/modules/aps")
        assert r2.status_code == 200
        body = r2.get_json()
        assert body["data"]["disabled"] is True
        assert "missing_capabilities" in body["data"]


def test_connect_starts_warmup_scheduler():
    from ruckus_dashboard.app import create_app
    from ruckus_dashboard.infra.warmup import WarmupScheduler
    import responses

    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})

    base = "https://sz.example:8443/wsg/api/public"
    with responses.RequestsMock() as r:
        r.add(responses.GET, f"{base}/apiInfo",
              json={"apiSupportVersions": ["v11_0"]}, status=200)
        r.add(responses.POST, f"{base}/v11_0/serviceTicket",
              json={"serviceTicket": "tkt", "controllerVersion": "6"}, status=200)
        r.add(responses.GET, "https://sz.example:8443/wsg/apiDoc/openapi",
              status=404)
        r.add(responses.GET, "https://sz.example:8443/switchm/api/openapi",
              status=404)

        with app.test_client() as c:
            c.get("/")
            with c.session_transaction() as s:
                token = s["csrf_token"]
            resp = c.post("/connect", data={
                "csrf_token": token,
                "platform": "smartzone",
                "smartzone_host": "sz.example",
                "smartzone_username": "u",
                "smartzone_password": "p",
                "smartzone_api_version": "auto",
                "smartzone_skip_tls_verify": "1",
            }, follow_redirects=False)
            assert resp.status_code == 302
            assert app.warmup_scheduler is not None
            assert isinstance(app.warmup_scheduler, WarmupScheduler)


def test_logout_cancels_warmup_scheduler():
    from ruckus_dashboard.app import create_app
    from ruckus_dashboard.infra.warmup import WarmupScheduler
    from unittest.mock import MagicMock

    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    fake_scheduler = MagicMock(spec=WarmupScheduler)
    app.warmup_scheduler = fake_scheduler

    with app.test_client() as c:
        c.get("/")
        with c.session_transaction() as s:
            s["auth"] = True
            s["connection_ids"] = []
            token = s["csrf_token"]
        resp = c.post("/logout", data={"csrf_token": token}, follow_redirects=False)
        assert resp.status_code in (200, 302)
        fake_scheduler.cancel.assert_called_once()
        assert app.warmup_scheduler is None
