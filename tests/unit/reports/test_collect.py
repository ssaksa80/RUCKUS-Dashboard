"""Unit tests for the generic report collector (reports/collect.py)."""
import dataclasses

from ruckus_dashboard.clients.base import RuckusClientError
from ruckus_dashboard.infra.capability_gate import CapabilityGate
from ruckus_dashboard.modules._base import (
    Column, FetcherContext, ModuleSpec, TabSpec,
)
from ruckus_dashboard.reports.collect import apply_filter


def _spec(**over):
    """A minimal valid ModuleSpec; override fields per test."""
    base = dict(
        slug="demo", title="Demo", group="Wireless", icon="x",
        poll_seconds=10, fetcher=lambda ctx: {"items": []},
        drill_fetcher=None, drill_tabs=(), summary_fn=lambda d: {},
        requires_platforms=("smartzone",), requires_capabilities=(),
        supports_views=("table",), columns=(Column("Host", "hostname"),),
        filters=(),
    )
    base.update(over)
    return ModuleSpec(**base)


def _ctx(config=None):
    return FetcherContext(connection=object(), config=config or {},
                          filters=None, capability_gate=CapabilityGate(set()),
                          connection_label="SZ-LAB")


def test_apply_filter_exact_match_per_key():
    rows = [
        {"band": "5 GHz", "quality": "good"},
        {"band": "2.4 GHz", "quality": "poor"},
        {"band": "5 GHz", "quality": "poor"},
    ]
    out = apply_filter(rows, {"band": "5 GHz", "quality": "poor"})
    assert out == [{"band": "5 GHz", "quality": "poor"}]


def test_apply_filter_skips_empty_values():
    rows = [{"band": "5 GHz"}, {"band": "2.4 GHz"}]
    # Empty / None filter values are ignored (no narrowing) — parity with JS.
    assert apply_filter(rows, {"band": ""}) == rows
    assert apply_filter(rows, {"band": None}) == rows  # type: ignore[dict-item]


def test_apply_filter_search_substring_over_all_values():
    rows = [
        {"host": "lab-pc", "ip": "10.0.0.5"},
        {"host": "kiosk", "ip": "10.0.0.9"},
    ]
    # __search matches the substring against the join of all stringified values.
    assert apply_filter(rows, {"__search": "lab"}) == [rows[0]]
    assert apply_filter(rows, {"__search": "10.0.0"}) == rows
    assert apply_filter(rows, {"__search": "LAB"}) == [rows[0]]   # case-insensitive


def test_apply_filter_missing_key_treated_as_empty_string():
    rows = [{"band": "5 GHz"}, {}]
    # A row lacking the key compares as "" — only the explicit value matches.
    assert apply_filter(rows, {"band": "5 GHz"}) == [{"band": "5 GHz"}]


def test_project_columns_keeps_only_declared_keys_and_id():
    from ruckus_dashboard.reports.collect import project_columns
    from ruckus_dashboard.reports.model import ColumnSpec

    cols = [ColumnSpec("Host", "hostname"), ColumnSpec("Band", "band")]
    rows = [{"id": "AA", "hostname": "h1", "band": "5 GHz", "rssi": -60}]
    out = project_columns(rows, cols)
    # id always kept; only declared column keys retained; rssi dropped.
    assert out == [{"id": "AA", "hostname": "h1", "band": "5 GHz"}]
    # key order follows the columns (id first since it is the drill key).
    assert list(out[0].keys()) == ["id", "hostname", "band"]


def test_project_columns_passthrough_when_no_columns():
    from ruckus_dashboard.reports.collect import project_columns
    rows = [{"id": "x", "a": 1, "b": 2}]
    # No columns declared (e.g. topology) → rows pass through unchanged.
    assert project_columns(rows, []) == rows


def test_rows_from_payload_items_with_raw_count_and_raw_rows():
    from ruckus_dashboard.reports.collect import _rows_from_payload
    payload = {"items": [{"id": 1}, {"id": 2}], "raw_count": 99,
               "raw_rows": [{"clientMac": "AA"}]}
    rows, total, raw, note = _rows_from_payload(payload, raw_n=2)
    assert rows == [{"id": 1}, {"id": 2}]
    assert total == 99                       # raw_count wins over len(items)
    assert raw == [{"clientMac": "AA"}]      # raw_rows used verbatim
    assert note is None


def test_rows_from_payload_items_without_raw_rows_samples_items():
    from ruckus_dashboard.reports.collect import _rows_from_payload
    payload = {"items": [{"id": 1}, {"id": 2}, {"id": 3}]}
    rows, total, raw, note = _rows_from_payload(payload, raw_n=2)
    assert total == 3                        # falls back to len(items)
    assert raw == [{"id": 1}, {"id": 2}]     # first raw_n items


def test_rows_from_payload_overview_is_empty_with_note():
    from ruckus_dashboard.reports.collect import _rows_from_payload
    rows, total, raw, note = _rows_from_payload({"items": [], "_overview": True},
                                                raw_n=2)
    assert rows == [] and total == 0 and raw == []
    assert note and "overview" in note.lower()


