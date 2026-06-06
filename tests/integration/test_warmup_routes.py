from unittest.mock import MagicMock
from ruckus_dashboard.app import create_app
from ruckus_dashboard.infra.warmup import WarmupScheduler, WarmupStatus


def _make_authed_app():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    return app


def test_status_endpoint_requires_auth():
    app = _make_authed_app()
    with app.test_client() as c:
        r = c.get("/api/warmup/status")
        assert r.status_code == 401


def test_status_returns_no_scheduler_when_none():
    app = _make_authed_app()
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["auth"] = True
        r = c.get("/api/warmup/status")
        assert r.status_code == 200
        body = r.get_json()
        assert body["complete"] is True
        assert body["states"] == {}


def test_status_reflects_scheduler_snapshot():
    app = _make_authed_app()
    fake = MagicMock(spec=WarmupScheduler)
    fake.is_complete.return_value = False
    fake.snapshot.return_value = {
        "aps": WarmupStatus(slug="aps", status="running"),
        "wlans": WarmupStatus(slug="wlans", status="done",
                              summary={"total": 12}),
    }
    app.warmup_scheduler = fake

    with app.test_client() as c:
        with c.session_transaction() as s:
            s["auth"] = True
        r = c.get("/api/warmup/status")
        body = r.get_json()
        assert body["complete"] is False
        assert body["states"]["aps"]["status"] == "running"
        assert body["states"]["wlans"]["status"] == "done"
        assert body["states"]["wlans"]["summary"] == {"total": 12}
