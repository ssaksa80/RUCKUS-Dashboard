import pytest
from ruckus_dashboard.modules._base import (
    ModuleSpec, Column, Filter,
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


def test_column_filter_metadata_defaults():
    c = Column("Name", "name")
    assert c.filterable is True
    assert c.filter_kind is None
    assert c.server_filter is None


def test_column_filter_metadata_overrides():
    c = Column("Zone", "zone", "text", filter_kind="select", server_filter="ZONE_ID")
    assert c.filterable is True
    assert c.filter_kind == "select"
    assert c.server_filter == "ZONE_ID"


def test_column_suppressed_when_not_filterable():
    c = Column("Raw", "raw", filterable=False)
    assert c.filterable is False


def test_filter_carries_server_filter_default_none():
    f = Filter("status", "Status", "select")
    assert f.server_filter is None
    f2 = Filter("zone", "Zone", "select", server_filter="ZONE_ID")
    assert f2.server_filter == "ZONE_ID"


from ruckus_dashboard.modules._base import resolve_filters, _infer_filter_kind


def test_infer_filter_kind_by_column_kind():
    assert _infer_filter_kind("status") == "select"
    assert _infer_filter_kind("text") == "search"
    assert _infer_filter_kind("link") == "search"
    assert _infer_filter_kind("number") == "range"
    assert _infer_filter_kind("bytes") == "range"
    assert _infer_filter_kind("rate") == "range"
    assert _infer_filter_kind("uptime") == "range"


def test_resolve_filters_derives_one_per_column():
    cols = (Column("Name", "name"), Column("Status", "status", "status"),
            Column("Clients", "clients", "number"))
    out = resolve_filters(cols, ())
    by_key = {f.key: f for f in out}
    assert by_key["name"].kind == "search"
    assert by_key["status"].kind == "select"
    assert by_key["clients"].kind == "range"
    assert by_key["name"].label == "Name"


def test_resolve_filters_suppresses_non_filterable_and_none():
    cols = (Column("Name", "name"),
            Column("Raw", "raw", filterable=False),
            Column("Blob", "blob", filter_kind="none"))
    keys = {f.key for f in resolve_filters(cols, ())}
    assert keys == {"name"}


def test_resolve_filters_column_override_wins_over_inference():
    cols = (Column("Zone", "zone", "text", filter_kind="select", server_filter="ZONE_ID"),)
    out = resolve_filters(cols, ())
    assert out[0].kind == "select"          # override beats text→search
    assert out[0].server_filter == "ZONE_ID"


def test_resolve_filters_explicit_override_replaces_derived():
    cols = (Column("Status", "status", "status"),)
    overrides = (Filter("status", "Health", "select", server_filter="STATE"),)
    out = resolve_filters(cols, overrides)
    assert len(out) == 1
    assert out[0].label == "Health"          # explicit label wins
    assert out[0].server_filter == "STATE"


def test_resolve_filters_keeps_non_column_explicit_filter():
    cols = (Column("Name", "name"),)
    overrides = (Filter("synthetic", "Synthetic", "select"),)
    out = resolve_filters(cols, overrides)
    keys = [f.key for f in out]
    assert keys == ["name", "synthetic"]     # derived first, then appended


def test_resolve_filters_no_columns_returns_overrides_only():
    overrides = (Filter("severity", "Severity", "select"),)
    out = resolve_filters((), overrides)
    assert [f.key for f in out] == ["severity"]
    assert resolve_filters((), ()) == ()
