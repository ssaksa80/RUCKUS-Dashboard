import pytest
from ruckus_dashboard.modules._base import (
    ModuleSpec, TabSpec, FetcherContext, Column, Filter,
)

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


def test_module_spec_warmup_defaults_true():
    spec = ModuleSpec(
        slug="x", title="X", group="Wireless", icon="?",
        poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=noop_summary,
        requires_platforms=("smartzone",), requires_capabilities=(),
        supports_views=("table",),
    )
    assert spec.warmup is True
    assert spec.merge is None


def test_module_spec_warmup_false_when_set():
    spec = ModuleSpec(
        slug="x2", title="X2", group="Wireless", icon="?",
        poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=noop_summary,
        requires_platforms=("smartzone",), requires_capabilities=(),
        supports_views=("table",), warmup=False,
    )
    assert spec.warmup is False


def test_module_spec_merge_function_attaches():
    def my_merge(results): return {"items": []}
    spec = ModuleSpec(
        slug="x3", title="X3", group="Wireless", icon="?",
        poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=noop_summary,
        requires_platforms=("smartzone",), requires_capabilities=(),
        supports_views=("table",), merge=my_merge,
    )
    assert spec.merge is my_merge


def test_module_spec_columns_filters_default_empty():
    spec = ModuleSpec(
        slug="x4", title="X4", group="Wireless", icon="?",
        poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=noop_summary,
        requires_platforms=("smartzone",), requires_capabilities=(),
        supports_views=("table",),
    )
    assert spec.columns == ()
    assert spec.filters == ()


def test_module_spec_accepts_columns_and_filters():
    cols = (Column("Name", "name"), Column("Status", "status", "status"))
    filt = (Filter("zone", "Zone", "select"),)
    spec = ModuleSpec(
        slug="x5", title="X5", group="Wireless", icon="?",
        poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=noop_summary,
        requires_platforms=("smartzone",), requires_capabilities=(),
        supports_views=("table",), columns=cols, filters=filt,
    )
    assert spec.columns == cols
    assert spec.filters == filt
    assert spec.columns[1].kind == "status"
    assert spec.filters[0].kind == "select"


def test_column_defaults_text_kind():
    c = Column("Name", "name")
    assert c.kind == "text"


def test_filter_defaults_select_kind():
    f = Filter("zone", "Zone")
    assert f.kind == "select"
