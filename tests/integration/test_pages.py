from ruckus_dashboard.app import create_app


def test_root_renders_legacy_when_flag_off():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": False})
    with app.test_client() as c:
        r = c.get("/")
        assert r.status_code == 200
        assert b"Legacy dashboard placeholder" in r.data \
            or b"RUCKUS NOC Assurance Dashboard" in r.data


def test_root_renders_new_ui_when_flag_on():
    # With the login flow landed (Task 32), GET / shows the login form when
    # unauthenticated. Once a session has auth=True we should see the
    # sidebar overview shell.
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        # Unauthenticated -> login form.
        r_login = c.get("/")
        assert r_login.status_code == 200
        assert b'name="platform"' in r_login.data
        # Inject an authenticated session and re-request.
        with c.session_transaction() as s:
            s["auth"] = True
            s["connection_ids"] = []
        r = c.get("/")
        assert r.status_code == 200
        assert b"DSO Overview" in r.data
        assert b"sidebar" in r.data.lower()


def test_module_page_route_renders():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/m/aps")
        assert r.status_code == 200
        assert b"Access Points" in r.data


def test_unknown_module_page_404():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/m/does-not-exist")
        assert r.status_code == 404


def test_overview_renders_warmup_strip_when_authenticated():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        c.get("/")
        with c.session_transaction() as s:
            s["auth"] = True
            s["connection_ids"] = []
        r = c.get("/")
        assert r.status_code == 200
        assert b"warmup-strip" in r.data
        assert b"tile-skeleton" in r.data


def test_overview_module_route_renders_tile_grid():
    # /m/overview must render the DSO tile grid, not the empty module table.
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/m/overview")
        assert r.status_code == 200
        assert b"tile-grid" in r.data
        assert b"data-kpi-strip" not in r.data  # not the module table page


def test_drill_page_404_for_module_without_drill():
    # Controller has no drill_fetcher; a drill URL must 404, not render a broken
    # page that then polls a 404 drill endpoint.
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/m/controller/some-node-id")
        assert r.status_code == 404


def test_shell_renders_health_bar_and_pinned_nav():
    # Health bar + pinned DSO Overview present on a normal module page.
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/m/aps")
        assert b"data-health-bar" in r.data
        assert b"nav-pinned" in r.data


def test_topology_route_renders_graph_container():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/m/topology")
        assert r.status_code == 200
        assert b"data-topology" in r.data
        assert b"topology.js" in r.data


def test_csp_header_present_and_strict():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        # No inline <script> blocks remain (CSP would block them silently).
        assert b"<script>" not in r.data


def test_api_explorer_moved_to_topbar_button():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        html = c.get("/m/aps").data.decode()
        # No sidebar nav entry; topbar link opens a new tab instead.
        assert 'data-slug="api-explorer"' not in html.split("topbar-actions")[0].split("</aside>")[0]
        assert 'href="/m/api-explorer" target="_blank"' in html


def test_module_page_has_email_tab_button_and_csrf_meta(tmp_path):
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        c.get("/")
        with c.session_transaction() as s:
            s["auth"] = True
            s["connection_ids"] = []
        r = c.get("/m/clients")
        assert r.status_code == 200
        body = r.data.decode()
        assert '<meta name="csrf-token"' in body
        assert "data-email-tab" in body
        assert "Email this tab" in body
