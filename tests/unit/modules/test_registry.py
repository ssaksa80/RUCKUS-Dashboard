from ruckus_dashboard.modules import all_modules
import ruckus_dashboard.modules._registry  # noqa: F401  registers stubs

EXPECTED_SLUGS = {
    "overview", "zones", "aps", "wlans", "clients", "alarms", "rogues", "controller",
    "switches", "switch-groups", "ports", "traffic", "poe", "stack", "vlans",
    "firmware", "security", "api-explorer", "topology",
}


def test_all_modules_registered():
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


def test_registry_has_all_modules_with_real_fetchers():
    from ruckus_dashboard.modules import MODULES
    assert len(MODULES) == 19
    from ruckus_dashboard.modules._stub import stub_fetcher
    # All modules have real fetchers (wireless + switching + cross-cutting + topology)
    real_slugs = ("overview","zones","aps","wlans","clients","alarms","rogues","controller",
                  "switches","switch-groups","ports","traffic","poe","stack","vlans",
                  "firmware","security","api-explorer","topology")
    for slug in real_slugs:
        assert MODULES[slug].fetcher is not stub_fetcher, f"{slug} still a stub"
    remaining_stubs = {slug for slug, m in MODULES.items() if m.fetcher is stub_fetcher}
    assert remaining_stubs == set()
