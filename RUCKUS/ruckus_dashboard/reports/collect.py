"""Generic, registry-driven report collection.

Walks ``all_modules()``, runs each fetcher under the live capability gate with
a per-module timeout, adapts the payload shape to rows, applies the operator's
filters generically (mirroring ``dashboard.js:_applyFilters``), projects to the
module's declared columns, and harvests summary KPIs, a raw field-map sample,
and a small drill sample. Produces a pure ``ReportModel`` (reports/model.py).

A thin ``collect_report_data`` wrapper preserves the legacy 4-domain dict the
alert path consumes (``state_from_data``)."""
from __future__ import annotations

import logging
from typing import Any

from .model import ColumnSpec

LOG = logging.getLogger("ruckus.reports")


def _matches_range(row: dict, col: str, val: Any) -> bool:
    """Range predicate: {min, max} over Number(row[col]) — mirrors JS range:."""
    lo = val.get("min")
    hi = val.get("max")
    lo = None if lo in ("", None) else _to_number(lo)
    hi = None if hi in ("", None) else _to_number(hi)
    if lo is None and hi is None:
        return True
    n = _to_number(row.get(col))
    if n is None:
        return False
    if lo is not None and n < lo:
        return False
    if hi is not None and n > hi:
        return False
    return True


def _to_number(value: Any):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def apply_filter(rows: list[dict], filters: dict) -> list[dict]:
    """Filter ``rows`` by ``filters``, mirroring ``dashboard.js:_applyFilters``.

    Parity with the SP1 client-side predicate (``static/dashboard.js``):
    - empty/None values (and empty lists) are ignored;
    - ``__search`` matches a case-insensitive substring over all stringified
      values of a row;
    - ``search:<col>`` matches a case-insensitive substring over one column;
    - ``range:<col>`` matches ``{min, max}`` against ``Number(row[col])``;
    - a list value is a multi-select: the row passes if ``row[key]`` is one of
      the selected values;
    - every other key requires an exact string match against ``row[key]``
      ("" when the key is absent).
    """
    active = {
        k: v for k, v in (filters or {}).items()
        if v not in ("", None) and not (isinstance(v, list) and len(v) == 0)
    }
    if not active:
        return list(rows)
    out: list[dict] = []
    for row in rows:
        keep = True
        for key, val in active.items():
            if key == "__search":
                hay = " ".join(str(v if v is not None else "")
                               for v in row.values()).lower()
                if str(val).lower() not in hay:
                    keep = False
                    break
            elif isinstance(key, str) and key.startswith("search:"):
                col = key[7:]
                cell = str(row.get(col, "") if row.get(col) is not None else "")
                if str(val).lower() not in cell.lower():
                    keep = False
                    break
            elif isinstance(key, str) and key.startswith("range:"):
                if isinstance(val, dict) and not _matches_range(row, key[6:], val):
                    keep = False
                    break
            elif isinstance(val, list):
                cell = str(row.get(key, "") if row.get(key) is not None else "")
                if cell not in [str(v) for v in val]:
                    keep = False
                    break
            elif str(row.get(key, "") if row.get(key) is not None else "") != str(val):
                keep = False
                break
        if keep:
            out.append(row)
    return out


def project_columns(rows: list[dict],
                    columns: list[ColumnSpec]) -> list[dict]:
    """Keep only ``columns`` keys (label order), always passing through ``id``.

    With no columns the rows pass through unchanged (e.g. graph modules that
    declare none)."""
    if not columns:
        return list(rows)
    keys: list[str] = ["id"] + [c.key for c in columns if c.key != "id"]
    out: list[dict] = []
    for row in rows:
        projected: dict[str, Any] = {}
        for k in keys:
            if k == "id" and "id" not in row:
                continue
            if k in row:
                projected[k] = row[k]
        out.append(projected)
    return out
