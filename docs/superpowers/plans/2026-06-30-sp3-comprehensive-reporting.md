# SP3+8 — Full-Coverage Reporting + Per-Tab Email Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Excel report cover all 19 registered modules generically (list + summary + drill samples + raw field maps) and add a per-tab "Email this tab" button/endpoint that honors the operator's live filters.

**Architecture:** Introduce a pure data layer — `reports/model.py` (typed `ReportModel`/`ModuleReport` dataclasses) + `reports/collect.py` (`collect_report_model` enumerating `all_modules()` under a real capability gate, with a shape adapter, generic filter predicate, column projection, drill sampling, and per-module timeouts). `reports/excel.py` renders one sheet per module from the model; `routes/notifications.py` adds `POST /api/reports/tab` (+ optional preview); `static/dashboard.js` adds the button. A thin `collect_report_data` wrapper keeps the alert path byte-for-byte unchanged.

**Tech Stack:** Python 3.10+, Flask, openpyxl (Excel), `concurrent.futures` (bounded pool + per-future timeout), pytest + `responses` (HTTP mocking) for tests, ruff for lint.

---

## File Structure

| File | Responsibility | Tasks |
|------|----------------|-------|
| `RUCKUS/ruckus_dashboard/reports/model.py` | **New.** Pure dataclasses: `ColumnSpec`, `DrillSample`, `ModuleReport`, `ReportModel` (+ `by_slug`). No openpyxl / no Flask. | 1 |
| `RUCKUS/ruckus_dashboard/reports/collect.py` | **New.** `apply_filter`, `project_columns`, `_rows_from_payload`, `_collect_module`, `collect_report_model`, and the legacy `collect_report_data` wrapper. | 2, 3, 4, 5, 6, 7 |
| `RUCKUS/ruckus_dashboard/notify/scheduler.py` | Re-point `collect_report_data` import to `reports.collect`; daily report builds the full 19-module model. `state_from_data` unchanged. | 7, 11 |
| `RUCKUS/ruckus_dashboard/reports/excel.py` | `build_report` accepts a `ReportModel` (or legacy dict); add Coverage block + generic per-module sheets + `_safe_sheet_name`; keep curated chart sheets. | 8, 9 |
| `RUCKUS/ruckus_dashboard/routes/notifications.py` | New `POST /api/reports/tab` (+ `POST /api/reports/tab/preview`); switch `/api/reports/test` & `/api/reports/generate` to the 19-module model. | 10, 11 |
| `RUCKUS/ruckus_dashboard/templates/base.html` | Add `<meta name="csrf-token">` so module pages expose the token to JS (mirrors notifications.html/topology.html). | 12 |
| `RUCKUS/ruckus_dashboard/templates/module.html` | Add the "Email this tab" button into the module toolbar. | 12 |
| `RUCKUS/ruckus_dashboard/static/dashboard.js` | `wireEmailTab()` — reads `activeFilters[slug]`, POSTs to `/api/reports/tab` with `X-CSRF-Token`, toast feedback. | 13 |
| `tests/unit/reports/__init__.py` | **New.** Package marker for the new unit-test dir. | 2 |
| `tests/unit/reports/test_collect.py` | **New.** Unit tests for `apply_filter`, `project_columns`, `_rows_from_payload`, `collect_report_model`, `collect_report_data`. | 2-7 |
| `tests/unit/reports/test_excel.py` | **New.** Renderer tests: model → xlsx loads in openpyxl; per-module sheets; coverage; legacy dict; charts; debug gating. | 8, 9 |
| `tests/integration/test_notifications_api.py` | Extend: `POST /api/reports/tab` auth/CSRF/404/200/filter-respect; 19-module collector on test/generate. | 10, 11 |
| `tests/integration/test_dashboard_js.py` | Extend: static-assert the "Email this tab" handler + CSRF + activeFilters. | 13 |

**Module count note:** the spec says "18 modules"; the live registry registers **19** (`all_modules()` includes `api-explorer`). All coverage tests assert over `all_modules()` (no magic number) so the guarantee is registry-driven, not count-driven. Existing `tests/integration/test_routes_new_ui.py::test_module_list_endpoint` already pins `len(slugs) == 19` — do not change it.

**Pre-flight (run once before Task 1, do not commit):**
```
cd "<repo>" && python -m pytest -q 2>&1 | tail -3      # expect 302 passed
cd "<repo>" && python -m ruff check RUCKUS/ruckus_dashboard tests   # expect All checks passed!
```
All `pytest`/`ruff` commands below run from the repo root: `C:\Users\sshoaib\OneDrive - Mohamed & Obaid Almulla LLC\Documents\RUCKUS-Dashboard`.

---

## Task 1 — `reports/model.py`: typed report model

**Files**
- Create: `RUCKUS/ruckus_dashboard/reports/model.py`
- Test: covered by `tests/unit/reports/test_collect.py` (Task 2 creates the dir + first test that imports these dataclasses).

This task has no standalone test (pure dataclasses with no logic beyond `by_slug`); its `by_slug` is exercised in Task 6. Write it first so later tasks import real types.

- [ ] Create `RUCKUS/ruckus_dashboard/reports/model.py` with the complete content:

```python
"""Pure, serializable report model — no openpyxl, no Flask.

``collect_report_model`` (reports/collect.py) produces a ``ReportModel``;
``reports/excel.py`` and the per-tab route render from it. Keeping the model
free of I/O lets both the collector and the renderers be unit-tested without
SMTP or a workbook."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ColumnSpec:
    """Decoupled mirror of ``modules._base.Column`` (label + key + kind)."""
    label: str
    key: str
    kind: str = "text"


@dataclass
class DrillSample:
    """One entity's drill payload (``drill_fetcher`` output), or an error."""
    entity_id: str
    sections: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ModuleReport:
    slug: str
    title: str
    group: str
    status: str                              # "ok" | "disabled" | "error"
    columns: list[ColumnSpec] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)   # projected, post-filter
    row_total: int = 0                       # pre-filter raw count
    raw_samples: list[dict] = field(default_factory=list)      # upstream field map
    drill_samples: list[DrillSample] = field(default_factory=list)
    filters_applied: dict[str, str] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)           # str-safe controller errors
    note: str | None = None


@dataclass
class ReportModel:
    generated_at: str
    connection_label: str
    modules: list[ModuleReport] = field(default_factory=list)

    def by_slug(self, slug: str) -> ModuleReport | None:
        return next((m for m in self.modules if m.slug == slug), None)
```

- [ ] Verify it imports cleanly:
```
cd "<repo>" && python -c "import sys; sys.path.insert(0,'RUCKUS'); from ruckus_dashboard.reports.model import ReportModel, ModuleReport, ColumnSpec, DrillSample; print('ok')"
```
Expected: prints `ok`.

- [ ] Commit:
```
git add RUCKUS/ruckus_dashboard/reports/model.py
git commit -m "feat(reports): pure ReportModel/ModuleReport dataclasses"
```

---

## Task 2 — `apply_filter`: generic predicate mirroring `dashboard.js:_applyFilters`

**Files**
- Create: `RUCKUS/ruckus_dashboard/reports/collect.py`
- Create: `tests/unit/reports/__init__.py`
- Create: `tests/unit/reports/test_collect.py`

Mirror the JS predicate exactly (`static/dashboard.js:179-193`): per key exact string match; empty/None values skipped; `__search` is a substring match over all stringified values, case-insensitive.

- [ ] Create `tests/unit/reports/__init__.py` (empty file):
```
cd "<repo>" && python -c "open('tests/unit/reports/__init__.py','w').close()"
```

- [ ] Create `tests/unit/reports/test_collect.py` with the failing test:

```python
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
```

- [ ] Run it — expect failure (module/function does not exist yet):
```
cd "<repo>" && python -m pytest tests/unit/reports/test_collect.py -q
```
Expected FAIL: `ModuleNotFoundError: No module named 'ruckus_dashboard.reports.collect'`.

- [ ] Create `RUCKUS/ruckus_dashboard/reports/collect.py` with the module docstring, imports, and `apply_filter`:

```python
"""Generic, registry-driven report collection.

Walks ``all_modules()``, runs each fetcher under the live capability gate with
a per-module timeout, adapts the payload shape to rows, applies the operator's
filters generically (mirroring ``dashboard.js:_applyFilters``), projects to the
module's declared columns, and harvests summary KPIs, a raw field-map sample,
and a small drill sample. Produces a pure ``ReportModel`` (reports/model.py).

A thin ``collect_report_data`` wrapper preserves the legacy 4-domain dict the
alert path consumes (``state_from_data``)."""
from __future__ import annotations

import concurrent.futures
import logging
import time
from typing import Any, Iterable

from .model import ColumnSpec, DrillSample, ModuleReport, ReportModel

LOG = logging.getLogger("ruckus.reports")


def apply_filter(rows: list[dict], filters: dict[str, str]) -> list[dict]:
    """Filter ``rows`` by ``filters``, mirroring ``dashboard.js:_applyFilters``.

    - empty/None filter values are ignored;
    - ``__search`` matches a case-insensitive substring over all stringified
      values of a row;
    - every other key requires an exact string match against ``row[key]``
      ("" when the key is absent).
    """
    active = {k: v for k, v in (filters or {}).items() if v not in ("", None)}
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
            elif str(row.get(key, "") if row.get(key) is not None else "") != str(val):
                keep = False
                break
        if keep:
            out.append(row)
    return out
```

