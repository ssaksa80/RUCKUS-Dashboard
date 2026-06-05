from ruckus_dashboard.app import create_app


def test_dashboard_js_served_and_has_router():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        r = c.get("/static/dashboard.js")
        assert r.status_code == 200
        body = r.data.decode()
        for symbol in ["startModulePoller", "stopModulePoller",
                       "renderModule", "renderTile",
                       "document.hidden", "fetch("]:
            assert symbol in body, f"missing JS symbol: {symbol}"
