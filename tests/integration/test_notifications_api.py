from ruckus_dashboard.app import create_app


def _app(tmp_path):
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    app.instance_path = str(tmp_path)
    return app


def _login(c):
    c.get("/")
    with c.session_transaction() as s:
        s["auth"] = True
        s["connection_ids"] = []
        return s["csrf_token"]


def test_notifications_api_requires_auth(tmp_path):
    app = _app(tmp_path)
    with app.test_client() as c:
        assert c.get("/api/notifications/config").status_code == 401
        assert c.post("/api/notifications/config", json={}).status_code == 401
        assert c.post("/api/notifications/test").status_code == 401
        assert c.get("/api/reports/generate").status_code == 401


def test_notifications_config_roundtrip_masks_password(tmp_path):
    app = _app(tmp_path)
    with app.test_client() as c:
        csrf = _login(c)
        r = c.post("/api/notifications/config",
                   json={"smtp": {"host": "mail.x", "password": "hunter2"},
                         "alerts": {"enabled": True, "recipients": ["a@x"]}},
                   headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        body = r.get_json()
        assert body["smtp"]["password"] == "********"
        assert "hunter2" not in r.get_data(as_text=True)
        got = c.get("/api/notifications/config").get_json()
        assert got["smtp"]["host"] == "mail.x"
        assert got["alerts"]["recipients"] == ["a@x"]


def test_test_email_route_uses_mailer(tmp_path, monkeypatch):
    import ruckus_dashboard.routes.notifications as notif_routes
    calls = {}

    def fake_send(cfg, pw, recipients, subject, body, **kw):
        calls["recipients"] = recipients
        calls["subject"] = subject

    monkeypatch.setattr(notif_routes, "send_email", fake_send)
    app = _app(tmp_path)
    with app.test_client() as c:
        csrf = _login(c)
        c.post("/api/notifications/config",
               json={"smtp": {"host": "mail.x"},
                     "alerts": {"recipients": ["noc@x"]}},
               headers={"X-CSRF-Token": csrf})
        r = c.post("/api/notifications/test", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        assert r.get_json()["sent"] is True
        assert calls["recipients"] == ["noc@x"]


def test_notifications_page_renders(tmp_path):
    app = _app(tmp_path)
    with app.test_client() as c:
        _login(c)
        r = c.get("/notifications")
        assert r.status_code == 200
        assert b"data-notifications" in r.data
        assert b"notifications.js" in r.data