- [ ] Run the test — expect PASS:
```
cd "<repo>" && python -m pytest tests/unit/reports/test_collect.py -q
```
Expected: 4 passed.

- [ ] Commit:
```
git add RUCKUS/ruckus_dashboard/reports/collect.py tests/unit/reports/__init__.py tests/unit/reports/test_collect.py
git commit -m "feat(reports): generic apply_filter predicate mirroring dashboard.js"
```

---

## Task 3 — `project_columns`: keep only declared column keys (+ `id`)

**Files**
- Modify: `RUCKUS/ruckus_dashboard/reports/collect.py`
- Test: `tests/unit/reports/test_collect.py`

Keep only `spec.columns` keys, preserving label order; always pass through `id` (the drill key) even when no column declares it.

- [ ] Add the failing test to `tests/unit/reports/test_collect.py`:

```python
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
```

- [ ] Run — expect FAIL (`project_columns` undefined):
```
cd "<repo>" && python -m pytest tests/unit/reports/test_collect.py::test_project_columns_keeps_only_declared_keys_and_id -q
```
Expected FAIL: `ImportError: cannot import name 'project_columns'`.

- [ ] Append `project_columns` to `RUCKUS/ruckus_dashboard/reports/collect.py`:

```python
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
```

- [ ] Run both new tests — expect PASS:
```
cd "<repo>" && python -m pytest tests/unit/reports/test_collect.py -q
```
Expected: 6 passed.

- [ ] Commit:
```
git add RUCKUS/ruckus_dashboard/reports/collect.py tests/unit/reports/test_collect.py
git commit -m "feat(reports): project_columns keeps declared keys plus id"
```

---

## Task 4 — `_rows_from_payload`: shape adapter for items / `_overview` / topology

**Files**
- Modify: `RUCKUS/ruckus_dashboard/reports/collect.py`
- Test: `tests/unit/reports/test_collect.py`

Adapt the four real payload shapes (spec §5.3 table). Returns `(rows, row_total, raw_samples, note)`. Keyed off `nodes`/`_overview` first, then `items`.

- [ ] Add the failing tests:

```python
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
```

- [ ] Run — expect FAIL (`_rows_from_payload` undefined):
```
cd "<repo>" && python -m pytest tests/unit/reports/test_collect.py -k rows_from_payload -q
```
Expected FAIL: `ImportError: cannot import name '_rows_from_payload'`.

- [ ] Append `_rows_from_payload` to `collect.py`:

```python
def _rows_from_payload(payload: dict,
                       *, raw_n: int) -> tuple[list[dict], int, list[dict], str | None]:
    """Adapt a fetcher payload to ``(rows, row_total, raw_samples, note)``.

    Handles the real variants:
      * topology graph ``{"nodes":[...], "edges":[...], "items":[]}`` -> node rows
      * overview ``{"items":[], "_overview":True}`` -> empty + note
      * ``{"items":[...], "raw_count":N, "raw_rows":[...]}`` -> items
      * ``{"items":[...]}`` -> items, total = len(items)
    """
    payload = payload or {}
    if payload.get("nodes") is not None and "items" in payload:
        nodes = list(payload.get("nodes") or [])
        return nodes, len(nodes), nodes[:raw_n], "graph module — node list"
    if payload.get("_overview"):
        return [], 0, [], "overview tiles (warmup-driven), no list"
    items = list(payload.get("items") or [])
    raw_count = payload.get("raw_count")
    total = int(raw_count) if raw_count is not None else len(items)
    raw_rows = payload.get("raw_rows")
    raw = list(raw_rows) if raw_rows else items[:raw_n]
    return items, total, raw, None
```

- [ ] Run — expect PASS:
```
cd "<repo>" && python -m pytest tests/unit/reports/test_collect.py -k rows_from_payload -q
```
Expected: 4 passed.

- [ ] Commit:
```
git add RUCKUS/ruckus_dashboard/reports/collect.py tests/unit/reports/test_collect.py
git commit -m "feat(reports): _rows_from_payload shape adapter (items/overview/topology)"
```

---

## Task 5 — `_collect_module`: per-module harvest (status, summary, rows, raw, drill)

**Files**
- Modify: `RUCKUS/ruckus_dashboard/reports/collect.py`
- Test: `tests/unit/reports/test_collect.py`

`_collect_module(spec, ctx, *, gate, filters, drill_n, raw_n)` returns a `ModuleReport`. Order of operations: capability gate → run fetcher (wrapped) → adapt shape → `summary_fn(payload)` → filter rows → project columns → drill sample on first `drill_n` filtered rows that have an `id`. Errors never raise; they become `ModuleReport.errors` / `DrillSample.error`. Honors `RUCKUS_SHOW_DEBUG` for error-string exposure via `ctx.config`, mirroring `routes/modules.py:_upstream_message`.

- [ ] Add the failing tests (use lightweight fakes — no HTTP):

```python
import dataclasses

from ruckus_dashboard.modules._base import (
    Column, FetcherContext, ModuleSpec, TabSpec,
)
from ruckus_dashboard.infra.capability_gate import CapabilityGate
from ruckus_dashboard.clients.base import RuckusClientError


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
```

- [ ] Run — expect FAIL (`_collect_module` undefined):
```
cd "<repo>" && python -m pytest tests/unit/reports/test_collect.py -k collect_module -q
```
Expected FAIL: `ImportError: cannot import name '_collect_module'`.

- [ ] Append `_collect_module` and a private error-formatting helper to `collect.py`:

```python
def _error_message(exc: Exception, config: dict) -> str:
    """Error text for the report. Appends the controller's raw body only when
    ``RUCKUS_SHOW_DEBUG`` is set — mirror of routes/modules.py:_upstream_message,
    so the report never leaks upstream bodies by default."""
    from ..clients.base import RuckusClientError
    message = str(getattr(exc, "message", None) or exc)
    if (config or {}).get("RUCKUS_SHOW_DEBUG") and isinstance(exc, RuckusClientError):
        debug = exc.debug if isinstance(exc.debug, dict) else {}
        raw = debug.get("raw")
        if raw:
            message = f"{message} :: {raw}"
    return message


def _error_dict(exc: Exception, label: str, slug: str, config: dict) -> dict:
    from ..clients.base import RuckusClientError
    status = exc.status_code if isinstance(exc, RuckusClientError) else 502
    return {"connection": label, "endpoint": slug,
            "message": _error_message(exc, config), "status": status}


def _collect_module(spec, ctx, *, gate, filters: dict[str, str],
                    drill_n: int, raw_n: int) -> ModuleReport:
    """Harvest one module into a ``ModuleReport``. Never raises."""
    columns = [ColumnSpec(c.label, c.key, c.kind) for c in spec.columns]
    rep = ModuleReport(slug=spec.slug, title=spec.title, group=spec.group,
                       status="ok", columns=columns,
                       filters_applied=dict(filters or {}))

    if not gate.satisfied(spec.requires_capabilities):
        rep.status = "disabled"
        rep.note = "module unavailable on this controller"
        return rep

    try:
        payload = spec.fetcher(ctx) or {}
    except Exception as exc:  # noqa: BLE001 — one module never aborts the report
        LOG.warning("report: %s fetch failed", spec.slug)
        rep.status = "error"
        rep.errors.append(_error_dict(exc, ctx.connection_label, spec.slug,
                                      ctx.config))
        return rep

    all_rows, total, raw_samples, note = _rows_from_payload(payload, raw_n=raw_n)
    try:
        rep.summary = spec.summary_fn(payload) or {}
    except Exception:  # noqa: BLE001
        rep.summary = {}
    rep.row_total = total
    rep.raw_samples = raw_samples
    if note:
        rep.note = note

    filtered = apply_filter(all_rows, filters or {})
    rep.rows = project_columns(filtered, columns)

    if spec.drill_fetcher is not None and drill_n > 0:
        for row in filtered:
            if len(rep.drill_samples) >= drill_n:
                break
            ident = row.get("id")
            if ident in (None, ""):
                continue
            try:
                sections = spec.drill_fetcher(ctx, str(ident)) or {}
                rep.drill_samples.append(
                    DrillSample(entity_id=str(ident), sections=sections))
            except Exception as exc:  # noqa: BLE001
                rep.drill_samples.append(
                    DrillSample(entity_id=str(ident),
                                error=_error_message(exc, ctx.config)))
    return rep
```

- [ ] Run — expect PASS:
```
cd "<repo>" && python -m pytest tests/unit/reports/test_collect.py -k collect_module -q
```
Expected: 6 passed.

- [ ] Commit:
```
git add RUCKUS/ruckus_dashboard/reports/collect.py tests/unit/reports/test_collect.py
git commit -m "feat(reports): _collect_module harvests summary/rows/raw/drill with gating"
```

---

## Task 6 — `collect_report_model`: enumerate `all_modules()` with bounded concurrency + timeout

**Files**
- Modify: `RUCKUS/ruckus_dashboard/reports/collect.py`
- Test: `tests/unit/reports/test_collect.py`

`collect_report_model(connection, config, *, available_ops, slugs=None, filters_by_slug=None, drill_sample_size=3, raw_sample_size=2, per_module_timeout=20.0, max_workers=4) -> ReportModel`. Builds a real `CapabilityGate(available_ops)`, builds a `FetcherContext` per module (its filters from `filters_by_slug`), runs `_collect_module` for each slug via a `ThreadPoolExecutor` using `future.result(timeout=...)` per future (so a slow module bounds its own slot — not `ParallelFetcher`, per spec §5.3). On timeout → `ModuleReport(status="error", note="timed out")`. Output module order follows `all_modules()` order.