def test_rows_from_payload_topology_uses_nodes():
    from ruckus_dashboard.reports.collect import _rows_from_payload
    payload = {"nodes": [{"id": "controller"}, {"id": "z1"}],
               "edges": [{"source": "controller", "target": "z1"}],
               "items": []}
    rows, total, raw, note = _rows_from_payload(payload, raw_n=1)
    assert rows == [{"id": "controller"}, {"id": "z1"}]
    assert total == 2
    assert raw == [{"id": "controller"}]     # first raw_n nodes
    assert note and "graph" in note.lower()


def test_collect_module_ok_projects_rows_and_summary():
    from ruckus_dashboard.reports.collect import _collect_module
    spec = _spec(
        fetcher=lambda ctx: {"items": [{"id": "a", "hostname": "h1", "x": 9}],
                             "raw_count": 1, "raw_rows": [{"clientMac": "a"}]},
        summary_fn=lambda d: {"total": len(d.get("items", []))},
    )
    rep = _collect_module(spec, _ctx(), gate=CapabilityGate(set()),
                          filters={}, drill_n=3, raw_n=2)
    assert rep.status == "ok"
    assert rep.summary == {"total": 1}
    assert rep.rows == [{"id": "a", "hostname": "h1"}]   # projected
    assert rep.row_total == 1
    assert rep.raw_samples == [{"clientMac": "a"}]
    assert rep.columns and rep.columns[0].key == "hostname"


def test_collect_module_disabled_when_gate_unsatisfied_and_not_fetched():
    from ruckus_dashboard.reports.collect import _collect_module
    called = {"n": 0}

    def fetcher(ctx):
        called["n"] += 1
        return {"items": []}

    spec = _spec(fetcher=fetcher,
                 requires_capabilities=(("POST", "/query/ap"),))
    rep = _collect_module(spec, _ctx(), gate=CapabilityGate(set()),
                          filters={}, drill_n=3, raw_n=2)
    assert rep.status == "disabled"
    assert called["n"] == 0                  # fetcher never ran
    assert rep.note and "unavailable" in rep.note.lower()


def test_collect_module_error_is_contained():
    from ruckus_dashboard.reports.collect import _collect_module

    def boom(ctx):
        raise RuckusClientError("bad", 502, {"raw": "secret detail"})

    spec = _spec(fetcher=boom)
    rep = _collect_module(spec, _ctx({"RUCKUS_SHOW_DEBUG": False}),
                          gate=CapabilityGate(set()), filters={},
                          drill_n=3, raw_n=2)
    assert rep.status == "error"
    assert rep.errors and rep.errors[0]["status"] == 502
    # Debug off → raw upstream body is NOT exposed in the error message.
    assert "secret detail" not in rep.errors[0]["message"]


def test_collect_module_error_exposes_raw_when_debug_on():
    from ruckus_dashboard.reports.collect import _collect_module

    def boom(ctx):
        raise RuckusClientError("bad", 400, {"raw": "validation: nope"})

    spec = _spec(fetcher=boom)
    rep = _collect_module(spec, _ctx({"RUCKUS_SHOW_DEBUG": True}),
                          gate=CapabilityGate(set()), filters={},
                          drill_n=3, raw_n=2)
    assert "validation: nope" in rep.errors[0]["message"]


def test_collect_module_applies_filters_before_projection():
    from ruckus_dashboard.reports.collect import _collect_module
    spec = _spec(
        fetcher=lambda ctx: {"items": [
            {"id": "a", "hostname": "h1", "band": "5 GHz"},
            {"id": "b", "hostname": "h2", "band": "2.4 GHz"}]},
        columns=(Column("Host", "hostname"), Column("Band", "band")),
    )
    rep = _collect_module(spec, _ctx(), gate=CapabilityGate(set()),
                          filters={"band": "5 GHz"}, drill_n=3, raw_n=2)
    assert rep.rows == [{"id": "a", "hostname": "h1", "band": "5 GHz"}]
    assert rep.row_total == 2                 # pre-filter total preserved
    assert rep.filters_applied == {"band": "5 GHz"}


def test_collect_module_drill_sample_and_error_capture():
    from ruckus_dashboard.reports.collect import _collect_module

    def drill(ctx, entity_id):
        if entity_id == "b":
            raise RuntimeError("drill blew up")
        return {"identity": {"id": entity_id}, "raw": {"k": "v"}}

    spec = _spec(
        fetcher=lambda ctx: {"items": [{"id": "a", "hostname": "h1"},
                                       {"id": "b", "hostname": "h2"}]},
        drill_fetcher=drill,
        drill_tabs=(TabSpec(slug="summary", title="Summary"),),
    )
    rep = _collect_module(spec, _ctx(), gate=CapabilityGate(set()),
                          filters={}, drill_n=2, raw_n=2)
    assert len(rep.drill_samples) == 2
    ok = next(d for d in rep.drill_samples if d.entity_id == "a")
    bad = next(d for d in rep.drill_samples if d.entity_id == "b")
    assert ok.sections["identity"]["id"] == "a" and ok.error is None
    assert bad.error and "drill blew up" in bad.error


