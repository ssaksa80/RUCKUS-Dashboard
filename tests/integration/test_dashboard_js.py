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


def test_dashboard_js_contains_warmup_integration():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        r = c.get("/static/dashboard.js")
        body = r.data.decode()
        for symbol in ["startWarmupStream", "updateTile", "EventSource",
                       "/api/warmup", "module-ready", "data-warmup-strip",
                       "data-tile-status"]:
            assert symbol in body, f"missing symbol: {symbol}"


def test_dashboard_js_contains_drill_rendering():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        r = c.get("/static/dashboard.js")
        body = r.data.decode()
        for symbol in ["renderDrill", "data-drill-body", "renderKeyVals",
                       "renderGenericTable"]:
            assert symbol in body, f"missing symbol: {symbol}"


def test_dashboard_js_contains_columns_filters_rowclick():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        r = c.get("/static/dashboard.js")
        body = r.data.decode()
        for symbol in ["renderColumns", "renderFilters", "humanBytes",
                       "humanUptime", "status-pill", "data-href", "/m/"]:
            assert symbol in body, f"missing symbol: {symbol}"


def test_dashboard_js_contains_health_bar():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        for symbol in ["renderHealthBar", "applyHealthState", "pickSummaryNumber",
                       "data-health-value"]:
            assert symbol in body, f"missing symbol: {symbol}"