- [ ] Add the failing tests (monkeypatch the registry via `dataclasses.replace`, like the integration tests do):

```python
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
```

- [ ] Run — expect FAIL (`collect_report_model` undefined):
```
cd "<repo>" && python -m pytest tests/unit/reports/test_collect.py -k collect_report_model -q
```
Expected FAIL: `ImportError: cannot import name 'collect_report_model'`.

- [ ] Append `collect_report_model` to `collect.py`:

```python
def collect_report_model(
    connection, config: dict, *,
    available_ops: set[tuple[str, str]],
    slugs: Iterable[str] | None = None,
    filters_by_slug: dict[str, dict[str, str]] | None = None,
    drill_sample_size: int = 3,
    raw_sample_size: int = 2,
    per_module_timeout: float = 20.0,
    max_workers: int = 4,
) -> ReportModel:
    """Collect a ``ReportModel`` over the registry (or a slug subset).

    ``slugs=None`` => every module in ``all_modules()`` order. Each module runs
    under a real ``CapabilityGate(available_ops)`` with a per-module timeout
    enforced via ``future.result(timeout=...)`` (a slow module bounds its own
    slot)."""
    from ..modules import all_modules
    from ..modules._base import FetcherContext
    from ..infra.capability_gate import CapabilityGate

    gate = CapabilityGate(available=set(available_ops or set()))
    filters_by_slug = filters_by_slug or {}
    ordered = all_modules()
    if slugs is not None:
        wanted = set(slugs)
        ordered = [s for s in ordered if s.slug in wanted]

    label = getattr(connection, "display_name", "") or ""
    model = ReportModel(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        connection_label=label, modules=[])

    def _run(spec) -> ModuleReport:
        ctx = FetcherContext(connection=connection, config=config,
                             filters=filters_by_slug.get(spec.slug),
                             capability_gate=gate, connection_label=label)
        return _collect_module(spec, ctx, gate=gate,
                               filters=filters_by_slug.get(spec.slug) or {},
                               drill_n=drill_sample_size, raw_n=raw_sample_size)

    if not ordered:
        return model

    results: dict[str, ModuleReport] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_spec = {pool.submit(_run, spec): spec for spec in ordered}
        for future, spec in future_to_spec.items():
            try:
                results[spec.slug] = future.result(timeout=per_module_timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                results[spec.slug] = ModuleReport(
                    slug=spec.slug, title=spec.title, group=spec.group,
                    status="error", note="timed out",
                    columns=[ColumnSpec(c.label, c.key, c.kind)
                             for c in spec.columns])
            except Exception as exc:  # noqa: BLE001 — defensive
                LOG.warning("report: %s crashed", spec.slug)
                results[spec.slug] = ModuleReport(
                    slug=spec.slug, title=spec.title, group=spec.group,
                    status="error",
                    errors=[{"connection": label, "endpoint": spec.slug,
                             "message": str(exc), "status": 502}])

    model.modules = [results[spec.slug] for spec in ordered]
    return model
```

- [ ] Run — expect PASS (the slow-timeout test takes ~0.2s):
```
cd "<repo>" && python -m pytest tests/unit/reports/test_collect.py -k collect_report_model -q
```
Expected: 5 passed.

- [ ] Commit:
```
git add RUCKUS/ruckus_dashboard/reports/collect.py tests/unit/reports/test_collect.py
git commit -m "feat(reports): collect_report_model enumerates registry with timeouts"
```

---

## Task 7 — `collect_report_data` legacy wrapper (alert path unchanged)

**Files**
- Modify: `RUCKUS/ruckus_dashboard/reports/collect.py`
- Modify: `RUCKUS/ruckus_dashboard/notify/scheduler.py`
- Test: `tests/unit/reports/test_collect.py`, `tests/unit/notify/test_notify.py` (existing — must stay green)

Add `collect_report_data(connection, config)` to `reports/collect.py` returning the legacy `{"aps":[...], "clients":[...], "alarms":[...], "switches":[...]}` dict by pulling those four slugs' `rows` out of `collect_report_model(slugs=core4)`. Then re-point `notify/scheduler.py` to import it from `reports.collect` (keeping a re-export so `from ..notify.scheduler import collect_report_data` still works for `routes/notifications.py`).

- [ ] Add the failing test for the wrapper:

```python
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
```

- [ ] Run — expect FAIL (`collect_report_data` undefined in `reports.collect`):
```
cd "<repo>" && python -m pytest tests/unit/reports/test_collect.py::test_collect_report_data_legacy_shape -q
```
Expected FAIL: `ImportError: cannot import name 'collect_report_data'`.

- [ ] Append `collect_report_data` to `collect.py`. It must project **all** keys (not just declared columns) so `state_from_data` keeps reading `status`/`severity`/`count`/`quality`/`ap`. Use raw rows, not column-projected rows:

```python
_LEGACY_SLUGS = ("aps", "clients", "alarms", "switches")


def collect_report_data(connection, config: dict) -> dict[str, Any]:
    """Backward-compatible shim for the alert path.

    Returns the legacy ``{"aps":[...], "clients":[...], "alarms":[...],
    "switches":[...]}`` dict (full normalized rows, not column-projected) so
    ``notify.scheduler.state_from_data`` is untouched. Implemented over
    ``collect_report_model`` so alerts and reports share one collector."""
    from ..modules import MODULES
    from ..modules._base import FetcherContext
    from ..infra.capability_gate import CapabilityGate

    gate = CapabilityGate(available=set())
    out: dict[str, Any] = {}
    for slug in _LEGACY_SLUGS:
        spec = MODULES.get(slug)
        if spec is None:
            out[slug] = []
            continue
        ctx = FetcherContext(connection=connection, config=config, filters=None,
                             capability_gate=gate,
                             connection_label=getattr(connection,
                                                      "display_name", ""))
        try:
            payload = spec.fetcher(ctx) or {}
            out[slug] = list(payload.get("items") or [])
        except Exception:  # noqa: BLE001
            LOG.exception("report(legacy): %s fetch failed", slug)
            out[slug] = []
    return out
```

> **DRY note:** the legacy shim deliberately runs the four fetchers directly (empty gate, full rows) rather than going through `collect_report_model`, because the alert path needs *all* normalized keys and the empty-gate behavior of the prior `notify/scheduler.collect_report_data` — this keeps alerts byte-for-byte identical. `collect_report_model` (column-projected, gated) is the report path.

- [ ] In `RUCKUS/ruckus_dashboard/notify/scheduler.py`, delete the old `collect_report_data` function (lines 22-39) and replace it with a re-export from `reports.collect`. First read the current top-of-file imports, then apply:

  - Remove the function body `def collect_report_data(...)` through its `return out`.
  - Add, just below the existing `from .rules import evaluate` import block (top of module), a re-export so existing importers keep working:

```python
from ..reports.collect import collect_report_data  # re-export (alert path)
```

  Concretely, replace this block:

```python
def collect_report_data(connection, config: dict) -> dict[str, Any]:
    """Run the relevant module fetchers (dump-style) for the report/alerts."""
    from ..modules import MODULES
    from ..modules._base import FetcherContext
    from ..infra.capability_gate import CapabilityGate

    ctx = FetcherContext(connection=connection, config=config, filters=None,
                         capability_gate=CapabilityGate(set()),
                         connection_label=getattr(connection, "display_name", ""))
    out: dict[str, Any] = {}
    for slug, key in (("aps", "aps"), ("clients", "clients"),
                      ("alarms", "alarms"), ("switches", "switches")):
        try:
            out[key] = (MODULES[slug].fetcher(ctx) or {}).get("items", [])
        except Exception:  # noqa: BLE001
            LOG.exception("notify: %s fetch failed", slug)
            out[key] = []
    return out
```

  with:

