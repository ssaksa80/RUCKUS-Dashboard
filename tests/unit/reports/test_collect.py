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
