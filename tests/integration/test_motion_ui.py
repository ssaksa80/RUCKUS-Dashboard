import pathlib

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