```python
from ..reports.collect import collect_report_data  # noqa: F401  re-export
```

  (Keep `state_from_data`, `poor_quality_aps`, and `NotifyScheduler` exactly as-is. The `from typing import Any` import is still used by `state_from_data`'s signature, so leave it.)

- [ ] Run the new wrapper test, the existing notify suite, and the scheduler/alert tests together — all must pass (proves the alert path is unchanged):
```
cd "<repo>" && python -m pytest tests/unit/reports/test_collect.py tests/unit/notify/test_notify.py -q
```
Expected: all passed (existing `test_state_from_data_counts`, `test_alerts_due_*`, `test_report_due_*` still green; new wrapper test green).

- [ ] Run ruff on the touched files:
```
cd "<repo>" && python -m ruff check RUCKUS/ruckus_dashboard/reports RUCKUS/ruckus_dashboard/notify/scheduler.py
```
Expected: All checks passed!

- [ ] Commit:
```
git add RUCKUS/ruckus_dashboard/reports/collect.py RUCKUS/ruckus_dashboard/notify/scheduler.py tests/unit/reports/test_collect.py
git commit -m "refactor(reports): collect_report_data wrapper over model; scheduler re-exports"
```

---

## Task 8 — `excel.py`: accept a `ReportModel` (legacy dict still works) + Coverage sheet

**Files**
- Modify: `RUCKUS/ruckus_dashboard/reports/excel.py`
- Create: `tests/unit/reports/test_excel.py`

`build_report` gains a model-aware path while preserving the legacy dict path. Add `_safe_sheet_name(title, used)` and a `_wrap_legacy(data)` that turns the legacy `{aps,clients,...}` dict into a minimal `ReportModel` so the curated sheets keep working. This task adds the dispatch + Coverage sheet; Task 9 adds the generic per-module sheets.

- [ ] Create `tests/unit/reports/test_excel.py` with failing tests:

```python
"""Renderer tests: build_report over a ReportModel and the legacy dict."""
import io

import openpyxl

from ruckus_dashboard.reports.excel import build_report, _safe_sheet_name
from ruckus_dashboard.reports.model import (
    ColumnSpec, DrillSample, ModuleReport, ReportModel,
)


def _model():
    return ReportModel(
        generated_at="2026-06-30T07:00:00Z", connection_label="SZ-LAB",
        modules=[
            ModuleReport(
                slug="aps", title="Access Points", group="Wireless", status="ok",
                columns=[ColumnSpec("Name", "name"),
                         ColumnSpec("Status", "status", "status")],
                summary={"total": 2, "online": 1, "offline": 1},
                rows=[{"id": "a", "name": "AP1", "status": "online"},
                      {"id": "b", "name": "AP2", "status": "offline"}],
                row_total=2,
                raw_samples=[{"apMac": "a", "deviceName": "AP1"}],
                drill_samples=[DrillSample("a", {"identity": {"name": "AP1"}})],
            ),
            ModuleReport(slug="topology", title="Topology", group="Cross-cutting",
                         status="disabled", note="module unavailable"),
        ],
    )


def test_safe_sheet_name_truncates_and_dedupes():
    used: set[str] = set()
    a = _safe_sheet_name("A very long module title that exceeds excel limit", used)
    assert len(a) <= 31 and a not in ("",)
    used.add(a)
    b = _safe_sheet_name("A very long module title that exceeds excel limit", used)
    assert b != a and len(b) <= 31           # deduped suffix


def test_safe_sheet_name_strips_illegal_chars():
    used: set[str] = set()
    name = _safe_sheet_name("APs: by/zone [x]?", used)
    for bad in ":/\\?*[]":
        assert bad not in name


def test_build_report_from_model_loads_with_overview_and_coverage():
    blob = build_report(_model())
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    assert "Overview" in wb.sheetnames
    assert "Coverage" in wb.sheetnames
    # Coverage lists every module + its status.
    cov_text = "\n".join(str(c.value) for row in wb["Coverage"].iter_rows()
                         for c in row if c.value is not None)
    assert "Access Points" in cov_text and "Topology" in cov_text
    assert "disabled" in cov_text


def test_build_report_legacy_dict_still_renders_curated_sheets():
    data = {
        "aps": [{"name": "AP1", "zone": "HQ", "status": "online", "mac": "a"},
                {"name": "AP2", "zone": "HQ", "status": "offline", "mac": "b"}],
        "clients": [{"hostname": "h1", "mac": "m", "ssid": "S", "ap": "AP1",
                     "band": "5 GHz", "quality": "good",
                     "rx_bytes": 10, "tx_bytes": 20}],
        "alarms": [{"severity": "critical", "category": "AP", "source": "AP2",
                    "message": "down", "count": 1}],
        "switches": [{"name": "SW1", "ip": "10.0.0.1", "model": "ICX",
                      "fw": "x", "status": "online", "ports_online": 10,
                      "ports_total": 24, "group": "Core", "mac": "c"}],
    }
    wb = openpyxl.load_workbook(io.BytesIO(build_report(data)))
    # Curated sheets preserved; charts intact (regression for current suite).
    assert {"Overview", "APs by Zone", "Clients", "Alarms",
            "Switches", "Offline Devices"} <= set(wb.sheetnames)
    assert len(wb["APs by Zone"]._charts) == 1
    assert len(wb["Clients"]._charts) == 1
    assert len(wb["Alarms"]._charts) == 1
```

- [ ] Run — expect FAIL (`_safe_sheet_name` undefined; model path missing):
```
cd "<repo>" && python -m pytest tests/unit/reports/test_excel.py -q
```
Expected FAIL: `ImportError: cannot import name '_safe_sheet_name'`.

- [ ] Edit `RUCKUS/ruckus_dashboard/reports/excel.py`. Add imports and helpers near the top (after the existing `_HEAD`/`_HEAD_FILL` constants and `_autofit`), and refactor `build_report` to dispatch. Replace the current `def build_report(data: dict[str, Any]) -> bytes:` signature line and the body up to (but not including) the `wb = Workbook()` line so the curated logic moves into a private `_build_curated(wb, data)`; then add the new dispatcher. Use this exact structure:

  Add after `_autofit`:

```python
import re

from .model import ReportModel, ModuleReport

_ILLEGAL_SHEET = re.compile(r"[:\\/?*\[\]]")


def _safe_sheet_name(title: str, used: set[str]) -> str:
    """Excel sheet names: <=31 chars, none of :\\/?*[]; unique within a book."""
    base = _ILLEGAL_SHEET.sub(" ", str(title or "Sheet")).strip()[:31] or "Sheet"
    name = base
    n = 2
    while name in used:
        suffix = f" ({n})"
        name = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(name)
    return name


def _wrap_legacy(data: dict[str, Any]) -> ReportModel:
    """Adapt the legacy {aps,clients,alarms,switches} dict to a minimal model
    so the model-driven Overview/Coverage render alongside the curated sheets."""
    mods: list[ModuleReport] = []
    titles = {"aps": ("Access Points", "Wireless"),
              "clients": ("Clients", "Wireless"),
              "alarms": ("Alarms", "Wireless"),
              "switches": ("Switches", "Switching")}
    for slug, (title, group) in titles.items():
        rows = list(data.get(slug) or [])
        mods.append(ModuleReport(slug=slug, title=title, group=group,
                                 status="ok", rows=rows, row_total=len(rows)))
    return ReportModel(generated_at=time.strftime("%Y-%m-%dT%H:%M UTC",
                                                  time.gmtime()),
                       connection_label="", modules=mods)
```

  Now change the entry point. Rename the existing function to `_build_curated` and add the new dispatcher. Replace this line:

```python
def build_report(data: dict[str, Any]) -> bytes:
    aps = data.get("aps") or []
```

  with:

```python
def build_report(data_or_model) -> bytes:
    """Render xlsx bytes from a ReportModel (new) or the legacy
    {aps,clients,...} dict (curated sheets + model-driven Overview/Coverage)."""
    if isinstance(data_or_model, ReportModel):
        model = data_or_model
        legacy = _legacy_from_model(model)
    else:
        legacy = data_or_model or {}
        model = _wrap_legacy(legacy)
    wb = Workbook()
    _build_curated(wb, legacy)
    _build_coverage(wb, model)
    _build_module_sheets(wb, model)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _legacy_from_model(model: ReportModel) -> dict[str, Any]:
    """Pull the four curated domains' rows out of a model for the chart sheets."""
    out: dict[str, Any] = {}
    for slug in ("aps", "clients", "alarms", "switches"):
        rep = model.by_slug(slug)
        out[slug] = list(rep.rows) if rep else []
    return out


def _build_curated(wb: Workbook, data: dict[str, Any]) -> None:
    aps = data.get("aps") or []
```

  Then, in the (now) `_build_curated` body, **delete** the line `wb = Workbook()` and the line `ws = wb.active` immediately followed by `ws.title = "Overview"` — replace those two lines:

```python
    wb = Workbook()

    # ── Overview ──────────────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Overview"
```

  with:

```python
    # ── Overview ──────────────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Overview"
```

  (i.e. remove only the `wb = Workbook()` line — `wb` is now a parameter). Finally, **delete** the trailing 3 lines of the old function:

```python
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

  (they moved into `build_report`). Add the `_build_coverage` helper (the `_build_module_sheets` is added in Task 9 — define a temporary no-op stub now so the module imports; Task 9 replaces it):

```python
def _build_coverage(wb: Workbook, model: ReportModel) -> None:
    ws = wb.create_sheet("Coverage")
    ws["A1"] = "Module coverage"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Generated {model.generated_at}"
    _header(ws, 4, ["Module", "Group", "Status", "Rows", "Errors", "Note"])
    for i, m in enumerate(model.modules, start=5):
        ws.cell(row=i, column=1, value=m.title)
        ws.cell(row=i, column=2, value=m.group)
        ws.cell(row=i, column=3, value=m.status)
        ws.cell(row=i, column=4, value=m.row_total)
        ws.cell(row=i, column=5, value=len(m.errors))
        ws.cell(row=i, column=6, value=m.note or "")
    _autofit(ws, [26, 14, 10, 8, 8, 40])


def _build_module_sheets(wb: Workbook, model: ReportModel) -> None:
    # Replaced in Task 9 with the generic per-module sheets.
    return
```

- [ ] Run — expect PASS:
```
cd "<repo>" && python -m pytest tests/unit/reports/test_excel.py -q
```
Expected: 4 passed.

- [ ] Run the existing notify excel test (must stay green — curated sheets/charts unchanged):
```
cd "<repo>" && python -m pytest "tests/unit/notify/test_notify.py::test_build_report_loads_and_has_sheets_and_charts" -q
```
Expected: 1 passed. **Note:** the existing test asserts `set(wb.sheetnames) == {...6 names...}`. Adding `Coverage` breaks that equality. Update that one assertion now.

- [ ] In `tests/unit/notify/test_notify.py`, change the strict set-equality to a subset check so the new Coverage/module sheets don't break it. Replace:

```python
    assert set(wb.sheetnames) == {"Overview", "APs by Zone", "Clients",
                                  "Alarms", "Switches", "Offline Devices"}
```

  with:

```python
    assert {"Overview", "APs by Zone", "Clients", "Alarms", "Switches",
            "Offline Devices"} <= set(wb.sheetnames)
```

- [ ] Re-run the existing test — expect PASS:
```
cd "<repo>" && python -m pytest "tests/unit/notify/test_notify.py::test_build_report_loads_and_has_sheets_and_charts" -q
```
Expected: 1 passed.

- [ ] Commit:
```
git add RUCKUS/ruckus_dashboard/reports/excel.py tests/unit/reports/test_excel.py tests/unit/notify/test_notify.py
git commit -m "feat(reports): build_report accepts ReportModel; add Coverage sheet"
```

---

## Task 9 — `excel.py`: generic per-module sheets (summary + list + raw + drill)

**Files**
- Modify: `RUCKUS/ruckus_dashboard/reports/excel.py`
- Test: `tests/unit/reports/test_excel.py`

Replace the `_build_module_sheets` stub with one sheet per module: title + status + filters line; Summary key/value; List table (header from `columns[*].label`, projected rows, capped at 1000 with a "+N more" note per Open-Q #2); Raw field-map blocks; Drill-sample blocks.

- [ ] Add failing tests:

```python
def test_module_sheet_has_summary_list_raw_and_drill():
    blob = build_report(_model())
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    # The aps module gets its own sheet (safe name == title, fits in 31 chars).
    assert "Access Points" in wb.sheetnames
    ws = wb["Access Points"]
    text = "\n".join(str(c.value) for row in ws.iter_rows()
                     for c in row if c.value is not None)
    assert "Summary" in text and "online" in text      # summary block
    assert "AP1" in text and "AP2" in text              # list rows
    assert "apMac" in text                              # raw field-map key
    assert "Drill" in text                              # drill block label


def test_disabled_module_sheet_notes_status():
    wb = openpyxl.load_workbook(io.BytesIO(build_report(_model())))
    assert "Topology" in wb.sheetnames
    ws = wb["Topology"]
    text = "\n".join(str(c.value) for row in ws.iter_rows()
                     for c in row if c.value is not None)
    assert "disabled" in text


def test_list_rows_capped_with_more_note():
    big = ReportModel(
        generated_at="t", connection_label="x",
        modules=[ModuleReport(
            slug="clients", title="Clients", group="Wireless", status="ok",
            columns=[ColumnSpec("Host", "hostname")],
            rows=[{"id": str(i), "hostname": f"h{i}"} for i in range(1500)],
            row_total=1500)])
    wb = openpyxl.load_workbook(io.BytesIO(build_report(big)))
    ws = wb["Clients"]
    text = "\n".join(str(c.value) for row in ws.iter_rows()
                     for c in row if c.value is not None)
    assert "more" in text.lower()                       # "+N more" note present
```

- [ ] Run — expect FAIL (stub produces no per-module sheet):
```
cd "<repo>" && python -m pytest tests/unit/reports/test_excel.py -k "module_sheet or disabled_module or rows_capped" -q
```
Expected FAIL: `KeyError: 'Worksheet Access Points does not exist.'` (or the `"Summary" in text` assertion fails).

- [ ] Replace the `_build_module_sheets` stub in `excel.py` with the full implementation and helpers:

```python
_LIST_ROW_CAP = 1000


def _fmt_value(value, kind: str):
    """Light, render-only formatting matching the dashboard idioms."""
    if value is None:
        return ""
    if kind == "bytes":
        try:
            return _human_bytes_xl(int(value))
        except (TypeError, ValueError):
            return value
    return value


def _human_bytes_xl(n: int) -> str:
    v = float(n or 0)
    if v <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if v < 1024:
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} EB"


