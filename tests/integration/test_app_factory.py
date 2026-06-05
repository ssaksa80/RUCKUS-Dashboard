import sys, pathlib
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
