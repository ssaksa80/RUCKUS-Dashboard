"""Contract test for per-module Column/Filter declarations.

We cannot assert that a Column.key exists in the normalized items without live
data, so instead we assert structural validity: keys are non-empty strings and
kinds fall within the allowed vocabularies.
"""
import ruckus_dashboard.modules._registry  # noqa: F401  side-effect: register stubs
from ruckus_dashboard.modules import all_modules

COLUMN_KINDS = {"text", "status", "bytes", "uptime", "number", "link", "rate"}
FILTER_KINDS = {"select", "search"}


def test_columns_have_valid_keys_and_kinds():
    seen_any = False
    for m in all_modules():
        for col in m.columns:
            seen_any = True
            assert isinstance(col.key, str) and col.key, \
                f"{m.slug}: column key must be non-empty str"
            assert isinstance(col.label, str) and col.label, \
                f"{m.slug}: column label must be non-empty str"
            assert col.kind in COLUMN_KINDS, \
                f"{m.slug}: bad column kind {col.kind!r}"
    assert seen_any, "expected at least one module to declare columns"


def test_filters_have_valid_keys_and_kinds():
    for m in all_modules():
        for flt in m.filters:
            assert isinstance(flt.key, str) and flt.key, \
                f"{m.slug}: filter key must be non-empty str"
            assert isinstance(flt.label, str) and flt.label, \
                f"{m.slug}: filter label must be non-empty str"
            assert flt.kind in FILTER_KINDS, \
                f"{m.slug}: bad filter kind {flt.kind!r}"