def _kv_block(ws, row: int, title: str, mapping: dict) -> int:
    """Write a 'title' header then key/value rows. Returns the next free row."""
    ws.cell(row=row, column=1, value=title).font = Font(bold=True)
    row += 1
    for k, v in (mapping or {}).items():
        ws.cell(row=row, column=1, value=str(k))
        ws.cell(row=row, column=2, value=v if not isinstance(v, (dict, list))
                else str(v))
        row += 1
    return row + 1


def _build_module_sheets(wb: Workbook, model: ReportModel) -> None:
    used = {ws_title for ws_title in wb.sheetnames}
    for m in model.modules:
        ws = wb.create_sheet(_safe_sheet_name(m.title, used))
        ws["A1"] = m.title
        ws["A1"].font = Font(bold=True, size=14)
        ws["A2"] = f"Status: {m.status}"
        if m.note:
            ws["A3"] = m.note
        if m.filters_applied:
            applied = ", ".join(f"{k}={v}" for k, v in m.filters_applied.items()
                                if v)
            ws["B2"] = f"Filters: {applied}" if applied else "Filters: none"
        row = 5
        row = _kv_block(ws, row, "Summary", m.summary)

        # List table.
        ws.cell(row=row, column=1, value="List").font = Font(bold=True)
        row += 1
        if m.columns and m.rows:
            labels = [c.label for c in m.columns]
            _header(ws, row, labels)
            row += 1
            shown = m.rows[:_LIST_ROW_CAP]
            for r in shown:
                for col, c in enumerate(m.columns, start=1):
                    ws.cell(row=row, column=col,
                            value=_fmt_value(r.get(c.key), c.kind))
                row += 1
            extra = len(m.rows) - len(shown)
            if extra > 0:
                ws.cell(row=row, column=1, value=f"+{extra} more rows (capped)")
                row += 1
        else:
            ws.cell(row=row, column=1,
                    value="(no list)" if not m.rows else "(no columns declared)")
            row += 1
        row += 1

        # Raw field-map samples.
        if m.raw_samples:
            ws.cell(row=row, column=1, value="Raw field map").font = Font(bold=True)
            row += 1
            for i, sample in enumerate(m.raw_samples, start=1):
                row = _kv_block(ws, row, f"Sample {i}", sample)

        # Drill samples.
        if m.drill_samples:
            ws.cell(row=row, column=1, value="Drill samples").font = Font(bold=True)
            row += 1
            for d in m.drill_samples:
                if d.error:
                    ws.cell(row=row, column=1,
                            value=f"{d.entity_id}: error — {d.error}")
                    row += 2
                    continue
                for section, payload in (d.sections or {}).items():
                    flat = payload if isinstance(payload, dict) else {"value": payload}
                    row = _kv_block(ws, row, f"{d.entity_id} · {section}", flat)
        _autofit(ws, [28, 32])
```

- [ ] Run — expect PASS:
```
cd "<repo>" && python -m pytest tests/unit/reports/test_excel.py -q
```
Expected: 7 passed.

- [ ] Run ruff on excel.py:
```
cd "<repo>" && python -m ruff check RUCKUS/ruckus_dashboard/reports/excel.py
```
Expected: All checks passed!

- [ ] Commit:
```
git add RUCKUS/ruckus_dashboard/reports/excel.py tests/unit/reports/test_excel.py
git commit -m "feat(reports): generic per-module sheets (summary/list/raw/drill)"
```

---

## Task 10 — `POST /api/reports/tab`: per-tab email endpoint

**Files**
- Modify: `RUCKUS/ruckus_dashboard/routes/notifications.py`
- Test: `tests/integration/test_notifications_api.py`

New endpoint emailing one module's sheet, honoring posted `filters`. Flow per spec §5.6: auth → `validate_csrf()` → resolve connection → validate `slug` against `MODULES` (404 unknown) → validate `filters` is flat `dict[str,str]`, drop keys not in `spec.filters` (+ allow `__search`) → `collect_report_model(slugs=(slug,), filters_by_slug={slug: filters})` → `build_report(model)` → `send_email(... attachment=xlsx)`. Disabled module → 422.

- [ ] Add failing integration tests (append to `tests/integration/test_notifications_api.py`). They reuse the file's existing `_app`/`_login` helpers and the `_authed` pattern with a stored connection:

```python
def _authed_with_conn(tmp_path):
    """App + one stored SmartZone connection; returns (app, csrf)."""
    from ruckus_dashboard.auth.session_store import ConnectionConfig
    app = _app(tmp_path)
    conn = ConnectionConfig(platform="smartzone", api_base="https://sz/wsg/api/public",
                            display_name="SZ-LAB", auth_token="t",
                            api_version="v11_0", verify_tls=False,
                            token_expires_at=9999999999)
    cid = app.connection_store.put(conn)
    app.available_ops = {("POST", "/query/client"), ("POST", "/query/ap")}
    with app.test_client() as c:
        c.get("/")
        with c.session_transaction() as s:
            s["auth"] = True
            s["connection_ids"] = [cid]
            csrf = s["csrf_token"]
        yield c, csrf


def test_reports_tab_requires_auth(tmp_path):
    app = _app(tmp_path)
    with app.test_client() as c:
        assert c.post("/api/reports/tab", json={"slug": "clients"}).status_code == 401


def test_reports_tab_requires_csrf(tmp_path):
    for c, _csrf in [next(_authed_with_conn(tmp_path))]:
        r = c.post("/api/reports/tab", json={"slug": "clients"})
        assert r.status_code == 400          # missing X-CSRF-Token


