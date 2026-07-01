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


def test_dashboard_js_escapes_table_output():
    """formatCell/KPI strip/filters must HTML-escape controller-sourced strings
    (a hostile SSID like <img onerror=...> must not execute)."""
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        assert "function _escape" in body
        assert "_escape(value)" in body          # formatCell default branch
        assert "_escape(formatKpiValue(v))" in body  # KPI strip
        assert "&quot;" in body                  # attribute-context escaping


def test_wall_mode_collapses_layout_grid():
    """DSO wall mode hides the sidebar; the grid must collapse to one column or
    .main lands in the leftover 240px sidebar track."""
    import pathlib
    css = pathlib.Path("RUCKUS/ruckus_dashboard/static/styles.css").read_text(encoding="utf-8")
    assert "body.dso-mode .layout" in css
    assert "grid-template-columns: 1fr" in css


def test_drill_renders_from_cached_payload_and_stacks_summary():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        for sym in ["_kvListHtml", "_humanKey", "drill-section-title",
                    "showTab", "_drillUpdatePayload"]:
            assert sym in body, f"missing {sym}"


def test_drill_css_present():
    import pathlib
    css = pathlib.Path("RUCKUS/ruckus_dashboard/static/styles.css").read_text(encoding="utf-8")
    for rule in [".drill-hero", ".drill-tab.active", ".kv-row", ".kv-key",
                 ".drill-section-title", ".drill-raw"]:
        assert rule in css, f"missing {rule}"


def test_dashboard_js_has_view_switcher_and_grid():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        for sym in ["wireViewToggle", "renderGrid", "renderData", "activeViews",
                    "card-grid"]:
            assert sym in body, f"missing {sym}"


def test_dashboard_js_kpi_filter_clicks():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        for sym in ["KPI_FILTER_MAP", "applyKpiFilter", "data-kpi-key",
                    "poor_signal", "band_5"]:
            assert sym in body, f"missing {sym}"


def test_dashboard_js_apply_filters_supports_search_and_range_keys():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        for sym in ['"search:"', '"range:"', "Array.isArray(val)",
                    "startsWith(\"search:\")", "startsWith(\"range:\")",
                    "__search"]:
            assert sym in body, f"missing {sym}"


def test_dashboard_js_render_filters_per_column_controls_and_clear():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        for sym in ['type="search" data-filter-key="search:',
                    'type="number"', 'data-filter-key="range:',
                    "data-filter-clear", "filterSignature",
                    '_escape']:
            assert sym in body, f"missing {sym}"
        # build-once staleness gate must be gone (options rebuild each render)
        assert "host.dataset.built === slug" not in body, \
            "renderFilters must not short-circuit on dataset.built"


def test_dashboard_js_kpi_and_poor_ap_reflect_into_selects():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        # KPI scalar filters still write unprefixed keys and reflect into SELECTs.
        assert 'data-filter-key="ap"' in body          # poor-AP reflect selector
        assert "applyKpiFilter" in body
        assert "ctrl.tagName === \"SELECT\"" in body
        # Single-select reflect must not assume multi-select.
        assert "band_5" in body and "poor_signal" in body


def test_dashboard_js_drill_table_filters_present():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        for sym in ["renderDrillFilters", "_applyDrillFilters", "drillFilters",
                    ":drill:", "data-drill-filter-key"]:
            assert sym in body, f"missing {sym}"
        # renderGenericTable still exists and is escape-safe
        assert "function renderGenericTable" in body
        assert "_escape(v ?? " in body or "_escape(v" in body


def test_dashboard_js_has_email_tab_handler():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        for sym in ["wireEmailTab", "/api/reports/tab", "X-CSRF-Token",
                    "data-email-tab", "activeFilters"]:
            assert sym in body, f"missing JS symbol: {sym}"


def test_dashboard_js_email_tab_reads_csrf_meta():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        assert 'meta[name="csrf-token"]' in body
