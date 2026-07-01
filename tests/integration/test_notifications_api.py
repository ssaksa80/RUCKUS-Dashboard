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


def test_notifications_config_roundtrip_includes_sp2_fields(tmp_path):
    """Config GET/POST roundtrip carries new SP2 alert fields."""
    app = _app(tmp_path)
    with app.test_client() as c:
        csrf = _login(c)
        r = c.post("/api/notifications/config",
                   json={"smtp": {"host": "mail.x", "password": "hunter2"},
                         "alerts": {
                             "enabled": True,
                             "recipients": ["a@x"],
                             "recovery": False,
                             "debounce_seconds": 60,
                             "group_by": "none",
                         }},
                   headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        body = r.get_json()
        alerts = body["alerts"]
        assert alerts["recovery"] is False
        assert alerts["debounce_seconds"] == 60
        assert alerts["group_by"] == "none"
        # Password still masked.
        assert body["smtp"]["password"] == "********"

        # GET returns same values.
        got = c.get("/api/notifications/config").get_json()
        assert got["alerts"]["recovery"] is False
        assert got["alerts"]["debounce_seconds"] == 60


def test_test_alert_email_sends_grouped_body(tmp_path, monkeypatch):
    """kind='alerts' test email sends subject+body using the configured recipients."""
    import ruckus_dashboard.routes.notifications as notif_routes
    calls = {}

    def fake_send(cfg, pw, recipients, subject, body, **kw):
        calls["recipients"] = recipients
        calls["subject"] = subject
        calls["body"] = body

    monkeypatch.setattr(notif_routes, "send_email", fake_send)
    app = _app(tmp_path)
    with app.test_client() as c:
        csrf = _login(c)
        c.post("/api/notifications/config",
               json={"smtp": {"host": "mail.x"},
                     "alerts": {"recipients": ["noc@x"]}},
               headers={"X-CSRF-Token": csrf})
        r = c.post("/api/notifications/test",
                   json={"kind": "alerts"},
                   headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        assert r.get_json()["sent"] is True
        assert calls["recipients"] == ["noc@x"]
        # Test alert body mentions the outage channel (not just "smtp works").
        assert "alert" in calls["body"].lower() or "RUCKUS DSO" in calls["subject"]
