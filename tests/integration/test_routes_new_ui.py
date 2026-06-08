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

def test_module_list_includes_columns_and_filters():
    app = make_app()
    with app.test_client() as c:
        r = c.get("/api/modules")
        assert r.status_code == 200
        for m in r.json["modules"]:
            assert "columns" in m, f"{m['slug']} missing columns"
            assert "filters" in m, f"{m['slug']} missing filters"
            assert isinstance(m["columns"], list)
            assert isinstance(m["filters"], list)
        by_slug = {m["slug"]: m for m in r.json["modules"]}
        aps = by_slug["aps"]
        assert aps["columns"], "aps should declare columns"
        assert {"label", "key", "kind"} <= set(aps["columns"][0].keys())
        assert aps["filters"], "aps should declare filters"
        assert {"key", "label", "kind"} <= set(aps["filters"][0].keys())


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


def test_drill_route_unauthenticated_401():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/api/modules/aps/AB:CD:EF:01:02:03")
        assert r.status_code == 401


def test_drill_route_unknown_module_404():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/api/modules/does-not-exist/abc")
        assert r.status_code == 404


def _authed_app_with_conn():
    """App with one stored SmartZone connection + matching capability."""
    import ruckus_dashboard.modules as modmod
    from ruckus_dashboard.auth.session_store import ConnectionConfig
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    conn = ConnectionConfig(
        platform="smartzone", api_base="https://sz/wsg/api/public",
        display_name="SZ-LAB", auth_token="t", api_version="v11_0",
        verify_tls=False, token_expires_at=9999999999,
    )
    cid = app.connection_store.put(conn)
    # Satisfy capability gate for every module under test
    app.available_ops = {("POST", "/query/client"), ("POST", "/query/roguesInfoList")}
    return app, cid, modmod


def test_module_data_fetcher_error_returns_envelope_not_500():
    """A single module's upstream RuckusClientError must NOT 500 the request.

    Regression for live SmartZone HTTP 400 on query/client + query/roguesInfoList:
    the route must return a 200 envelope with status!=complete and the upstream
    error surfaced in controller_errors, so the page survives and the operator
    sees what failed.
    """
    import dataclasses
    from ruckus_dashboard.clients.base import RuckusClientError
    app, cid, modmod = _authed_app_with_conn()

    def boom(ctx):
        raise RuckusClientError(
            "SmartZone query/client failed with HTTP 400.", 400,
            {"raw": "validation error: bad payload"},
        )

    original = modmod.MODULES["clients"]
    modmod.MODULES["clients"] = dataclasses.replace(original, fetcher=boom)
    try:
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["auth"] = True
                s["connection_ids"] = [cid]
            r = c.get("/api/modules/clients")
            assert r.status_code == 200, "must not 500 on a single module failure"
            body = r.get_json()
            assert body["status"] in ("error", "partial")
            assert body["controller_errors"], "upstream error must be surfaced"
            ce = body["controller_errors"][0]
            assert ce["status"] == 400
            assert ce["connection"] == "SZ-LAB"
            assert ce["endpoint"] == "clients"
    finally:
        modmod.MODULES["clients"] = original


def test_module_data_partial_when_one_of_two_controllers_fails():
    """With 2 controllers, one OK + one failing → status 'partial', data kept."""
    import dataclasses
    from ruckus_dashboard.clients.base import RuckusClientError
    from ruckus_dashboard.auth.session_store import ConnectionConfig
    import ruckus_dashboard.modules as modmod

    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    app.available_ops = {("POST", "/query/client")}
    good = ConnectionConfig(platform="smartzone", api_base="https://a/wsg/api/public",
                            display_name="SZ-A", auth_token="t", api_version="v11_0",
                            verify_tls=False, token_expires_at=9999999999)
    bad = ConnectionConfig(platform="smartzone", api_base="https://b/wsg/api/public",
                           display_name="SZ-B", auth_token="t", api_version="v11_0",
                           verify_tls=False, token_expires_at=9999999999)
    cid_a = app.connection_store.put(good)
    cid_b = app.connection_store.put(bad)

    def flaky(ctx):
        if ctx.connection.display_name == "SZ-B":
            raise RuckusClientError("boom", 502, {"raw": "down"})
        return {"items": [{"id": "x", "mac": "x"}], "raw_count": 1}

    original = modmod.MODULES["clients"]
    modmod.MODULES["clients"] = dataclasses.replace(original, fetcher=flaky)
    try:
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["auth"] = True
                s["connection_ids"] = [cid_a, cid_b]
            r = c.get("/api/modules/clients")
            assert r.status_code == 200
            body = r.get_json()
            assert body["status"] == "partial"
            assert len(body["data"]["items"]) == 1     # SZ-A data preserved
            assert len(body["controller_errors"]) == 1  # SZ-B error surfaced
    finally:
        modmod.MODULES["clients"] = original