def test_collect_report_model_covers_every_registered_module(monkeypatch):
    """SP3 invariant: every slug in all_modules() yields a ModuleReport."""
    import ruckus_dashboard.modules as modmod
    from ruckus_dashboard.reports.collect import collect_report_model

    # Replace every fetcher/drill with a cheap stub so no HTTP happens.
    originals = dict(modmod.MODULES)
    try:
        for slug, spec in list(modmod.MODULES.items()):
            modmod.MODULES[slug] = dataclasses.replace(
                spec,
                fetcher=lambda ctx, s=slug: {"items": [{"id": f"{s}-1"}],
                                             "raw_count": 1},
                drill_fetcher=None,
                requires_capabilities=(),     # all enabled for this test
            )
        model = collect_report_model(
            object(), {}, available_ops=set(), per_module_timeout=5.0)
        got = {m.slug for m in model.modules}
        want = {s.slug for s in modmod.all_modules()}
        assert got == want
        assert all(m.status in ("ok", "disabled", "error") for m in model.modules)
        # Order matches all_modules() (group, title).
        assert [m.slug for m in model.modules] == [s.slug for s in modmod.all_modules()]
    finally:
        modmod.MODULES.clear()
        modmod.MODULES.update(originals)


def test_collect_report_model_disabled_module_not_fetched(monkeypatch):
    import ruckus_dashboard.modules as modmod
    from ruckus_dashboard.reports.collect import collect_report_model
    calls = {"n": 0}

    def fetcher(ctx):
        calls["n"] += 1
        return {"items": []}

    original = modmod.MODULES["aps"]
    modmod.MODULES["aps"] = dataclasses.replace(
        original, fetcher=fetcher, requires_capabilities=(("POST", "/query/ap"),))
    try:
        model = collect_report_model(object(), {}, available_ops=set(),
                                     slugs=("aps",))
        rep = model.by_slug("aps")
        assert rep.status == "disabled"
        assert calls["n"] == 0
    finally:
        modmod.MODULES["aps"] = original


def test_collect_report_model_slow_module_times_out(monkeypatch):
    import time as _t
    import ruckus_dashboard.modules as modmod
    from ruckus_dashboard.reports.collect import collect_report_model

    def slow(ctx):
        _t.sleep(2.0)
        return {"items": []}

    original = modmod.MODULES["aps"]
    modmod.MODULES["aps"] = dataclasses.replace(
        original, fetcher=slow, requires_capabilities=())
    try:
        model = collect_report_model(object(), {}, available_ops=set(),
                                     slugs=("aps",), per_module_timeout=0.2)
        rep = model.by_slug("aps")
        assert rep.status == "error"
        assert rep.note and "timed out" in rep.note.lower()
    finally:
        modmod.MODULES["aps"] = original


def test_collect_report_model_forwards_filters_per_slug():
    import ruckus_dashboard.modules as modmod
    from ruckus_dashboard.reports.collect import collect_report_model

    original = modmod.MODULES["clients"]
    modmod.MODULES["clients"] = dataclasses.replace(
        original,
        fetcher=lambda ctx: {"items": [
            {"id": "a", "band": "5 GHz"}, {"id": "b", "band": "2.4 GHz"}]},
        drill_fetcher=None, requires_capabilities=())
    try:
        model = collect_report_model(
            object(), {}, available_ops=set(), slugs=("clients",),
            filters_by_slug={"clients": {"band": "5 GHz"}})
        rep = model.by_slug("clients")
        assert [r["id"] for r in rep.rows] == ["a"]
        assert rep.filters_applied == {"band": "5 GHz"}
    finally:
        modmod.MODULES["clients"] = original


def test_collect_report_model_metadata_fields():
    from ruckus_dashboard.reports.collect import collect_report_model

    class Conn:
        display_name = "SZ-PROD"

    model = collect_report_model(Conn(), {}, available_ops=set(),
                                 slugs=())
    assert model.connection_label == "SZ-PROD"
    assert model.generated_at        # ISO-ish timestamp string
    assert model.modules == []


def test_collect_report_data_legacy_shape(monkeypatch):
    import ruckus_dashboard.modules as modmod
    from ruckus_dashboard.reports.collect import collect_report_data

    originals = dict(modmod.MODULES)
    try:
        for slug in ("aps", "clients", "alarms", "switches"):
            modmod.MODULES[slug] = dataclasses.replace(
                modmod.MODULES[slug],
                fetcher=lambda ctx, s=slug: {"items": [{"id": f"{s}-1",
                                                        "status": "online"}],
                                             "raw_count": 1},
                drill_fetcher=None, requires_capabilities=())
        data = collect_report_data(object(), {})
        assert set(data.keys()) == {"aps", "clients", "alarms", "switches"}
        assert data["aps"] == [{"id": "aps-1", "status": "online"}]
        assert data["switches"][0]["id"] == "switches-1"
    finally:
        modmod.MODULES.clear()
        modmod.MODULES.update(originals)
