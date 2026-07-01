"""Unit tests for the generic report collector (reports/collect.py)."""
from ruckus_dashboard.reports.collect import apply_filter


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
