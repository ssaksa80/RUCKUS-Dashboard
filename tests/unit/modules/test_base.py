import pytest
from ruckus_dashboard.modules._base import ModuleSpec, TabSpec, FetcherContext

def noop_fetcher(ctx): return {"items": []}
def noop_summary(data): return {"count": 0}

def test_module_spec_minimal_valid():
    spec = ModuleSpec(
        slug="aps", title="Access Points", group="Wireless",
        icon="📶", poll_seconds=30,
        fetcher=noop_fetcher, drill_fetcher=None, drill_tabs=(),
        summary_fn=noop_summary,
        requires_platforms=("smartzone",),
        requires_capabilities=(("POST", "/query/ap"),),
        supports_views=("table",),
    )
    assert spec.slug == "aps"
    assert spec.poll_seconds == 30

def test_module_spec_rejects_invalid_group():
    with pytest.raises(ValueError):
        ModuleSpec(
            slug="x", title="X", group="UnknownGroup", icon="?",
            poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
            drill_tabs=(), summary_fn=noop_summary,
            requires_platforms=("smartzone",), requires_capabilities=(),
            supports_views=("table",),
        )

def test_module_spec_rejects_invalid_view():
    with pytest.raises(ValueError):
        ModuleSpec(
            slug="x", title="X", group="Wireless", icon="?",
            poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
            drill_tabs=(), summary_fn=noop_summary,
            requires_platforms=("smartzone",), requires_capabilities=(),
            supports_views=("invalid-view",),
        )

def test_module_spec_slug_kebab_case_only():
    with pytest.raises(ValueError):
        ModuleSpec(
            slug="Switch Groups", title="X", group="Switching", icon="?",
            poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
            drill_tabs=(), summary_fn=noop_summary,
            requires_platforms=("smartzone",), requires_capabilities=(),
            supports_views=("table",),
        )
