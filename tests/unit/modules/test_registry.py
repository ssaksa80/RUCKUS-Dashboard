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


def test_api_explorer_excluded_from_warmup():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["api-explorer"].warmup is False


def test_all_other_modules_warmup_enabled():
    from ruckus_dashboard.modules import MODULES
    warmup_disabled = {slug for slug, m in MODULES.items() if not m.warmup}
    assert warmup_disabled == {"api-explorer"}


def test_registry_has_18_modules_after_wireless_promoted():
    from ruckus_dashboard.modules import MODULES
    assert len(MODULES) == 18
    from ruckus_dashboard.modules._stub import stub_fetcher
    # 15 modules now have real fetchers (8 wireless + 7 switching)
    real_slugs = ("overview","zones","aps","wlans","clients","alarms","rogues","controller",
                  "switches","switch-groups","ports","traffic","poe","stack","vlans")
    for slug in real_slugs:
        assert MODULES[slug].fetcher is not stub_fetcher, f"{slug} still a stub"
    # 3 cross-cutting remain stubs
    for slug in ("firmware","security","api-explorer"):
        assert MODULES[slug].fetcher is stub_fetcher, f"{slug} should still be stub"
