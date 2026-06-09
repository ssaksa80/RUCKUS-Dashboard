import pathlib


def test_topology_js_symbols_present():
    js = pathlib.Path("RUCKUS/ruckus_dashboard/static/topology.js").read_text(encoding="utf-8")
    for sym in ["layoutGraph", "renderTopology", "/api/modules/topology", "viewBox"]:
        assert sym in js, f"missing {sym}"
