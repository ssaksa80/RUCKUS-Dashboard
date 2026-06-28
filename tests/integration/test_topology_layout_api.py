from ruckus_dashboard.app import create_app
from ruckus_dashboard.auth.session_store import ConnectionConfig


def _app(tmp_path):
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    app.instance_path = str(tmp_path)
    return app


def _login(app, c):
    conn = ConnectionConfig(platform="smartzone",
        api_base="https://sz.example:8443/wsg/api/public", display_name="SZ",
        auth_token="t", api_version="v11_0", verify_tls=False,
        token_expires_at=9999999999)
    cid = app.connection_store.put(conn)
    c.get("/")  # seed csrf token
    with c.session_transaction() as s:
        s["auth"] = True
        s["connection_ids"] = [cid]
        csrf = s["csrf_token"]
    return csrf


def test_layout_requires_auth(tmp_path):
    app = _app(tmp_path)
    with app.test_client() as c:
        assert c.get("/api/topology/layout").status_code == 401
        assert c.post("/api/topology/layout", json={}).status_code == 401
        assert c.delete("/api/topology/layout").status_code == 401


def test_layout_roundtrip_and_reset(tmp_path):
    app = _app(tmp_path)
    with app.test_client() as c:
        csrf = _login(app, c)
        # empty before save
        assert c.get("/api/topology/layout").get_json()["positions"] == {}
        body = {"positions": {"controller": {"x": 1.5, "y": -2},
                              "B0:7C:51:19:52:6C": {"x": 100, "y": 200}}}
        r = c.post("/api/topology/layout", json=body,
                   headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200 and r.get_json()["saved"] == 2
        got = c.get("/api/topology/layout").get_json()["positions"]
        assert got["B0:7C:51:19:52:6C"] == {"x": 100.0, "y": 200.0}
        r = c.delete("/api/topology/layout", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        assert c.get("/api/topology/layout").get_json()["positions"] == {}


def test_layout_rejects_garbage_and_missing_csrf(tmp_path):
    app = _app(tmp_path)
    with app.test_client() as c:
        csrf = _login(app, c)
        r = c.post("/api/topology/layout", json={"positions": {"a": {"x": "nan?", "y": []}}},
                   headers={"X-CSRF-Token": csrf})
        assert r.status_code == 400
        r = c.post("/api/topology/layout", data="not json",
                   headers={"X-CSRF-Token": csrf},
                   content_type="application/json")
        assert r.status_code == 400
        # missing CSRF header -> 400 from validate_csrf
        r = c.post("/api/topology/layout", json={"positions": {}})
        assert r.status_code == 400
