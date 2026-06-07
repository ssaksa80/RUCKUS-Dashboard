from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import api_explorer as ax_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate


def _ctx(available, filters=None):
    return FetcherContext(connection=None, config={}, filters=filters,
                          capability_gate=CapabilityGate(available=available),
                          connection_label="")


def test_api_explorer_lists_discovered_ops():
    ops = {("GET", "/rkszones"), ("POST", "/query/ap"), ("POST", "/switch/view/details")}
    out = ax_mod.fetch(_ctx(ops))
    assert out["raw_count"] == 3
    paths = {i["path"] for i in out["items"]}
    assert "/rkszones" in paths
    assert "/switch/view/details" in paths


def test_api_explorer_source_classification():
    ops = {("GET", "/rkszones"), ("POST", "/switch/view/details")}
    out = ax_mod.fetch(_ctx(ops))
    by_path = {i["path"]: i for i in out["items"]}
    assert by_path["/rkszones"]["source"] == "wireless"
    assert by_path["/switch/view/details"]["source"] == "switch"


def test_api_explorer_filter_by_source():
    ops = {("GET", "/rkszones"), ("POST", "/switch/view/details")}
    out = ax_mod.fetch(_ctx(ops, filters={"source": "switch"}))
    assert out["raw_count"] == 1
    assert out["items"][0]["path"] == "/switch/view/details"


def test_api_explorer_filter_by_search():
    ops = {("GET", "/rkszones"), ("POST", "/query/ap"), ("POST", "/query/client")}
    out = ax_mod.fetch(_ctx(ops, filters={"search": "query"}))
    assert out["raw_count"] == 2


def test_api_explorer_summary():
    data = {"items": [
        {"source": "wireless", "method": "GET"},
        {"source": "wireless", "method": "POST"},
        {"source": "switch", "method": "POST"},
    ]}
    s = ax_mod.summary(data)
    assert s["total_ops"] == 3
    assert s["wireless_ops"] == 2
    assert s["switch_ops"] == 1
    assert s["by_method"]["POST"] == 2


def test_api_explorer_registered_warmup_false():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["api-explorer"].fetcher is ax_mod.fetch
    assert MODULES["api-explorer"].warmup is False
