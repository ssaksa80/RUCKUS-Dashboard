import pathlib

from ruckus_dashboard.app import create_app

CSS = pathlib.Path("RUCKUS/ruckus_dashboard/static/styles.css")


def _css():
    return CSS.read_text(encoding="utf-8")


def _reduced_motion_block():
    """Return the body of the single @media (prefers-reduced-motion: reduce)
    block via a balanced-brace scan, so assertions about the guard test the
    guard itself — not unrelated rules that happen to follow it in the file
    (the SP5 motion rules are appended after the guard by design)."""
    css = _css()
    marker = "@media (prefers-reduced-motion: reduce)"
    start = css.index(marker) + len(marker)
    open_brace = css.index("{", start)
    depth = 0
    for i in range(open_brace, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[open_brace + 1:i]
    raise AssertionError("unterminated @media (prefers-reduced-motion) block")


def test_motion_tokens_present():
    css = _css()
    for token in [
        "--glow-ok", "--glow-watch", "--glow-critical", "--glow-accent",
        "--motion-fast", "--motion-base", "--motion-slow",
        "--ease-out", "--pulse-critical-period",
    ]:
        assert token in css, f"missing token {token}"


def test_reduced_motion_global_killswitch():
    css = _css()
    assert "@media (prefers-reduced-motion: reduce)" in css
    # The guard must flatten motion to none.
    assert "animation: none" in css
    assert "transition: none" in css


def test_reduced_motion_covers_legacy_topo_and_toast():
    """Spec §3 / Q5: the pre-existing infinite topo-pulse and toast-in must be
    brought under the reduced-motion guard (latent a11y bug fixed here)."""
    guard = _reduced_motion_block()
    assert ".topo-node.pulse > circle" in guard
    assert ".topo-toast" in guard


def test_state_glow_rules_present():
    css = _css()
    for rule in [
        ".kpi-card.critical .kpi-value", ".kpi-card.watch .kpi-value",
        ".kpi-card.ok .kpi-value",
        ".status-error", ".status-partial", ".status-complete",
        ".health-chip.danger",
    ]:
        assert rule in css, f"missing glow rule {rule}"
    # Glow uses the tokens + box/text-shadow.
    assert "var(--glow-critical)" in css
    assert "var(--glow-watch)" in css
    assert "var(--glow-ok)" in css


def test_critical_breathing_keyframe():
    css = _css()
    assert "@keyframes glow-critical-breathe" in css
    assert "var(--pulse-critical-period)" in css


def test_topo_pulse_retokened_to_glow_critical():
    """Spec §4.3.5: topo-pulse keeps its cadence but uses the shared token."""
    css = _css()
    assert "@keyframes topo-pulse" in css  # still defined
    # the highlight drop-shadow / pulse now references the critical glow token
    assert "drop-shadow(0 0 8px var(--glow-critical))" in css


def test_entrance_and_pulse_keyframes_present():
    css = _css()
    for kf in [
        "@keyframes tile-enter", "@keyframes refresh-ring",
        "@keyframes value-flash", "@keyframes warmup-sheen",
    ]:
        assert kf in css, f"missing keyframe {kf}"


def test_trigger_classes_present():
    css = _css()
    # one-shot pulse fired by motion.js pulse(root, "refreshed")
    assert ".module-refreshed::after" in css
    # value flash for non-numeric/formatted KPI changes
    assert ".value-changed" in css
    # staggered tile entrance keyed to nth-child (no JS list)
    assert ".tile-grid .tile" in css
    assert "nth-child" in css
    # warmup sheen only while filling
    assert '.warmup-fill:not([style*="width: 100%"])::after' in css \
        or ".warmup-fill::after" in css


def test_dso_mode_intensifies_glow():
    """Q3: wall mode intensifies (larger halo); desk mode subtle."""
    css = _css()
    assert "body.dso-mode .kpi-card.critical .kpi-value" in css
    assert "body.dso-mode .health-chip.danger" in css


def test_warmup_width_transition_preserved():
    """The warmup bar width transition (styles.css:108) must remain; only the
    decorative sheen is gated. Guards against a future over-broad kill-switch."""
    css = _css()
    assert "transition: width 0.3s" in css
    guard = _reduced_motion_block()
    # the guard targets the sheen pseudo-element, never the base .warmup-fill width
    assert ".warmup-fill::after" in guard
    assert ".warmup-fill {" not in guard


def test_motion_js_served_with_js_content_type():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        r = c.get("/static/motion.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["Content-Type"].lower()


def test_motion_js_public_api_symbols():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/motion.js").data.decode()
        for sym in ["function animateCount", "function pulse",
                    "function motionReduced", "window.RuckusMotion"]:
            assert sym in body, f"missing {sym}"


def test_motion_js_is_leak_safe_and_reduced_motion_aware():
    """Single cancellable rAF per node; snaps under hidden/reduced; no setInterval."""
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/motion.js").data.decode()
        assert "requestAnimationFrame" in body
        assert "cancelAnimationFrame" in body
        assert "document.hidden" in body
        assert "prefers-reduced-motion" in body
        assert "matchMedia" in body
        # leak rule: no interval timers introduced by the motion layer
        assert "setInterval" not in body


def test_dashboard_js_wires_kpi_state_class_and_count_up():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        # state→class mapper for KPI cards (Q1)
        assert "function kpiHealthClass" in body
        # count-up + flash applied via the guarded helper
        assert "_motion(" in body or "RuckusMotion" in body
        assert "animateCount" in body
        assert "value-changed" in body
        # refresh pulse fired once per render on the module root
        assert 'pulse(root, "refreshed")' in body or 'RuckusMotion.pulse(root' in body


def test_dashboard_js_motion_is_fail_open():
    """Spec §4.7: a throw in the motion layer must never break renderModule."""
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        assert "function _motion" in body  # try/catch wrapper around RuckusMotion calls
        assert "try {" in body


def test_dashboard_js_health_bar_counts_up():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        # the health-value count-up must be inside applyHealthState
        fn = body.split("function applyHealthState", 1)[1].split("function renderHealthBar", 1)[0]
        assert "animateCount" in fn, "applyHealthState must count up the chip value"


def test_dashboard_js_tile_counts_up_and_pulses():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        # the count-up + pulse must live inside updateTile (the SSE tile updater)
        fn = body.split("const updateTile", 1)[1].split("const finish", 1)[0]
        assert "animateCount" in fn, "updateTile must count up the resolved value"
        assert "pulse(tile" in fn or "m.pulse(tile" in fn, "tile must pulse on resolve"