def test_reports_tab_unknown_slug_404(tmp_path):
    for c, csrf in [next(_authed_with_conn(tmp_path))]:
        r = c.post("/api/reports/tab", json={"slug": "nope"},
                   headers={"X-CSRF-Token": csrf})
        assert r.status_code == 404


def test_reports_tab_happy_path_emails_one_module(tmp_path, monkeypatch):
    import ruckus_dashboard.routes.notifications as notif_routes
    import ruckus_dashboard.reports.collect as collect_mod
    calls = {}

    def fake_send(cfg, pw, recipients, subject, body, **kw):
        calls["recipients"] = recipients
        calls["subject"] = subject
        calls["filename"] = kw.get("filename")
        calls["has_attachment"] = kw.get("attachment") is not None

    captured = {}
    real_collect = collect_mod.collect_report_model

    def spy_collect(*a, **kw):
        captured["slugs"] = kw.get("slugs")
        captured["filters_by_slug"] = kw.get("filters_by_slug")
        return real_collect(*a, **kw)

    monkeypatch.setattr(notif_routes, "send_email", fake_send)
    monkeypatch.setattr(notif_routes, "collect_report_model", spy_collect)

    gen = _authed_with_conn(tmp_path)
    c, csrf = next(gen)
    # Configure report recipients.
    c.post("/api/notifications/config",
           json={"smtp": {"host": "mail.x"}, "report": {"recipients": ["noc@x"]}},
           headers={"X-CSRF-Token": csrf})
    # Stub the clients fetcher so no HTTP happens.
    import ruckus_dashboard.modules as modmod
    import dataclasses
    original = modmod.MODULES["clients"]
    modmod.MODULES["clients"] = dataclasses.replace(
        original,
        fetcher=lambda ctx: {"items": [{"id": "a", "band": "5 GHz"},
                                       {"id": "b", "band": "2.4 GHz"}]},
        drill_fetcher=None)
    try:
        r = c.post("/api/reports/tab",
                   json={"slug": "clients", "filters": {"band": "5 GHz"}},
                   headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        assert body["sent"] is True
        assert body["slug"] == "clients"
        assert calls["recipients"] == ["noc@x"]
        assert "clients" in calls["filename"]
        assert calls["has_attachment"] is True
        # Filters forwarded into the collector for that slug only.
        assert captured["slugs"] == ("clients",)
        assert captured["filters_by_slug"] == {"clients": {"band": "5 GHz"}}
    finally:
        modmod.MODULES["clients"] = original


def test_reports_tab_disabled_module_returns_422(tmp_path):
    gen = _authed_with_conn(tmp_path)
    c, csrf = next(gen)
    # 'rogues' requires ("POST","/query/roguesInfoList"), not in available_ops.
    r = c.post("/api/reports/tab", json={"slug": "rogues"},
               headers={"X-CSRF-Token": csrf})
    assert r.status_code == 422
    assert r.get_json()["sent"] is False
```

- [ ] Run — expect FAIL (route 404, no `collect_report_model` imported in routes):
```
cd "<repo>" && python -m pytest tests/integration/test_notifications_api.py -k reports_tab -q
```
Expected FAIL: assorted 404s / `AttributeError: ... has no attribute 'collect_report_model'`.

- [ ] Edit `RUCKUS/ruckus_dashboard/routes/notifications.py`. Add imports at the top (after the existing `from ..modules import all_modules`):

```python
from ..modules import MODULES, all_modules
from ..reports.collect import collect_report_model
from ..reports.excel import build_report
from ..infra.capability_gate import CapabilityGate
```

  (Replace the existing `from ..modules import all_modules` line with the `MODULES, all_modules` form; add the other three lines.)

  Then append the new endpoint at the end of the file:

```python
def _valid_filters(spec, raw) -> dict[str, str]:
    """Keep only flat string filters whose key the module declares (or __search)."""
    if not isinstance(raw, dict):
        return {}
    allowed = {f.key for f in spec.filters} | {"__search"}
    return {str(k): str(v) for k, v in raw.items()
            if k in allowed and isinstance(v, (str, int, float)) and str(v) != ""}


@bp.post("/api/reports/tab")
def email_report_tab():
    """E-mail the current tab (one module's sheet), honoring active filters."""
    if not session.get("auth"):
        return _unauth()
    validate_csrf()
    payload = request.get_json(silent=True) or {}
    slug = str(payload.get("slug") or "")
    spec = MODULES.get(slug)
    if spec is None:
        return jsonify({"error": f"unknown module: {slug}"}), 404

    conn = None
    for cid in session.get("connection_ids", []):
        conn = current_app.connection_store.get(cid)
        if conn is not None:
            break
    if conn is None:
        return jsonify({"error": "Connection expired.", "reauth": True}), 401

    gate = CapabilityGate(available=getattr(current_app, "available_ops", set()))
    if not gate.satisfied(spec.requires_capabilities):
        return jsonify({"sent": False,
                        "error": "module unavailable on this controller"}), 422

    filters = _valid_filters(spec, payload.get("filters"))
    cfg = load_config(current_app.instance_path)
    recipients = payload.get("recipients")
    if not (isinstance(recipients, list) and
            [r for r in recipients if isinstance(r, str) and r.strip()]):
        recipients = cfg["report"]["recipients"]
    if not [r for r in (recipients or []) if r and str(r).strip()]:
        return jsonify({"sent": False, "error": "No recipients configured."}), 400

    try:
        model = collect_report_model(
            conn, dict(current_app.config),
            available_ops=getattr(current_app, "available_ops", set()),
            slugs=(slug,), filters_by_slug={slug: filters})
        xlsx = build_report(model)
        ts = time.strftime("%Y%m%d-%H%M", time.gmtime())
        send_email(cfg, smtp_password(cfg, current_app.secrets_manager),
                   recipients,
                   f"[RUCKUS DSO] {spec.title} report {ts}",
                   f"Attached: {spec.title} tab report"
                   + (" (filtered)." if filters else "."),
                   attachment=xlsx,
                   filename=f"ruckus-{slug}-{ts}.xlsx")
        rep = model.by_slug(slug)
        return jsonify({"sent": True, "recipients": recipients, "slug": slug,
                        "rows": len(rep.rows) if rep else 0,
                        "filtered": bool(filters)})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"sent": False, "error": str(exc)}), 502
```

- [ ] Run the new tests — expect PASS:
```
cd "<repo>" && python -m pytest tests/integration/test_notifications_api.py -k reports_tab -q
```
Expected: 6 passed.

- [ ] Commit:
```
git add RUCKUS/ruckus_dashboard/routes/notifications.py tests/integration/test_notifications_api.py
git commit -m "feat(reports): POST /api/reports/tab emails one module honoring filters"
```

---

## Task 11 — Route + scheduler full-coverage reports (`/api/reports/test`, `/generate`, daily)

**Files**
- Modify: `RUCKUS/ruckus_dashboard/routes/notifications.py`
- Modify: `RUCKUS/ruckus_dashboard/notify/scheduler.py`
- Test: `tests/integration/test_notifications_api.py`

Switch the manual report routes and the daily scheduler report to the 19-module model so they no longer share the 4-module blind spot, and prove topology/overview shapes don't crash.

- [ ] Add a failing integration test asserting the full report covers all modules and survives topology/overview shapes:

```python
def test_reports_generate_covers_all_modules_no_crash(tmp_path, monkeypatch):
    """/api/reports/generate runs the 19-module collector; topology/overview
    shapes must not crash the workbook (regression for the 4-module blind spot)."""
    import io
    import openpyxl
    import ruckus_dashboard.modules as modmod
    import dataclasses

    gen = _authed_with_conn(tmp_path)
    c, _csrf = next(gen)
    # Make every module enabled + cheap; keep topology/overview real shapes.
    originals = dict(modmod.MODULES)
    try:
        for slug, spec in list(modmod.MODULES.items()):
            if slug in ("topology", "overview"):
                modmod.MODULES[slug] = dataclasses.replace(
                    spec, requires_capabilities=())
                continue
            modmod.MODULES[slug] = dataclasses.replace(
                spec,
                fetcher=lambda ctx, s=slug: {"items": [{"id": f"{s}-1"}],
                                             "raw_count": 1},
                drill_fetcher=None, requires_capabilities=())
        # topology fetcher returns its graph shape; stub to avoid HTTP.
        modmod.MODULES["topology"] = dataclasses.replace(
            modmod.MODULES["topology"],
            fetcher=lambda ctx: {"nodes": [{"id": "controller"}], "edges": [],
                                 "items": []})
        r = c.get("/api/reports/generate")
        assert r.status_code == 200
        wb = openpyxl.load_workbook(io.BytesIO(r.data))
        assert "Coverage" in wb.sheetnames
        # Every module title shows up on the Coverage sheet.
        cov = "\n".join(str(cell.value) for row in wb["Coverage"].iter_rows()
                        for cell in row if cell.value is not None)
        for spec in modmod.all_modules():
            assert spec.title in cov, f"{spec.slug} missing from coverage"
    finally:
        modmod.MODULES.clear()
        modmod.MODULES.update(originals)
```

- [ ] Run — expect FAIL (generate still uses the legacy 4-domain dict; no Coverage sheet):
```
cd "<repo>" && python -m pytest tests/integration/test_notifications_api.py::test_reports_generate_covers_all_modules_no_crash -q
```
Expected FAIL: `KeyError: 'Worksheet Coverage does not exist'` (legacy dict path renders curated sheets only — actually `_wrap_legacy` now adds Coverage, but only 4 modules appear, so the `for spec in all_modules()` assertion fails on the 5th title).

- [ ] In `routes/notifications.py`, update `email_report_now` (the `/api/reports/test` handler) and `generate_report` to build the model. Replace, inside `email_report_now`, this block:

```python
        from ..notify.scheduler import collect_report_data
        from ..reports.excel import build_report
        data = collect_report_data(conn, dict(current_app.config))
        xlsx = build_report(data)
