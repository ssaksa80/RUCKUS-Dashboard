import pathlib


def test_topology_js_symbols_present():
    js = pathlib.Path("RUCKUS/ruckus_dashboard/static/topology.js").read_text(encoding="utf-8")
    for sym in ["layoutGraph", "renderTopology", "/api/modules/topology", "viewBox",
                "diffAndToast", "centerOn", "applySearch", "tooltipHtml",
                "api/topology/layout", "data-topo-search", "X-CSRF-Token",
                "expanded", "pinned", "refanChildren", "visibleGraph",
                "data-topo-arrange", "data-topo-export"]:
        assert sym in js, f"missing {sym}"


def test_topology_template_has_v2_hooks():
    html = pathlib.Path("RUCKUS/ruckus_dashboard/templates/topology.html").read_text(encoding="utf-8")
    for hook in ["data-topo-search", "data-topo-save", "data-topo-reset",
                 "data-topo-arrange", "data-topo-export",
                 "data-topo-tooltip", "data-topo-toasts", "csrf-token"]:
        assert hook in html, f"missing {hook}"


def test_topology_css_has_pulse_and_toast():
    css = pathlib.Path("RUCKUS/ruckus_dashboard/static/styles.css").read_text(encoding="utf-8")
    for rule in ["@keyframes topo-pulse", ".topo-toast", ".topo-tooltip",
                 ".topo-badge", ".topo-node.dimmed", "stroke-dasharray"]:
        assert rule in css, f"missing {rule}"


def test_topology_js_animated_arrange_reset():
    import pathlib
    js = pathlib.Path("RUCKUS/ruckus_dashboard/static/topology.js").read_text(encoding="utf-8")
    assert "animateToPositions" in js
    assert "requestAnimationFrame" in js
    # Reset must not refetch from the controller (instant local relayout).
    assert "freshLayout" in js


def test_topology_js_live_rates_and_ap_signal():
    import pathlib
    js = pathlib.Path("RUCKUS/ruckus_dashboard/static/topology.js").read_text(encoding="utf-8")
    for sym in ["updateRates", "fmtRate", "prevTraffic", "rssi_avg", "live rate"]:
        assert sym in js, f"missing {sym}"
