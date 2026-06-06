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