```

  with:

```python
        model = collect_report_model(
            conn, dict(current_app.config),
            available_ops=getattr(current_app, "available_ops", set()))
        xlsx = build_report(model)
```

  And in `generate_report`, replace:

```python
    from ..notify.scheduler import collect_report_data
    from ..reports.excel import build_report
    data = collect_report_data(conn, dict(current_app.config))
    xlsx = build_report(data)
```

  with:

```python
    model = collect_report_model(
        conn, dict(current_app.config),
        available_ops=getattr(current_app, "available_ops", set()))
    xlsx = build_report(model)
```

  (`collect_report_model` and `build_report` are already imported at module top from Task 10; the local `from ..reports.excel import build_report` lines are removed.)

- [ ] In `notify/scheduler.py`, update the daily-report block in `_tick` (currently lines ~158-173) to build the full model. Replace:

```python
            try:
                from ..reports.excel import build_report
                data = collect_report_data(connection, self._app_config)
                xlsx = build_report(data)
```

  with:

```python
            try:
                from ..reports.excel import build_report
                from ..reports.collect import collect_report_model
                model = collect_report_model(
                    connection, self._app_config,
                    available_ops=set(getattr(self, "_available_ops", set())))
                xlsx = build_report(model)
```

  **Note on `_available_ops`:** the scheduler has no `available_ops` today. Add a setter so the connect flow can hand them over without coupling. In `NotifyScheduler.__init__`, after `self._connection = None`, add:

```python
        self._available_ops: set = set()
```

  and add a method next to `set_connection`:

```python
    def set_available_ops(self, ops) -> None:
        with self._lock:
            self._available_ops = set(ops or set())
```

  The daily report uses `getattr(self, "_available_ops", set())` so it is safe even if `set_available_ops` is never wired. (Wiring it in `routes/connect.py` is optional and out of scope; the per-tab and manual routes already pass `current_app.available_ops` directly. A daily report with an empty gate marks capability-requiring modules `disabled` — acceptable, and noted in Open-Q #3.)

- [ ] Run the new test plus the existing notifications API tests — expect PASS:
```
cd "<repo>" && python -m pytest tests/integration/test_notifications_api.py -q
```
Expected: all passed (existing `test_notifications_api_requires_auth`, `test_test_email_route_uses_mailer`, etc., still green).

- [ ] Run the scheduler/notify unit tests to confirm no regression:
```
cd "<repo>" && python -m pytest tests/unit/notify/test_notify.py -q
```
Expected: all passed.

- [ ] Commit:
```
git add RUCKUS/ruckus_dashboard/routes/notifications.py RUCKUS/ruckus_dashboard/notify/scheduler.py tests/integration/test_notifications_api.py
git commit -m "feat(reports): manual + daily reports cover all 19 modules via model"
```

---

## Task 12 — Templates: expose CSRF token + add "Email this tab" button

**Files**
- Modify: `RUCKUS/ruckus_dashboard/templates/base.html`
- Modify: `RUCKUS/ruckus_dashboard/templates/module.html`
- Test: `tests/integration/test_pages.py` (extend) — assert the button + meta render

`base.html` currently has no `<meta name="csrf-token">`; module pages need it so `dashboard.js` can read the token the same way `notifications.js` does (`meta[name="csrf-token"]`). Add the meta to `base.html` `<head>` and the button to `module.html`.

- [ ] Add a failing page test (append to `tests/integration/test_pages.py`). First check the file's existing app/login helpers; it likely builds `create_app({...})` and logs in via `session_transaction`. Use the same pattern already present in that file. Add:

```python
def test_module_page_has_email_tab_button_and_csrf_meta(tmp_path):
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        c.get("/")
        with c.session_transaction() as s:
            s["auth"] = True
            s["connection_ids"] = []
        r = c.get("/m/clients")
        assert r.status_code == 200
        body = r.data.decode()
        assert '<meta name="csrf-token"' in body
        assert "data-email-tab" in body
        assert "Email this tab" in body
```

- [ ] Run — expect FAIL (neither marker present):
```
cd "<repo>" && python -m pytest tests/integration/test_pages.py::test_module_page_has_email_tab_button_and_csrf_meta -q
```
Expected FAIL: `assert '<meta name="csrf-token"' in body`.

- [ ] In `RUCKUS/ruckus_dashboard/templates/base.html`, add the meta tag inside `<head>`. Replace:

```html
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="{{ url_for('static', filename='styles.css') }}">
```

  with:

```html
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf-token" content="{{ csrf_token }}">
<link rel="stylesheet" href="{{ url_for('static', filename='styles.css') }}">
```

  (`csrf_token` is already passed into every render context that uses `base.html`; `module_page`, `drill_page`, `index` all pass it. For renders that don't — e.g. `legacy.html` extends nothing — the variable is simply empty, which is harmless.)

- [ ] In `RUCKUS/ruckus_dashboard/templates/module.html`, add the button into the toolbar. Replace:

```html
  <div class="view-toggle" data-views="{{ module.supports_views|join(',') }}">
    {% for v in module.supports_views %}
    <button data-view="{{ v }}" class="{% if loop.first %}active{% endif %}">{{ v }}</button>
    {% endfor %}
  </div>
```

  with:

```html
  <div class="module-toolbar">
    <div class="view-toggle" data-views="{{ module.supports_views|join(',') }}">
      {% for v in module.supports_views %}
      <button data-view="{{ v }}" class="{% if loop.first %}active{% endif %}">{{ v }}</button>
      {% endfor %}
    </div>
    <button class="button secondary" data-email-tab title="E-mail this tab with current filters">
      ✉ Email this tab
    </button>
  </div>
```

- [ ] Run — expect PASS:
```
cd "<repo>" && python -m pytest tests/integration/test_pages.py::test_module_page_has_email_tab_button_and_csrf_meta -q
```
Expected: 1 passed.

- [ ] Run the full pages + notifications page tests to ensure the new meta tag didn't break existing assertions (notifications.html has its own meta — make sure base.html's doesn't double up for pages that extend base):
```
cd "<repo>" && python -m pytest tests/integration/test_pages.py tests/integration/test_notifications_api.py::test_notifications_page_renders -q
```
Expected: all passed.

- [ ] Commit:
```
git add RUCKUS/ruckus_dashboard/templates/base.html RUCKUS/ruckus_dashboard/templates/module.html tests/integration/test_pages.py
git commit -m "feat(reports): expose CSRF meta + Email this tab button in module toolbar"
```

---

## Task 13 — `dashboard.js`: wire the "Email this tab" button

**Files**
- Modify: `RUCKUS/ruckus_dashboard/static/dashboard.js`
- Test: `tests/integration/test_dashboard_js.py` (extend — static-assert style)

Add `wireEmailTab(root, slug)` posting `activeFilters[slug]` (empty values skipped, same rule as `_applyFilters`) to `/api/reports/tab` with `X-CSRF-Token`, plus a `_dashCsrf()` reader and a small toast. Call it from `renderModule` after `wireViewToggle`.

- [ ] Add failing static-assert tests (append to `tests/integration/test_dashboard_js.py`):

```python
def test_dashboard_js_has_email_tab_handler():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        for sym in ["wireEmailTab", "/api/reports/tab", "X-CSRF-Token",
                    "data-email-tab", "activeFilters"]:
            assert sym in body, f"missing JS symbol: {sym}"


def test_dashboard_js_email_tab_reads_csrf_meta():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        assert 'meta[name="csrf-token"]' in body
```

- [ ] Run — expect FAIL:
```
cd "<repo>" && python -m pytest tests/integration/test_dashboard_js.py -k email_tab -q
```
Expected FAIL: `missing JS symbol: wireEmailTab`.

- [ ] In `RUCKUS/ruckus_dashboard/static/dashboard.js`, add a CSRF reader and `wireEmailTab` near the other render helpers. Insert after the `_escape` function (ends at the line `}` after line 402):

```javascript
function _dashCsrf() {
  const m = document.querySelector('meta[name="csrf-token"]');
  return m ? m.content : "";
}

function _toast(message, ok) {
  let host = document.querySelector(".dash-toast");
  if (!host) {
    host = document.createElement("div");
    host.className = "dash-toast";
    document.body.appendChild(host);
  }
  host.textContent = message;
  host.dataset.ok = ok ? "1" : "0";
  host.classList.add("show");
  setTimeout(() => host.classList.remove("show"), 4000);
}

function wireEmailTab(root, slug) {
  const btn = root.querySelector("[data-email-tab]");
  if (!btn || btn.dataset.wired === "1") return;
  btn.dataset.wired = "1";
  btn.addEventListener("click", async () => {
    // Same skip-empty rule as _applyFilters: only send active filter values.
    const raw = activeFilters[slug] || {};
    const filters = {};
    Object.entries(raw).forEach(([k, v]) => {
      if (v !== "" && v != null) filters[k] = v;
    });
    btn.disabled = true;
    try {
      const res = await fetch("/api/reports/tab", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json",
                   "X-CSRF-Token": _dashCsrf() },
        body: JSON.stringify({ slug, filters }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.ok && body.sent) {
        _toast(`Report e-mailed (${(body.recipients || []).join(", ")})`, true);
      } else {
        _toast(`Email failed: ${body.error || ("HTTP " + res.status)}`, false);
      }
    } catch (e) {
      _toast(`Email failed: ${e.message}`, false);
    } finally {
      btn.disabled = false;
    }
  });
}
```

- [ ] Call it from `renderModule`. Find the line `wireViewToggle(root, slug, spec);` (around line 167) and add directly after it:

```javascript
  wireViewToggle(root, slug, spec);
  wireEmailTab(root, slug);
