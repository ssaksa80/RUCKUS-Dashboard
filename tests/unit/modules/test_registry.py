from ruckus_dashboard.modules import all_modules
import ruckus_dashboard.modules._registry  # noqa: F401  registers stubs

EXPECTED_SLUGS = {
    "overview", "zones", "aps", "wlans", "clients", "alarms", "rogues", "controller",
    "switches", "switch-groups", "ports", "traffic", "poe", "stack", "vlans",
    "firmware", "security", "api-explorer",
}


def test_all_18_modules_registered():
    slugs = {m.slug for m in all_modules()}
    assert slugs == EXPECTED_SLUGS


def test_modules_grouped_correctly():
    by_group: dict[str, list[str]] = {}
    for m in all_modules():
        by_group.setdefault(m.group, []).append(m.slug)
    assert "overview" in by_group["Wireless"]
    assert "switches" in by_group["Switching"]
    assert "firmware" in by_group["Cross-cutting"]
