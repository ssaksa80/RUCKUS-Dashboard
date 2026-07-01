import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "RUCKUS"))
from ruckus_dashboard.app import create_app

def test_app_factory_returns_flask():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": False})
    assert app.name.startswith("ruckus_dashboard")

def test_healthz_returns_200():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": False})
    with app.test_client() as c:
        r = c.get("/healthz")
        assert r.status_code == 200
        assert r.json["ok"] is True

def test_security_headers_present():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": False})
    with app.test_client() as c:
        r = c.get("/healthz")
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert "Strict-Transport-Security" in r.headers
        assert r.headers["Cache-Control"] == "no-store"


def test_readyz_ready_returns_200():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": False})
    with app.test_client() as c:
        r = c.get("/readyz")
        assert r.status_code == 200
        assert r.json["ready"] is True


def test_readyz_not_ready_without_secret_key_returns_503():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": False})
    # Simulate a misconfigured app that can't sign sessions: no usable key.
    app.config["SECRET_KEY"] = ""
    with app.test_client() as c:
        r = c.get("/readyz")
        assert r.status_code == 503
        assert r.json["ready"] is False
        assert "reason" in r.json


def test_readyz_not_ready_when_instance_unwritable_returns_503(monkeypatch):
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": False})
    from ruckus_dashboard import app as app_module

    def _boom(_path):
        raise OSError("read-only file system")

    monkeypatch.setattr(app_module, "_instance_writable", _boom)
    with app.test_client() as c:
        r = c.get("/readyz")
        assert r.status_code == 503
        assert r.json["ready"] is False
        assert "reason" in r.json


def test_healthz_still_always_ok_even_when_not_ready():
    # Liveness must stay 200 regardless of readiness state.
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": False})
    app.config["SECRET_KEY"] = ""
    with app.test_client() as c:
        r = c.get("/healthz")
        assert r.status_code == 200
        assert r.json["ok"] is True
