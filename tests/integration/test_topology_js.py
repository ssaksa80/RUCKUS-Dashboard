import pathlib


def test_topology_js_symbols_present():
    js = pathlib.Path("RUCKUS/ruckus_dashboard/static/topology.js").read_text(encoding="utf-8")
    for sym in ["layoutGraph", "renderTopology", "/api/modules/topology", "viewBox",
                "diffAndToast", "centerOn", "applySearch", "tooltipHtml",
                "api/topology/layout", "data-topo-search", "X-CSRF-Token",
                "expanded", "pinned"]:
        assert sym in js, f"missing {sym}"


def test_topology_template_has_v2_hooks():
    html = pathlib.Path("RUCKUS/ruckus_dashboard/templates/topology.html").read_text(encoding="utf-8")
    for hook in ["data-topo-search", "data-topo-save", "data-topo-reset",
                 "data-topo-tooltip", "data-topo-toasts", "csrf-token"]:
        assert hook in html, f"missing {hook}"


def test_topology_css_has_pulse_and_toast():
    css = pathlib.Path("RUCKUS/ruckus_dashboard/static/styles.css").read_text(encoding="utf-8")
    for rule in ["@keyframes topo-pulse", ".topo-toast", ".topo-tooltip",
                 ".topo-badge", ".topo-node.dimmed"]:
        assert rule in css, f"missing {rule}"
