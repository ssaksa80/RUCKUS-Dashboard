import pathlib

CSS = pathlib.Path("RUCKUS/ruckus_dashboard/static/styles.css")


def _css():
    return CSS.read_text(encoding="utf-8")


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
    css = _css()
    guard = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
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
