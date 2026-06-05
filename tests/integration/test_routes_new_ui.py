from ruckus_dashboard.app import create_app

def make_app():
    return create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})

def test_module_list_endpoint():
    app = make_app()
    with app.test_client() as c:
        r = c.get("/api/modules")
        assert r.status_code == 200
        slugs = {m["slug"] for m in r.json["modules"]}
        assert "aps" in slugs
        assert "switches" in slugs
        assert len(slugs) == 18

def test_module_data_endpoint_unauthenticated_401():
    app = make_app()
    with app.test_client() as c:
        r = c.get("/api/modules/aps")
        assert r.status_code == 401
        assert r.json.get("reauth") is True

def test_unknown_module_404():
    app = make_app()
    with app.test_client() as c:
        r = c.get("/api/modules/does-not-exist")
        assert r.status_code == 404