```

- [ ] Run — expect PASS:
```
cd "<repo>" && python -m pytest tests/integration/test_dashboard_js.py -k email_tab -q
```
Expected: 2 passed.

- [ ] (Optional, no test) Add minimal toast CSS to `RUCKUS/ruckus_dashboard/static/styles.css` so the toast is visible. Append:

```css
.dash-toast {
  position: fixed; bottom: 20px; right: 20px; z-index: 1000;
  max-width: 360px; padding: 10px 14px; border-radius: 6px;
  background: #1f2a37; color: #fff; opacity: 0;
  transform: translateY(8px); transition: opacity .2s, transform .2s;
  pointer-events: none; font-size: 14px;
}
.dash-toast.show { opacity: 1; transform: translateY(0); }
.dash-toast[data-ok="0"] { background: #b03a2e; }
.module-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
```

- [ ] Run the full dashboard.js test module to ensure no regression:
```
cd "<repo>" && python -m pytest tests/integration/test_dashboard_js.py -q
```
Expected: all passed.

- [ ] Commit:
```
git add RUCKUS/ruckus_dashboard/static/dashboard.js RUCKUS/ruckus_dashboard/static/styles.css tests/integration/test_dashboard_js.py
git commit -m "feat(reports): wire Email this tab button (POST filters + CSRF + toast)"
```

---

## Task 14 — Full-suite green + ruff + coverage gate

**Files**
- Test: entire suite.

- [ ] Run the entire suite with coverage exactly as CI does:
```
cd "<repo>" && python -m pytest -q --cov=ruckus_dashboard --cov-fail-under=75 2>&1 | tail -20
```
Expected: all tests pass (302 baseline + the new unit/integration tests, roughly 330+); coverage ≥ 75%.

- [ ] Run ruff exactly as CI does:
```
cd "<repo>" && python -m ruff check RUCKUS/ruckus_dashboard tests
```
Expected: All checks passed!

- [ ] If ruff flags an unused import (e.g. the `Any`/`all_modules` re-import in `notifications.py`, or `from typing import Any` left unused in `scheduler.py`), remove the specific unused name and re-run. Do not add `# noqa` unless the import is a deliberate re-export (the scheduler `collect_report_data` re-export already carries `# noqa: F401`).

- [ ] Final commit if any lint cleanup was needed:
```
git add -A
git commit -m "chore(reports): lint cleanup; full suite + ruff green"
```

---

## Self-Review

### Spec coverage map (design §5.8 → tasks)

| Spec item | Where implemented |
|-----------|-------------------|
| `reports/model.py` dataclasses (`ColumnSpec`, `DrillSample`, `ModuleReport`, `ReportModel`) | Task 1 |
| `apply_filter` mirrors `dashboard.js:_applyFilters` (exact match, empty-skip, `__search`) | Task 2 |
| `project_columns` (declared keys + `id`, order) | Task 3 |
| `_rows_from_payload` (items+raw_count, `_overview`, topology nodes, items-only) | Task 4 |
| `_collect_module` (gate→fetch→adapt→summary→filter→project→drill, error containment, debug gating) | Task 5 |
| `collect_report_model` (enumerate `all_modules()`, bounded pool, `future.result(timeout=)`, real capability gate §1.5 fix) | Task 6 |
| Backward-compat `collect_report_data` wrapper (alert path unchanged §5.4) | Task 7 |
| `excel.py` accepts `ReportModel` + legacy dict; Coverage block; `_safe_sheet_name` | Task 8 |
| Generic per-module sheets (summary/list/raw/drill), 1000-row cap (Open-Q #2) | Task 9 |
| `POST /api/reports/tab` (auth, CSRF, slug 404, filter validation, disabled→422, recipients) §5.6 | Task 10 |
| `/api/reports/test` + `/api/reports/generate` + daily report cover 19 modules; topology/overview no-crash §1.1 | Task 11 |
| CSRF meta + "Email this tab" button §5.6 | Task 12 |
| `dashboard.js` posts `activeFilters` with CSRF + toast §5.6 | Task 13 |
| Suite + ruff + coverage gate green (§5.9) | Task 14 |
| Info-disclosure parity (`RUCKUS_SHOW_DEBUG` gates raw error bodies) §5.7 | Task 5 (`_error_message`), Task 10 (route), Task 9 (renderer surfaces only `ModuleReport.errors[*].message`) |

### Placeholder scan
No "TBD", "similar to Task N", "add error handling", or "write tests for the above" remain — every code step contains complete, runnable code. Each failing-test step shows the real expected failure reason; each implementation step shows the full function body.

### Type / name consistency (cross-task)
- `ColumnSpec(label, key, kind)` — defined Task 1; built from `spec.columns` (`Column(label, key, kind)`, `modules/_base.py:30-33`) in Tasks 5 & 6; read by `excel.py` Task 9. Consistent.
- `ModuleReport` fields (`slug, title, group, status, columns, summary, rows, row_total, raw_samples, drill_samples, filters_applied, errors, note`) — set in Tasks 5/6, read in Task 9. Names match exactly.
- `DrillSample(entity_id, sections, error)` — produced Task 5, rendered Task 9. Match.
- `collect_report_model(connection, config, *, available_ops, slugs, filters_by_slug, drill_sample_size, raw_sample_size, per_module_timeout, max_workers)` — signature defined Task 6; called with `slugs=(slug,)` + `filters_by_slug={slug: filters}` in Task 10 and `slugs=None` in Task 11. Keyword names match.
- `build_report(data_or_model)` — Task 8; accepts `ReportModel` (Tasks 10/11) and legacy dict (alert/scheduler legacy + existing test). Match.
- `collect_report_data(connection, config)` — Task 7; re-exported from `notify/scheduler.py`; consumed by `routes/notifications.py` only via the alert path through the scheduler tick (unchanged). The route handlers now call `collect_report_model` directly (Task 11). No dangling import: the old `from ..notify.scheduler import collect_report_data` local imports in the route are removed in Task 11.
- CSRF: JS reads `meta[name="csrf-token"]` (Task 13) which Task 12 adds to `base.html`; server validates `X-CSRF-Token` (`auth/csrf.py:17`). Match.
- Capability gate: `CapabilityGate(available=...)` / `.satisfied(...)` (`infra/capability_gate.py`) used in Tasks 5, 6, 10. Match.

### Known-issue non-regression (design §2 Non-Goals, §5.7)
- Alert path: `collect_report_data` keeps the legacy 4-domain full-row dict (Task 7) — `state_from_data` untouched; existing `test_state_from_data_counts` + scheduler due-logic tests stay green (asserted in Task 7 & 11).
- No new outbound HTTP paths; all fetches still route through existing clients (SSRF allowlist unchanged).
- Raw upstream error bodies gated behind `RUCKUS_SHOW_DEBUG` (Task 5), mirroring `routes/modules.py:_upstream_message` — no new info-disclosure.
- Per-module timeout + `max_workers` bound the scheduler tick / request worker (Task 6).

### Open questions resolved with defaults (design §6)
- #1 drill=3 / raw=2 caps → defaults in `collect_report_model` (Task 6).
- #2 list row cap → `_LIST_ROW_CAP = 1000` with "+N more" note (Task 9).
- #3 daily report filters → unfiltered (no `filters_by_slug`); per-tab uses live filters (Tasks 11, 10). Daily uses an empty/optional gate via `set_available_ops` (Task 11).
- #4 per-tab recipients → default to `report.recipients`, optional `recipients` override validated (Task 10).
- #5 topology in Excel → node table via `_rows_from_payload` nodes path (Task 4) + generic sheet (Task 9); edge sheet deferred.
- #6 overview → included as a sheet with the "(no list)" note (Tasks 4 & 9), no opt-out flag added (YAGNI).
- #7 `collect_report_data` kept indefinitely as the alert shim (Task 7).
- #8 Excel-only this round; model is JSON-able for future CSV/PDF (no extra renderer built — YAGNI).

---

## Execution Handoff

Two ways to execute this plan:

**Subagent-driven (recommended for parallel-safe tasks).** Use `superpowers:subagent-driven-development`. Tasks 1→9 are a mostly-linear data/render spine (each builds on the prior file); dispatch them sequentially. Tasks 10–13 (route, templates, JS) are independent surfaces once Tasks 1–9 land — they may be dispatched in parallel to separate subagents, then reconciled in Task 14. Each subagent should run the exact `pytest`/`ruff` command shown and report the pass/fail line before committing.

**Inline (single session).** Use `superpowers:executing-plans`. Work top to bottom, committing after every task. Re-run the Task 14 full-suite + ruff gate before declaring done; do not claim completion without pasting the final `pytest`/`ruff` output (per `superpowers:verification-before-completion`).

Either way: TDD is mandatory — write the failing test, see it fail for the stated reason, implement, see it pass, commit. Keep the suite green (302 baseline + additions) and ruff clean on every commit.
