# SP1 — Universal Per-Column Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every table column on every module (list, grid, and drill) filterable by deriving the filter control from `Column.kind`, with optional per-`Column` overrides, client-side filtering everywhere, and a declarative `server_filter` push-down token (only `ZONE_ID` today).

**Architecture:** Filters become *derived from columns* at module-registration time (`resolve_filters()` in `modules/_base.py`, stored on `ModuleSpec.resolved_filters`). The list endpoint serializes the resolved set; the data/drill endpoints parse multi-value and range query params via a new `_parse_filters()` (replacing the lossy `request.args.to_dict()`). The SmartZone `/query/*` body builder is generalized so any column carrying a `server_filter` token pushes down upstream; everything else is filtered in `dashboard.js`, whose `_applyFilters`/`renderFilters` gain `select` (multi), `search:<key>` (per-column substring), and `range:<key>` (min/max) modes plus a drill-table filter helper.

**Tech Stack:** Python 3.10+ / Flask 3, frozen `dataclasses`; vanilla ES (no framework) in `static/dashboard.js`; pytest + the `responses` library for HTTP mocking; ruff on CI.

---

## Repo & invariants (read before starting)

- Repo root: `C:\Users\sshoaib\OneDrive - Mohamed & Obaid Almulla LLC\Documents\RUCKUS-Dashboard`. Code is rooted at `RUCKUS\ruckus_dashboard\`.
- Run tests from the repo root: `python -m pytest -q` (301 tests must stay green). `tests/conftest.py` inserts `RUCKUS/` on `sys.path`, so imports are `ruckus_dashboard.*`.
- CI (`.github/workflows/ci.yml`) runs `ruff check RUCKUS/ruckus_dashboard tests` then `pytest -v --cov=ruckus_dashboard --cov-fail-under=75`. **Keep both green.** Default ruff config (no `[tool.ruff]` in `RUCKUS/pyproject.toml`) — so default rules: unused imports (F401), unused vars (F841), line length is NOT enforced by default, but match existing style.
- JS "tests" are **source-symbol assertions** in `tests/integration/test_dashboard_js.py` (no DOM harness). New JS behavior is verified by asserting the presence of new symbols/strings in the served `dashboard.js`. **Do not remove** any symbol asserted there: `startModulePoller`, `stopModulePoller`, `renderModule`, `renderTile`, `renderColumns`, `renderFilters`, `renderData`, `renderGrid`, `renderDrill`, `renderKeyVals`, `renderGenericTable`, `wireViewToggle`, `activeViews`, `KPI_FILTER_MAP`, `applyKpiFilter`, `_escape`, `_kvListHtml`, `_humanKey`, `showTab`, `_drillUpdatePayload`, `status-pill`, `data-href`, `/m/`, `_escape(value)`, `_escape(formatKpiValue(v))`, `&quot;`.
- Envelope contract (`infra/envelope.py:24-44`): `status` ∈ {`complete`,`partial`,`error`}; `build_envelope` is called with `data=`, `summary=`, `errors=`.
- The never-500 contract (`routes/modules.py:98-111`): unknown/unsupported filters must never raise server-side — they are simply ignored upstream and applied (or dropped) in the browser.

---

## File Structure

| File | Responsibility | Tasks |
|------|----------------|-------|
| `RUCKUS\ruckus_dashboard\modules\_base.py` | Add `Column.filterable/filter_kind/server_filter`; add `Filter.server_filter`; add `_infer_filter_kind()` + `resolve_filters()`; compute `ModuleSpec.resolved_filters` in `__post_init__`. | 1, 2, 3 |
| `RUCKUS\ruckus_dashboard\routes\modules.py` | Serialize `spec.resolved_filters` in `/api/modules`; add `_parse_filters()` (multi-value + range aware); use it at the 3 `request.args.to_dict()` sites. | 4, 5 |
| `RUCKUS\ruckus_dashboard\clients\smartzone.py` | Generalize `smartzone_query_body` to map any `server_filter` token from `filters["__server"]` into `body["filters"]`, keeping `ZONE_ID`. | 6 |
| `RUCKUS\ruckus_dashboard\modules\aps.py` | Mark `zone` column `server_filter="ZONE_ID"`; route `_filter_body` through the generalized push-down; trim hand `filters=(…)`. | 7 |
| `RUCKUS\ruckus_dashboard\modules\switches.py`, `ports.py`, `clients.py` | Trim hand `filters=(…)` to rely on column derivation; keep needed overrides. | 8 |
| `RUCKUS\ruckus_dashboard\static\dashboard.js` | Upgrade `_applyFilters` (select-multi / `search:<k>` / `range:<k>`); upgrade `renderFilters` (resolved list, option rebuild, clear-all); add `renderDrillFilters` + wire into `renderGenericTable`. | 9, 10, 11, 12 |
| `tests\unit\modules\test_base.py` | `resolve_filters` inference + override + suppression + `server_filter` unit tests. | 1, 2, 3 |
| `tests\unit\modules\test_columns.py` | Extend contract: resolved filters valid; every non-suppressed column yields a resolved filter; kinds ∈ {select,search,range}. | 3 |
| `tests\unit\clients\test_smartzone_query_body.py` | Extend: generic `server_filter` token → `body["filters"]`; absent value omitted; multiple tokens accumulate; `ZONE_ID` still works. | 6 |
| `tests\unit\routes\test_parse_filters.py` (new) | `_parse_filters` keeps repeated select params as a list; parses `key__min`/`key__max`; ignores unknown keys; per-column search. | 5 |
| `tests\unit\routes\__init__.py` (new) | Package marker for the new routes test dir. | 5 |
| `tests\integration\test_routes_new_ui.py` | Assert `/api/modules` filters now carry `server_filter`; assert resolved filters cover all columns for `aps`. | 4 |
| `tests\integration\test_dashboard_js.py` | Assert new JS symbols/strings (`search:`, `range:`, multi-select, option rebuild, `renderDrillFilters`). | 9, 10, 11, 12 |
| `tests\unit\modules\test_aps.py` | Assert `zone` push-down still emits `ZONE_ID` through the new path. | 7 |

---

## Control inference (single source of truth — used by every task)

`Column.kind` → resolved `Filter.kind`:

| `Column.kind` | Resolved control |
|---|---|
| `status` | `select` |
| `text`, `link` | `search` |
| `number`, `bytes`, `rate`, `uptime` | `range` |

A `Column` with `filterable=False` or `filter_kind="none"` yields **no** filter. A `Column.filter_kind` other than `None`/`"none"` overrides the inferred kind. An explicit `Filter` in `ModuleSpec.filters` whose `key` matches a column **wins** (its `kind`/`label`/`server_filter` replace the derived one); an explicit `Filter` with no matching column is appended as-is. `Column.server_filter` is carried onto the resolved `Filter.server_filter`.

---

## Task 1 — `Column` gains filter metadata; `Filter` gains `server_filter`

**Files**
- Modify: `RUCKUS\ruckus_dashboard\modules\_base.py` (lines 29-41: `Column`, `Filter`)
- Test: `tests\unit\modules\test_base.py` (append)

Steps:

- [ ] Add the failing test to the end of `tests\unit\modules\test_base.py`:

```python
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
```

- [ ] Run it — expect FAIL (`TypeError: __init__() got an unexpected keyword argument 'filterable'` / `'server_filter'`):

```
python -m pytest tests/unit/modules/test_base.py -q
```

- [ ] Implement: replace the `Column` and `Filter` dataclasses in `RUCKUS\ruckus_dashboard\modules\_base.py` (currently lines 29-41) with:

```python
@dataclass(frozen=True)
class Column:
    label: str
    key: str
    kind: str = "text"          # text | status | bytes | uptime | number | link | rate
    filterable: bool = True     # set False to suppress a filter for this column
    filter_kind: str | None = None    # override inferred control: select|search|range|none
    server_filter: str | None = None  # push-down token, e.g. "ZONE_ID"; None = client-only


@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    kind: str = "select"        # select | search | range
    server_filter: str | None = None
```

- [ ] Run tests — expect PASS:

```
python -m pytest tests/unit/modules/test_base.py -q
```

- [ ] Commit:

```
git add RUCKUS/ruckus_dashboard/modules/_base.py tests/unit/modules/test_base.py
git commit -m "feat(modules): add filter metadata to Column and server_filter to Filter"
```

---

## Task 2 — `resolve_filters()` helper + `_infer_filter_kind()`

**Files**
- Modify: `RUCKUS\ruckus_dashboard\modules\_base.py` (add module-level functions after the `Filter` dataclass, before `ModuleSpec`)
- Test: `tests\unit\modules\test_base.py` (append)

Steps:

- [ ] Add the failing test to the end of `tests\unit\modules\test_base.py`:

```python
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
```

- [ ] Run it — expect FAIL (`ImportError: cannot import name 'resolve_filters'`):

```
python -m pytest tests/unit/modules/test_base.py -q
```

- [ ] Implement: in `RUCKUS\ruckus_dashboard\modules\_base.py`, immediately after the `Filter` dataclass (after line 41 in the original, now shifted) and **before** `class ModuleSpec`, add:

```python
# Column.kind -> inferred filter control. status enumerates, text/link search,
# numeric-ish columns use a min/max range.
_FILTER_KIND_BY_COLUMN_KIND = {
    "status": "select",
    "text": "search",
    "link": "search",
    "number": "range",
    "bytes": "range",
    "rate": "range",
    "uptime": "range",
}


def _infer_filter_kind(column_kind: str) -> str:
    """Map a Column.kind to a filter control kind (default: search)."""
    return _FILTER_KIND_BY_COLUMN_KIND.get(column_kind, "search")


def resolve_filters(
    columns: tuple[Column, ...],
    overrides: tuple[Filter, ...],
) -> tuple[Filter, ...]:
    """Derive the universal filter set from columns, applying overrides.

    - Every filterable column yields one Filter; kind is inferred from
      Column.kind unless Column.filter_kind overrides it.
    - filterable=False or filter_kind="none" suppresses the column's filter.
    - An explicit Filter in ``overrides`` whose key matches a column replaces
      the derived one (label/kind/server_filter win). Explicit filters with no
      matching column are appended in declaration order.
    """
    override_by_key = {f.key: f for f in overrides}
    resolved: list[Filter] = []
    seen: set[str] = set()
    for col in columns:
        if not col.filterable or col.filter_kind == "none":
            continue
        if col.key in override_by_key:
            resolved.append(override_by_key[col.key])
        else:
            kind = col.filter_kind or _infer_filter_kind(col.kind)
            resolved.append(Filter(key=col.key, label=col.label, kind=kind,
                                   server_filter=col.server_filter))
        seen.add(col.key)
    for f in overrides:
        if f.key not in seen:
            resolved.append(f)
            seen.add(f.key)
    return tuple(resolved)
```

- [ ] Run tests — expect PASS:

```
python -m pytest tests/unit/modules/test_base.py -q
```

- [ ] Commit:

```
git add RUCKUS/ruckus_dashboard/modules/_base.py tests/unit/modules/test_base.py
git commit -m "feat(modules): resolve_filters() derives filter controls from columns"
```

---

## Task 3 — Compute `ModuleSpec.resolved_filters` in `__post_init__`

**Files**
- Modify: `RUCKUS\ruckus_dashboard\modules\_base.py` (`ModuleSpec`, lines 43-74)
- Test: `tests\unit\modules\test_base.py` (append) and `tests\unit\modules\test_columns.py` (extend)

`ModuleSpec` is a frozen dataclass; set the computed field via `object.__setattr__` inside `__post_init__`. Declare `resolved_filters` as a non-init field so callers never pass it.

Steps:

- [ ] Add the failing test to the end of `tests\unit\modules\test_base.py`:

```python
def test_module_spec_computes_resolved_filters_from_columns():
    spec = ModuleSpec(
        slug="rf", title="RF", group="Wireless", icon="?",
        poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=noop_summary,
        requires_platforms=("smartzone",), requires_capabilities=(),
        supports_views=("table",),
        columns=(Column("Name", "name"), Column("Status", "status", "status")),
        filters=(),
    )
    by_key = {f.key: f for f in spec.resolved_filters}
    assert by_key["name"].kind == "search"
    assert by_key["status"].kind == "select"


def test_module_spec_resolved_filters_default_empty_without_columns():
    spec = ModuleSpec(
        slug="rf2", title="RF2", group="Wireless", icon="?",
        poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=noop_summary,
        requires_platforms=("smartzone",), requires_capabilities=(),
        supports_views=("table",),
    )
    assert spec.resolved_filters == ()


def test_module_spec_resolved_filters_honor_explicit_override():
    spec = ModuleSpec(
        slug="rf3", title="RF3", group="Wireless", icon="?",
        poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=noop_summary,
        requires_platforms=("smartzone",), requires_capabilities=(),
        supports_views=("table",),
        columns=(Column("Zone", "zone", "text", server_filter="ZONE_ID"),),
        filters=(),
    )
    assert spec.resolved_filters[0].server_filter == "ZONE_ID"
```

- [ ] Run it — expect FAIL (`AttributeError: 'ModuleSpec' object has no attribute 'resolved_filters'`):

```
python -m pytest tests/unit/modules/test_base.py -q
```

- [ ] Implement: in `RUCKUS\ruckus_dashboard\modules\_base.py`, change the imports line 4 to include `field`:

```python
from dataclasses import dataclass, field
```

  Then add the `resolved_filters` field to `ModuleSpec` (after `filters: tuple[Filter, ...] = ()`, currently line 60):

```python
    resolved_filters: tuple[Filter, ...] = field(default=(), init=False, compare=False)
```

  Then at the **end** of `ModuleSpec.__post_init__` (after the `poll_seconds` check, line 74), append:

```python
        object.__setattr__(self, "resolved_filters",
                           resolve_filters(self.columns, self.filters))
```

- [ ] Run tests — expect PASS:

```
python -m pytest tests/unit/modules/test_base.py -q
```

- [ ] Extend the contract test. Append to `tests\unit\modules\test_columns.py`:

```python
RESOLVED_FILTER_KINDS = {"select", "search", "range"}


def test_resolved_filters_valid_and_cover_columns():
    for m in all_modules():
        suppressed = {c.key for c in m.columns
                      if not c.filterable or c.filter_kind == "none"}
        resolved_keys = {f.key for f in m.resolved_filters}
        for f in m.resolved_filters:
            assert isinstance(f.key, str) and f.key, \
                f"{m.slug}: resolved filter key must be non-empty str"
            assert f.kind in RESOLVED_FILTER_KINDS, \
                f"{m.slug}: bad resolved filter kind {f.kind!r}"
        for col in m.columns:
            if col.key in suppressed:
                continue
            assert col.key in resolved_keys, \
                f"{m.slug}: column {col.key!r} has no resolved filter"
```

- [ ] Run the contract + whole modules suite — expect PASS (this proves every existing module resolves cleanly, including alarms/rogues whose explicit filters must still survive):

```
python -m pytest tests/unit/modules/ -q
```

- [ ] Commit:

```
git add RUCKUS/ruckus_dashboard/modules/_base.py tests/unit/modules/test_base.py tests/unit/modules/test_columns.py
git commit -m "feat(modules): compute ModuleSpec.resolved_filters in __post_init__"
```

---

## Task 4 — `/api/modules` serializes resolved filters (with `server_filter`)

**Files**
- Modify: `RUCKUS\ruckus_dashboard\routes\modules.py` (line 59 — filters serialization)
- Test: `tests\integration\test_routes_new_ui.py` (append)

Steps:

- [ ] Add the failing test to the end of `tests\integration\test_routes_new_ui.py`:

```python
def test_module_list_filters_are_resolved_with_server_filter():
    app = make_app()
    with app.test_client() as c:
        r = c.get("/api/modules")
        assert r.status_code == 200
        by_slug = {m["slug"]: m for m in r.json["modules"]}
        aps = by_slug["aps"]
        # Resolved filters now include server_filter on every entry.
        assert aps["filters"], "aps should declare resolved filters"
        for f in aps["filters"]:
            assert {"key", "label", "kind", "server_filter"} <= set(f.keys())
        # Every aps column (none suppressed) yields a resolved filter.
        col_keys = {col["key"] for col in aps["columns"]}
        filter_keys = {f["key"] for f in aps["filters"]}
        assert col_keys <= filter_keys, "every aps column should be filterable"
        # zone pushes down as ZONE_ID (set in Task 7); assert the field exists now.
        kinds = {f["kind"] for f in aps["filters"]}
        assert kinds <= {"select", "search", "range"}
```

- [ ] Run it — expect FAIL (`KeyError`/`AssertionError`: serialized filter dicts have no `server_filter` key, and only the 2 hand-declared filters are present so `col_keys <= filter_keys` is False):

```
python -m pytest tests/integration/test_routes_new_ui.py::test_module_list_filters_are_resolved_with_server_filter -q
```

- [ ] Implement: in `RUCKUS\ruckus_dashboard\routes\modules.py`, replace the filters serialization at line 59:

```python
             "filters": [{"key": f.key, "label": f.label, "kind": f.kind} for f in m.filters],
```

  with:

```python
             "filters": [{"key": f.key, "label": f.label, "kind": f.kind,
                          "server_filter": f.server_filter} for f in m.resolved_filters],
```

- [ ] Run the new test — expect PASS for the `server_filter` and kinds asserts; the `col_keys <= filter_keys` assert PASSES once derivation is in (Task 3 already shipped). (`zone` push-down value is set in Task 7; this test only checks the field is present.):

```
python -m pytest tests/integration/test_routes_new_ui.py::test_module_list_filters_are_resolved_with_server_filter -q
```

- [ ] Run the existing route tests to confirm `test_module_list_includes_columns_and_filters` still passes (it asserts `{"key","label","kind"} <= set(...)` — a subset, so adding `server_filter` is compatible):

```
python -m pytest tests/integration/test_routes_new_ui.py -q
```

- [ ] Commit:

```
git add RUCKUS/ruckus_dashboard/routes/modules.py tests/integration/test_routes_new_ui.py
git commit -m "feat(routes): serialize resolved filters with server_filter in /api/modules"
```

---

## Task 5 — `_parse_filters()` replaces `request.args.to_dict()` (multi-value + range aware)

**Files**
- Modify: `RUCKUS\ruckus_dashboard\routes\modules.py` (add helper; replace `request.args.to_dict()` at lines 91, 140, 171)
- Create: `tests\unit\routes\__init__.py`
- Create: `tests\unit\routes\test_parse_filters.py`

Design of the parsed dict (consumed by fetchers and the push-down helper):
- For each resolved filter on the spec:
  - `kind == "range"`: read `<key>__min` / `<key>__max`; if either present, set `filters[key] = {"min": <str|None>, "max": <str|None>}`.
  - else (`select`/`search`): use `request.args.getlist(key)`; if 1 value → store the scalar string; if >1 → store the list (fixes the `to_dict()` last-wins bug for repeated selects).
- A reserved `__server` sub-dict maps each **present** `server_filter` token to its first value (`{"ZONE_ID": "z1"}`), so the SmartZone body builder (Task 6) and `aps._filter_body` (Task 7) stay declarative and never re-derive tokens.
- Keys not in the resolved set are ignored (never raises) — preserves the never-500 contract.

Steps:

- [ ] Create `tests\unit\routes\__init__.py` (empty file):

```python
```

- [ ] Create the failing test `tests\unit\routes\test_parse_filters.py`:

```python
from werkzeug.datastructures import MultiDict
from ruckus_dashboard.modules._base import Filter
from ruckus_dashboard.routes.modules import _parse_filters

SELECTS = (Filter("status", "Status", "select"),)
SEARCH = (Filter("name", "Name", "search"),)
RANGE = (Filter("clients", "Clients", "range"),)
ZONE = (Filter("zone", "Zone", "select", server_filter="ZONE_ID"),)


def test_repeated_select_kept_as_list():
    args = MultiDict([("status", "online"), ("status", "flagged")])
    out = _parse_filters(args, SELECTS)
    assert out["status"] == ["online", "flagged"]


def test_single_select_is_scalar():
    args = MultiDict([("status", "online")])
    out = _parse_filters(args, SELECTS)
    assert out["status"] == "online"


def test_search_scalar():
    args = MultiDict([("name", "lobby")])
    out = _parse_filters(args, SEARCH)
    assert out["name"] == "lobby"


def test_range_min_max_packed():
    args = MultiDict([("clients__min", "5"), ("clients__max", "20")])
    out = _parse_filters(args, RANGE)
    assert out["clients"] == {"min": "5", "max": "20"}


def test_range_only_min():
    args = MultiDict([("clients__min", "5")])
    out = _parse_filters(args, RANGE)
    assert out["clients"] == {"min": "5", "max": None}


def test_range_absent_omits_key():
    out = _parse_filters(MultiDict([]), RANGE)
    assert "clients" not in out


def test_unknown_key_ignored():
    args = MultiDict([("mystery", "x")])
    out = _parse_filters(args, SELECTS)
    assert out == {}


def test_server_filter_token_collected():
    args = MultiDict([("zone", "z1")])
    out = _parse_filters(args, ZONE)
    assert out["zone"] == "z1"
    assert out["__server"] == {"ZONE_ID": "z1"}


def test_server_filter_absent_no_server_dict():
    out = _parse_filters(MultiDict([]), ZONE)
    assert "__server" not in out


def test_page_and_limit_passthrough():
    # Paging params (used by smartzone_query_body) survive even when not a filter.
    args = MultiDict([("page", "2"), ("limit", "100")])
    out = _parse_filters(args, SELECTS)
    assert out["page"] == "2"
    assert out["limit"] == "100"
```

- [ ] Run it — expect FAIL (`ImportError: cannot import name '_parse_filters'`):

```
python -m pytest tests/unit/routes/test_parse_filters.py -q
```

- [ ] Implement the helper in `RUCKUS\ruckus_dashboard\routes\modules.py`. Add after `_log_upstream` (after line 47), before `@bp.get("/api/modules")`:

```python
# Paging params consumed by smartzone_query_body / pagers; not column filters,
# but must survive the parse so the body builder still sees them.
_PASSTHROUGH_KEYS = ("page", "limit")


def _parse_filters(args, resolved_filters) -> dict:
    """Build the filter dict threaded into FetcherContext.filters.

    Multi-value selects are kept as lists (fixes request.args.to_dict()
    last-wins); range filters are packed as {"min","max"}; present
    server_filter tokens are collected under a reserved ``__server`` key.
    Unknown query keys are ignored so an unsupported filter never 500s.
    """
    out: dict = {}
    server: dict = {}
    for f in resolved_filters:
        if f.kind == "range":
            lo = args.get(f"{f.key}__min")
            hi = args.get(f"{f.key}__max")
            if lo is not None or hi is not None:
                out[f.key] = {"min": lo, "max": hi}
        else:
            values = args.getlist(f.key)
            if not values:
                continue
            out[f.key] = values[0] if len(values) == 1 else values
        if f.server_filter and f.key in out:
            value = out[f.key]
            if isinstance(value, dict):
                value = value.get("min") or value.get("max")
            elif isinstance(value, list):
                value = value[0] if value else None
            if value:
                server[f.server_filter] = value
    for key in _PASSTHROUGH_KEYS:
        if key in args:
            out[key] = args.get(key)
    if server:
        out["__server"] = server
    return out
```

- [ ] Run the helper test — expect PASS:

```
python -m pytest tests/unit/routes/test_parse_filters.py -q
```

- [ ] Wire the helper into the three endpoints. In `module_data` replace line 91:

```python
    filters = request.args.to_dict()
```

  with:

```python
    filters = _parse_filters(request.args, spec.resolved_filters)
```

  In `module_drill` replace line 140 (same text) with the identical replacement. In `module_drill_tab` replace line 171 (same text) with the identical replacement. All three `spec` variables are already in scope (`module_data`/`module_drill`/`module_drill_tab` each fetch `spec = MODULES.get(slug)` at the top).

- [ ] Run the route integration tests — expect PASS (no behavior change for the existing tests; they send no filter query params, so `_parse_filters` returns `{}` like `to_dict()` did, except paging keys which those tests don't send either):

```
python -m pytest tests/integration/test_routes_new_ui.py -q
```

- [ ] Commit:

```
git add RUCKUS/ruckus_dashboard/routes/modules.py tests/unit/routes/__init__.py tests/unit/routes/test_parse_filters.py
git commit -m "feat(routes): _parse_filters keeps multi-value selects and ranges (fix to_dict last-wins)"
```

---

## Task 6 — Generalize `smartzone_query_body` to map any `server_filter` token

**Files**
- Modify: `RUCKUS\ruckus_dashboard\clients\smartzone.py` (`smartzone_query_body`, lines 648-670)
- Test: `tests\unit\clients\test_smartzone_query_body.py` (append)

Keep the legacy `zone` shortcut (so any caller passing `{"zone": ...}` still works) **and** add the token-driven path that reads `filters["__server"]` produced by `_parse_filters`.

Steps:

- [ ] Add the failing test to the end of `tests\unit\clients\test_smartzone_query_body.py`:

```python
def test_server_filter_token_maps_into_body():
    body = smartzone_query_body({"__server": {"ZONE_ID": "z9"}})
    assert body["filters"] == [{"type": "ZONE_ID", "value": "z9"}]


def test_multiple_server_filter_tokens_accumulate():
    body = smartzone_query_body({"__server": {"ZONE_ID": "z1", "AP_GROUP_ID": "g2"}})
    assert {"type": "ZONE_ID", "value": "z1"} in body["filters"]
    assert {"type": "AP_GROUP_ID", "value": "g2"} in body["filters"]
    assert len(body["filters"]) == 2


def test_empty_server_filter_dict_omits_filters():
    assert "filters" not in smartzone_query_body({"__server": {}})


def test_legacy_zone_shortcut_still_works():
    body = smartzone_query_body({"zone": "z1"})
    assert body["filters"] == [{"type": "ZONE_ID", "value": "z1"}]
```

- [ ] Run it — expect FAIL (`KeyError: 'filters'`: the `__server` dict is ignored by the current builder):

```
python -m pytest tests/unit/clients/test_smartzone_query_body.py -q
```

- [ ] Implement: in `RUCKUS\ruckus_dashboard\clients\smartzone.py`, replace the filter portion of `smartzone_query_body` (the tail, currently lines 667-670):

```python
    body: dict[str, Any] = {"page": page, "limit": limit}
    if f.get("zone"):
        body["filters"] = [{"type": "ZONE_ID", "value": f["zone"]}]
    return body
```

  with:

```python
    body: dict[str, Any] = {"page": page, "limit": limit}
    query_filters: list[dict[str, Any]] = []
    # Declarative push-down: every present server_filter token (collected by
    # routes._parse_filters under "__server") maps to a /query/* filter clause.
    for token, value in (f.get("__server") or {}).items():
        if value:
            query_filters.append({"type": token, "value": value})
    # Legacy shortcut: a bare {"zone": ...} still pushes ZONE_ID (back-compat).
    if f.get("zone") and not any(c["type"] == "ZONE_ID" for c in query_filters):
        query_filters.append({"type": "ZONE_ID", "value": f["zone"]})
    if query_filters:
        body["filters"] = query_filters
    return body
```

- [ ] Run the query-body tests — expect PASS (all 4 new + the 7 existing, including `test_zone_filter_translated` and `test_no_filters_key_when_no_zone`):

```
python -m pytest tests/unit/clients/test_smartzone_query_body.py -q
```

- [ ] Commit:

```
git add RUCKUS/ruckus_dashboard/clients/smartzone.py tests/unit/clients/test_smartzone_query_body.py
git commit -m "feat(smartzone): map any server_filter token into /query body, keep ZONE_ID"
```

---

## Task 7 — AP zone push-down rides the token path; trim AP filters

**Files**
- Modify: `RUCKUS\ruckus_dashboard\modules\aps.py` (`_filter_body` lines 76-81; `columns` lines 124-134; `filters` lines 135-138)
- Test: `tests\unit\modules\test_aps.py` (append)

`aps.fetch` calls `smartzone_query_paged(..., body=_filter_body(ctx.filters))`. Keep `_filter_body` but route it through the generalized builder so `__server` (from `_parse_filters`) and the legacy `zone` key both work. Mark the `zone` column `server_filter="ZONE_ID"` so the resolved filter advertises the push-down and `_parse_filters` collects it. Drop the hand `filters=(…)` tuple — `status` and `zone` now derive from columns (`status`→select via `Column("Status","status","status")`; `zone`→select via the override).

Steps:

- [ ] Add the failing test to the end of `tests\unit\modules\test_aps.py`:

```python
def test_aps_filter_body_from_server_token():
    from ruckus_dashboard.modules.aps import _filter_body
    body = _filter_body({"__server": {"ZONE_ID": "z1"}})
    assert body["filters"] == [{"type": "ZONE_ID", "value": "z1"}]


def test_aps_filter_body_legacy_zone():
    from ruckus_dashboard.modules.aps import _filter_body
    body = _filter_body({"zone": "z2"})
    assert body["filters"] == [{"type": "ZONE_ID", "value": "z2"}]


def test_aps_filter_body_empty_when_no_zone():
    from ruckus_dashboard.modules.aps import _filter_body
    assert _filter_body({}) == {}
    assert _filter_body(None) == {}


def test_aps_zone_column_advertises_server_filter():
    from ruckus_dashboard.modules import MODULES
    by_key = {f.key: f for f in MODULES["aps"].resolved_filters}
    assert by_key["zone"].server_filter == "ZONE_ID"
    assert by_key["zone"].kind == "select"
    # status still derives as a select from the status-kind column
    assert by_key["status"].kind == "select"
```

- [ ] Run it — expect FAIL: `_filter_body({"__server": ...})` returns `{}` today (only reads `f["zone"]`), and `zone` resolves to a `search` filter with `server_filter=None` (zone column is plain text with no override):

```
python -m pytest tests/unit/modules/test_aps.py -q
```

- [ ] Implement. In `RUCKUS\ruckus_dashboard\modules\aps.py`:

  1. Replace `_filter_body` (lines 76-81):

```python
def _filter_body(filters: dict | None) -> dict:
    """Filter portion of a /query/ap body (page/limit are added by the pager).

    Delegates to smartzone_query_body so push-down is token-driven: it honors
    both the resolved-filter tokens under ``__server`` and the legacy ``zone``
    key. Page/limit are stripped here because the pager owns them."""
    from ..clients.smartzone import smartzone_query_body
    body = smartzone_query_body(filters or {})
    return {"filters": body["filters"]} if "filters" in body else {}
```

  2. Mark the `zone` column (line 127) to advertise the push-down. Replace:

```python
        Column("Zone", "zone"),
```

  with:

```python
        Column("Zone", "zone", filter_kind="select", server_filter="ZONE_ID"),
```

  3. Remove the now-redundant hand `filters=(…)` block (lines 135-138). Delete:

```python
    filters=(
        Filter("zone", "Zone", "select"),
        Filter("status", "Status", "select"),
    ),
```

  4. Remove the now-unused `Filter` import to satisfy ruff F401. Change line 6:

```python
from ._base import Column, Filter, FetcherContext, ModuleSpec, TabSpec
```

  to:

```python
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
```

- [ ] Run the aps tests — expect PASS (the new 4 + existing 6, including `test_aps_fetch_returns_normalised_rows` which mocks `POST /v11_0/query/ap` and is unaffected because `_filter_body(None)` → `{}`):

```
python -m pytest tests/unit/modules/test_aps.py -q
```

- [ ] Run the route list test from Task 4 again — expect PASS (zone now reports `server_filter == "ZONE_ID"`):

```
python -m pytest tests/integration/test_routes_new_ui.py -q
```

- [ ] Commit:

```
git add RUCKUS/ruckus_dashboard/modules/aps.py tests/unit/modules/test_aps.py
git commit -m "feat(aps): drive zone push-down via server_filter token, derive filters from columns"
```

---

## Task 8 — Trim hand `filters=(…)` on switches / ports / clients

**Files**
- Modify: `RUCKUS\ruckus_dashboard\modules\switches.py` (filters lines 218-220; import line 6)
- Modify: `RUCKUS\ruckus_dashboard\modules\ports.py` (filters lines 94-96; import line 12)
- Modify: `RUCKUS\ruckus_dashboard\modules\clients.py` (filters lines 207-214; import line 11)
- Test: existing `tests\unit\modules\test_columns.py::test_resolved_filters_valid_and_cover_columns` (Task 3) already enforces coverage; no new test required, but verify per-module fetch tests stay green.

Rationale: every hand filter on these modules duplicates a column that now derives automatically:
- `switches`: `Filter("status",…)` duplicates `Column("Status","status","status")` → derives as select. Drop the tuple.
- `ports`: `Filter("model",…)` duplicates `Column("Model","model")` (text → search). The spec lists `model` as a select today; to **preserve the select control**, keep it via a column override rather than a separate Filter (cleaner single source). Set `Column("Model","model", filter_kind="select")`.
- `clients`: all six hand filters (`ssid`, `os`, `band`, `quality`, `ap`, `site`) duplicate columns. `quality` is a `status` column → select. `ssid/os/ap/site/band` are text columns → would derive as `search`. The KPI quick-filters (`band:"5 GHz"`, `quality:"poor"`) and the poor-AP chips (`ap`) write **scalar exact-match** values and reflect into `SELECT` controls (`dashboard.js:244`, `:281`). To keep those working, `band`, `quality`, `ssid`, `os`, `ap`, `site` must stay **select**. Apply column overrides.

Steps:

- [ ] **switches.py** — remove the filters tuple and the unused `Filter` import.

  Delete (lines 218-220):

```python
    filters=(
        Filter("status", "Status", "select"),
    ),
```

  Change line 6:

```python
from ._base import Column, Filter, FetcherContext, ModuleSpec, TabSpec
```

  to:

```python
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
```

- [ ] **ports.py** — convert the `Model` filter to a column override; remove the filters tuple and unused `Filter` import.

  Change the `Model` column (line 87):

```python
        Column("Model", "model"),
```

  to:

```python
        Column("Model", "model", filter_kind="select"),
```

  Delete (lines 94-96):

```python
    filters=(
        Filter("model", "Model", "select"),
    ),
```

  Change line 12:

```python
from ._base import Column, Filter, FetcherContext, ModuleSpec, TabSpec
```

  to:

```python
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
```

- [ ] **clients.py** — convert the six select columns to `filter_kind="select"`; remove the filters tuple and unused `Filter` import.

  Replace these columns (lines 197-202) — set `filter_kind="select"` on the five text columns that back KPI/select controls (`ssid`, `ap`, `site`, `band`, `os`); `quality` already derives select from its `status` kind but set it explicitly for clarity:

```python
        Column("SSID", "ssid"),
        Column("AP", "ap"),
        Column("Site", "site"),
        Column("Band", "band"),
```

  to:

```python
        Column("SSID", "ssid", filter_kind="select"),
        Column("AP", "ap", filter_kind="select"),
        Column("Site", "site", filter_kind="select"),
        Column("Band", "band", filter_kind="select"),
```

  and the `OS` column (line 206):

```python
        Column("OS", "os"),
```

  to:

```python
        Column("OS", "os", filter_kind="select"),
```

  Delete the filters tuple (lines 207-214):

```python
    filters=(
        Filter("ssid", "SSID", "select"),
        Filter("os", "OS", "select"),
        Filter("band", "Band", "select"),
        Filter("quality", "Quality", "select"),
        Filter("ap", "AP", "select"),
        Filter("site", "Site", "select"),
    ),
```

  Change line 11:

```python
from ._base import Column, Filter, FetcherContext, ModuleSpec, TabSpec
```

  to:

```python
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
```

- [ ] Run the affected module + contract tests — expect PASS (coverage test from Task 3 now also asserts `switches`/`ports`/`clients` columns each map to a resolved filter):

```
python -m pytest tests/unit/modules/test_switches.py tests/unit/modules/test_ports.py tests/unit/modules/test_clients.py tests/unit/modules/test_columns.py -q
```

- [ ] Run ruff to catch any leftover unused imports — expect clean:

```
ruff check RUCKUS/ruckus_dashboard tests
```

- [ ] Commit:

```
git add RUCKUS/ruckus_dashboard/modules/switches.py RUCKUS/ruckus_dashboard/modules/ports.py RUCKUS/ruckus_dashboard/modules/clients.py
git commit -m "refactor(modules): derive switches/ports/clients filters from columns (keep select controls)"
```

---

## Task 9 — `_applyFilters`: select-multi, per-column `search:<k>`, `range:<k>`

**Files**
- Modify: `RUCKUS\ruckus_dashboard\static\dashboard.js` (`_applyFilters`, lines 179-193)
- Test: `tests\integration\test_dashboard_js.py` (append)

New key schemes stored in `activeFilters[slug]`:
- unprefixed key (e.g. `status`, `band`) → `select`. Value is a **scalar** (KPI/poor-AP path, exact match) **or an array** (multi-select); empty string/array = no constraint.
- `search:<colKey>` → case-insensitive substring on `String(row[colKey])`.
- `range:<colKey>` → `{min,max}`; numeric compare on `Number(row[colKey])`; non-numeric row fails a *set* range.
- `__search` (reserved) → global substring across all fields (back-compat).

Steps:

- [ ] Add the failing symbol test to the end of `tests\integration\test_dashboard_js.py`:

```python
def test_dashboard_js_apply_filters_supports_search_and_range_keys():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        for sym in ['"search:"', '"range:"', "Array.isArray(val)",
                    "startsWith(\"search:\")", "startsWith(\"range:\")",
                    "__search"]:
            assert sym in body, f"missing {sym}"
```

- [ ] Run it — expect FAIL (`AssertionError: missing "search:"`): the current `_applyFilters` only knows `__search` + exact-equality:

```
python -m pytest "tests/integration/test_dashboard_js.py::test_dashboard_js_apply_filters_supports_search_and_range_keys" -q
```

- [ ] Implement: replace `_applyFilters` in `RUCKUS\ruckus_dashboard\static\dashboard.js` (lines 179-193) with:

```javascript
function _applyFilters(slug, items) {
  const f = activeFilters[slug] || {};
  return items.filter(row => {
    for (const [key, val] of Object.entries(f)) {
      if (val === "" || val == null) continue;
      if (Array.isArray(val) && val.length === 0) continue;
      if (key === "__search") {
        const hay = Object.values(row).map(v => String(v ?? "")).join(" ").toLowerCase();
        if (!hay.includes(String(val).toLowerCase())) return false;
      } else if (key.startsWith("search:")) {
        const col = key.slice(7);
        if (!String(row[col] ?? "").toLowerCase().includes(String(val).toLowerCase())) return false;
      } else if (key.startsWith("range:")) {
        const col = key.slice(6);
        const n = Number(row[col]);
        const lo = val.min === "" || val.min == null ? null : Number(val.min);
        const hi = val.max === "" || val.max == null ? null : Number(val.max);
        if (lo == null && hi == null) continue;
        if (!isFinite(n)) return false;
        if (lo != null && n < lo) return false;
        if (hi != null && n > hi) return false;
      } else if (Array.isArray(val)) {
        // multi-select: row passes if its value is one of the selected.
        if (!val.map(String).includes(String(row[key] ?? ""))) return false;
      } else if (String(row[key] ?? "") !== String(val)) {
        return false;  // single-select exact match (KPI/poor-AP path)
      }
    }
    return true;
  });
}
```

- [ ] Run the new test + the escaping test (unchanged behavior must still hold) — expect PASS:

```
python -m pytest tests/integration/test_dashboard_js.py -q
```

- [ ] Commit:

```
git add RUCKUS/ruckus_dashboard/static/dashboard.js tests/integration/test_dashboard_js.py
git commit -m "feat(dashboard): _applyFilters supports multi-select, search:<col>, range:<col>"
```

---

## Task 10 — `renderFilters`: render resolved set, rebuild options, clear-all

**Files**
- Modify: `RUCKUS\ruckus_dashboard\static\dashboard.js` (`renderFilters`, lines 365-396)
- Test: `tests\integration\test_dashboard_js.py` (append)

Changes:
- Render from `spec.filters` (now the resolved set with `server_filter`).
- Per kind: `select` → `<select>` with options rebuilt from current `items` each render (fixes the build-once staleness at line 370/385); `search` → `<input type=search data-filter-key="search:<key>">`; `range` → two `<input type=number data-filter-key="range:<key>" data-bound="min|max">`.
- Replace the blunt `host.dataset.built === slug` short-circuit with a per-render rebuild that **preserves the current selection** from `activeFilters[slug]` (so re-rendering on each poll doesn't drop the user's choice or focus). Rebuild only when the option signature changes for selects.
- Add a "Clear filters" button that zeroes `activeFilters[slug]` and re-renders.
- All option text/attrs continue through `_escape` (keep `&quot;`).

Steps:

- [ ] Add the failing symbol test to the end of `tests\integration\test_dashboard_js.py`:

```python
def test_dashboard_js_render_filters_per_column_controls_and_clear():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        for sym in ['type="search" data-filter-key="search:',
                    'type="number"', 'data-filter-key="range:',
                    "data-filter-clear", "filterSignature",
                    '_escape']:
            assert sym in body, f"missing {sym}"
        # build-once staleness gate must be gone (options rebuild each render)
        assert "host.dataset.built === slug" not in body, \
            "renderFilters must not short-circuit on dataset.built"
```

- [ ] Run it — expect FAIL (`AssertionError`): current `renderFilters` has the `host.dataset.built === slug` gate and no `search:`/`range:`/clear controls:

```
python -m pytest "tests/integration/test_dashboard_js.py::test_dashboard_js_render_filters_per_column_controls_and_clear" -q
```

- [ ] Implement: replace `renderFilters` in `RUCKUS\ruckus_dashboard\static\dashboard.js` (lines 365-396) with:

```javascript
function filterSignature(filters, items) {
  // Signature changes when the filter set or the option universe changes, so
  // we only rebuild controls (and lose focus/selection) when truly necessary.
  const parts = filters.map(f => {
    if (f.kind !== "select") return `${f.key}:${f.kind}`;
    const opts = Array.from(new Set(items.map(i => i[f.key])
      .filter(v => v != null && v !== ""))).sort();
    return `${f.key}:select:${opts.join("|")}`;
  });
  return parts.join("~~");
}

function renderFilters(root, slug, spec, items) {
  const host = root.querySelector("[data-filters]");
  if (!host) return;
  const filters = spec.filters || [];
  if (!filters.length) { host.innerHTML = ""; host.dataset.sig = ""; return; }

  const sig = filterSignature(filters, items);
  if (host.dataset.sig === sig) return;   // options unchanged → keep controls
  host.dataset.sig = sig;

  const state = activeFilters[slug] || {};
  const parts = filters.map(f => {
    if (f.kind === "search") {
      const cur = state[`search:${f.key}`] || "";
      return `<label class="filter-control"><span>${_escape(f.label)}</span>` +
             `<input type="search" data-filter-key="search:${_escape(f.key)}" ` +
             `placeholder="${_escape(f.label)}…" value="${_escape(cur)}"></label>`;
    }
    if (f.kind === "range") {
      const r = state[`range:${f.key}`] || {};
      return `<label class="filter-control"><span>${_escape(f.label)}</span>` +
             `<input type="number" data-filter-key="range:${_escape(f.key)}" ` +
             `data-bound="min" placeholder="min" value="${_escape(r.min ?? "")}">` +
             `<input type="number" data-filter-key="range:${_escape(f.key)}" ` +
             `data-bound="max" placeholder="max" value="${_escape(r.max ?? "")}"></label>`;
    }
    // select — options come from controller data (escape attr + text).
    const cur = state[f.key];
    const curArr = Array.isArray(cur) ? cur.map(String) : (cur ? [String(cur)] : []);
    const values = Array.from(new Set(items.map(i => i[f.key]).filter(v => v != null && v !== "")))
      .sort().map(v => {
        const sel = curArr.includes(String(v)) ? " selected" : "";
        return `<option value="${_escape(v)}"${sel}>${_escape(v)}</option>`;
      }).join("");
    const allSel = curArr.length ? "" : " selected";
    return `<label class="filter-control"><span>${_escape(f.label)}</span>` +
           `<select data-filter-key="${_escape(f.key)}"><option value=""${allSel}>All</option>${values}</select></label>`;
  });
  parts.push(`<button class="filter-clear" data-filter-clear>Clear filters</button>`);
  host.innerHTML = parts.join("");

  host.querySelectorAll("[data-filter-key]").forEach(ctrl => {
    const handler = () => {
      const store = activeFilters[slug] = activeFilters[slug] || {};
      const key = ctrl.dataset.filterKey;
      if (key.startsWith("range:")) {
        const r = store[key] = store[key] || { min: null, max: null };
        r[ctrl.dataset.bound] = ctrl.value === "" ? null : ctrl.value;
      } else {
        store[key] = ctrl.value;
      }
      renderData(root, slug, spec, lastItems[slug] || []);
    };
    ctrl.addEventListener("change", handler);
    ctrl.addEventListener("input", handler);
  });

  const clear = host.querySelector("[data-filter-clear]");
  if (clear) clear.addEventListener("click", () => {
    activeFilters[slug] = {};
    host.dataset.sig = "";                 // force a rebuild with cleared controls
    renderFilters(root, slug, spec, lastItems[slug] || []);
    renderData(root, slug, spec, lastItems[slug] || []);
  });
}
```

- [ ] Run the new test + the full dashboard_js suite — expect PASS (the escaping test still finds `&quot;`/`_escape`; `renderColumns`/`renderFilters` symbols intact):

```
python -m pytest tests/integration/test_dashboard_js.py -q
```

- [ ] Commit:

```
git add RUCKUS/ruckus_dashboard/static/dashboard.js tests/integration/test_dashboard_js.py
git commit -m "feat(dashboard): renderFilters renders resolved set, rebuilds options, adds clear"
```

---

## Task 11 — KPI quick-filters & poor-AP chips stay consistent with new selects

**Files**
- Modify: `RUCKUS\ruckus_dashboard\static\dashboard.js` (`applyKpiFilter` reflect loop lines 242-245; `_maybePoorApBreakdown` reflect loop lines 280-282)
- Test: `tests\integration\test_dashboard_js.py` (append)

The KPI map writes **scalar** values (`band:"5 GHz"`, `quality:"poor"`) under unprefixed keys — compatible with the single-select branch of the upgraded `_applyFilters` (Task 9). The only gap: after `renderFilters` rebuilds via signature, the reflect loops set `ctrl.value` on `SELECT`s. A single-select `<select>` (no `multiple` attr) accepts a scalar `value` fine, so the existing reflect loops keep working. This task only **locks that in** with a regression assertion and ensures the reflect loops survive the rewrite (they live outside `renderFilters`, so they are unchanged — but verify and pin).

Steps:

- [ ] Add the failing regression test to the end of `tests\integration\test_dashboard_js.py`:

```python
def test_dashboard_js_kpi_and_poor_ap_reflect_into_selects():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        # KPI scalar filters still write unprefixed keys and reflect into SELECTs.
        assert 'data-filter-key="ap"' in body          # poor-AP reflect selector
        assert "applyKpiFilter" in body
        assert "ctrl.tagName === \"SELECT\"" in body
        # Single-select reflect must not assume multi-select.
        assert "band_5" in body and "poor_signal" in body
```

- [ ] Run it — expect PASS already for most symbols, but FAIL on `'data-filter-key="ap"'` only if Task 10's selector form differs. Verify against the current code at line 280 (`'[data-filter-key="ap"]'`). If the assertion fails, it indicates the poor-AP reflect selector was altered; do NOT alter it. Confirm by running:

```
python -m pytest "tests/integration/test_dashboard_js.py::test_dashboard_js_kpi_and_poor_ap_reflect_into_selects" -q
```

> Expected: this test PASSES without code changes because `applyKpiFilter` (lines 228-247) and `_maybePoorApBreakdown` (lines 259-286) were not touched by Tasks 9-10. If it FAILS, the failure is the signal that an earlier task disturbed these blocks — restore the original `applyKpiFilter`/`_maybePoorApBreakdown` text (they must remain byte-for-byte as in the pre-SP1 file) and re-run.

- [ ] If (and only if) the test failed: re-add the original reflect loops verbatim. `applyKpiFilter`'s reflect loop (lines 242-245):

```javascript
  root.querySelectorAll("[data-filter-key]").forEach(ctrl => {
    const key = ctrl.dataset.filterKey;
    if (key in filters && ctrl.tagName === "SELECT") ctrl.value = filters[key] || "";
  });
```

  `_maybePoorApBreakdown`'s reflect loop (lines 280-282):

```javascript
      root.querySelectorAll('[data-filter-key="ap"]').forEach(ctrl => {
        if (ctrl.tagName === "SELECT") ctrl.value = filters2.ap || "";
      });
```

- [ ] Run the dashboard_js suite (must include the KPI-clicks test `test_dashboard_js_kpi_filter_clicks`) — expect PASS:

```
python -m pytest tests/integration/test_dashboard_js.py -q
```

- [ ] Commit:

```
git add RUCKUS/ruckus_dashboard/static/dashboard.js tests/integration/test_dashboard_js.py
git commit -m "test(dashboard): pin KPI/poor-AP scalar filters work with upgraded selects"
```

---

## Task 12 — Drill sub-table filters (`renderGenericTable` + `renderDrillFilters`)

**Files**
- Modify: `RUCKUS\ruckus_dashboard\static\dashboard.js` (`renderGenericTable`, lines 436-454; add `renderDrillFilters`)
- Test: `tests\integration\test_dashboard_js.py` (append)

Drill tables (ports, connected switches) have dynamic columns (union of row keys, lines 441-444) and no `Column` metadata. Infer control by value type: numeric column → `range`, else → `search`. State is namespaced per drill table (`"<slug>:drill:<sig>"`) so it never collides with list filters. Filtering is client-side on the already-cached drill rows. Controls reset implicitly when the entity/tab changes because the namespace key is derived from the rows' column signature, and a fresh `renderGenericTable` call rebuilds from scratch.

Implementation approach: `renderGenericTable(container, rows, stateKey)` gains an **optional** `stateKey`. When provided, it prepends a compact filter bar (built by `renderDrillFilters`) and renders only rows passing `_applyDrillFilters(stateKey, rows)`. Existing callers that pass no `stateKey` keep today's behavior (no filter bar) — preserving the `_renderDrillSection` summary-stacking tables. The named-tab path (`_renderDrillSection` line 494) is upgraded to pass a stateKey so per-tab tables (ports/connected) get filters.

Steps:

- [ ] Add the failing symbol test to the end of `tests\integration\test_dashboard_js.py`:

```python
def test_dashboard_js_drill_table_filters_present():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        for sym in ["renderDrillFilters", "_applyDrillFilters", "drillFilters",
                    ":drill:", "data-drill-filter-key"]:
            assert sym in body, f"missing {sym}"
        # renderGenericTable still exists and is escape-safe
        assert "function renderGenericTable" in body
        assert "_escape(v ?? " in body or "_escape(v" in body
```

- [ ] Run it — expect FAIL (`AssertionError: missing renderDrillFilters`):

```
python -m pytest "tests/integration/test_dashboard_js.py::test_dashboard_js_drill_table_filters_present" -q
```

- [ ] Implement. In `RUCKUS\ruckus_dashboard\static\dashboard.js`:

  1. Add a drill-filter state map near the other state maps (after `const lastItems = {};`, line 11):

```javascript
// Per-drill-table client filter state, namespaced "<slug>:drill:<sig>".
const drillFilters = {};
```

  2. Replace `renderGenericTable` (lines 436-454) with the filter-aware version:

```javascript
function _columnIsNumeric(rows, col) {
  // Numeric if every non-empty value parses as a finite number.
  let saw = false;
  for (const r of rows) {
    const v = r ? r[col] : null;
    if (v === null || v === undefined || v === "") continue;
    saw = true;
    if (!isFinite(Number(v))) return false;
  }
  return saw;
}

function _applyDrillFilters(stateKey, rows) {
  const f = drillFilters[stateKey] || {};
  return rows.filter(row => {
    for (const [key, val] of Object.entries(f)) {
      if (val === "" || val == null) continue;
      if (key.startsWith("search:")) {
        const col = key.slice(7);
        if (!String(row[col] ?? "").toLowerCase().includes(String(val).toLowerCase())) return false;
      } else if (key.startsWith("range:")) {
        const col = key.slice(6);
        const n = Number(row[col]);
        const lo = val.min === "" || val.min == null ? null : Number(val.min);
        const hi = val.max === "" || val.max == null ? null : Number(val.max);
        if (lo == null && hi == null) continue;
        if (!isFinite(n)) return false;
        if (lo != null && n < lo) return false;
        if (hi != null && n > hi) return false;
      }
    }
    return true;
  });
}

function renderDrillFilters(container, stateKey, cols, rows, onChange) {
  const bar = cols.map(col => {
    const numeric = _columnIsNumeric(rows, col);
    if (numeric) {
      return `<label class="filter-control"><span>${_escape(col)}</span>` +
             `<input type="number" data-drill-filter-key="range:${_escape(col)}" ` +
             `data-bound="min" placeholder="min">` +
             `<input type="number" data-drill-filter-key="range:${_escape(col)}" ` +
             `data-bound="max" placeholder="max"></label>`;
    }
    return `<label class="filter-control"><span>${_escape(col)}</span>` +
           `<input type="search" data-drill-filter-key="search:${_escape(col)}" ` +
           `placeholder="${_escape(col)}…"></label>`;
  }).join("");
  const wrap = document.createElement("div");
  wrap.className = "filters drill-filters";
  wrap.innerHTML = bar;
  container.appendChild(wrap);
  wrap.querySelectorAll("[data-drill-filter-key]").forEach(ctrl => {
    const handler = () => {
      const store = drillFilters[stateKey] = drillFilters[stateKey] || {};
      const key = ctrl.dataset.drillFilterKey;
      if (key.startsWith("range:")) {
        const r = store[key] = store[key] || { min: null, max: null };
        r[ctrl.dataset.bound] = ctrl.value === "" ? null : ctrl.value;
      } else {
        store[key] = ctrl.value;
      }
      onChange();
    };
    ctrl.addEventListener("change", handler);
    ctrl.addEventListener("input", handler);
  });
}

// Simple table for array-of-objects sections (ports, etc.).
// When stateKey is provided, prepend per-column filter controls (client-side).
function renderGenericTable(container, rows, stateKey) {
  if (!Array.isArray(rows) || rows.length === 0) {
    container.innerHTML = `<p class="empty">No data.</p>`;
    return;
  }
  const cols = Array.from(rows.reduce((set, r) => {
    Object.keys(r || {}).forEach(k => set.add(k));
    return set;
  }, new Set()));

  const draw = () => {
    const shown = stateKey ? _applyDrillFilters(stateKey, rows) : rows;
    const head = cols.map(c => `<th>${_escape(c)}</th>`).join("");
    const body = shown.slice(0, 500).map(r =>
      `<tr>${cols.map(c => {
        let v = r[c];
        if (v && typeof v === "object") v = JSON.stringify(v);
        return `<td>${_escape(v ?? "—")}</td>`;
      }).join("")}</tr>`).join("");
    let tbl = table.querySelector("tbody");
    if (tbl) {
      tbl.innerHTML = body;
    } else {
      table.innerHTML =
        `<table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    }
  };

  container.innerHTML = "";
  const table = document.createElement("div");
  if (stateKey) renderDrillFilters(container, stateKey, cols, rows, draw);
  container.appendChild(table);
  draw();
}
```

  3. Pass a `stateKey` from the named-tab array path so ports/connected tables get filters. In `_renderDrillSection`, the array branch (line 493-494):

```javascript
  if (Array.isArray(section)) {
    renderGenericTable(body, section);
```

  becomes:

```javascript
  if (Array.isArray(section)) {
    renderGenericTable(body, section, `${slug}:drill:${tabSlug}`);
```

  Note: the summary-stacking path (line 475, inside the `summary` branch) deliberately keeps calling `renderGenericTable(tmp, section)` with **no** stateKey, so the summary view stays a plain stacked table without filter bars.

- [ ] Run the new test + the drill tests (`test_dashboard_js_contains_drill_rendering`, `test_drill_renders_from_cached_payload_and_stacks_summary`) — expect PASS (`renderGenericTable`, `renderKeyVals`, `_kvListHtml`, `showTab`, `_drillUpdatePayload` all intact):

```
python -m pytest tests/integration/test_dashboard_js.py -q
```

- [ ] Add drill-filter CSS so the bar is laid out (reuse existing `.filters` styling). Append to `RUCKUS\ruckus_dashboard\static\styles.css`:

```css
.drill-filters { margin: 0.5rem 0; display: flex; flex-wrap: wrap; gap: 0.5rem; }
.drill-filters .filter-control { font-size: 0.85rem; }
```

- [ ] Run the CSS presence tests (unchanged) + the whole dashboard_js suite — expect PASS:

```
python -m pytest tests/integration/test_dashboard_js.py -q
```

- [ ] Commit:

```
git add RUCKUS/ruckus_dashboard/static/dashboard.js RUCKUS/ruckus_dashboard/static/styles.css tests/integration/test_dashboard_js.py
git commit -m "feat(dashboard): per-column client filters on drill sub-tables (ports, connected)"
```

---

## Task 13 — Full-suite + ruff gate, then finish

**Files**
- Test: entire suite

Steps:

- [ ] Run the complete suite — expect PASS, count strictly greater than 301 (added ~30 tests):

```
python -m pytest -q
```

- [ ] Run ruff exactly as CI does — expect no findings:

```
ruff check RUCKUS/ruckus_dashboard tests
```

- [ ] Run the coverage gate CI uses — expect PASS (`--cov-fail-under=75`):

```
python -m pytest --cov=ruckus_dashboard --cov-fail-under=75 -q
```

- [ ] If green, finish the branch with superpowers:finishing-a-development-branch (merge / PR / cleanup decision). No extra commit needed if every task already committed.

---

## Self-Review

### Spec coverage map (design §5 → tasks)
- §5.1 `Column.filterable/filter_kind/server_filter`, `Filter.server_filter` → **Task 1**.
- §5.1 control inference table (status→select, text/link→search, number/bytes/rate/uptime→range) → **Task 2** (`_infer_filter_kind`) + enforced by **Task 3** contract test.
- §5.1/§5.2 `resolve_filters(columns, overrides)`, override-wins, suppression, compute on the spec → **Task 2** (helper) + **Task 3** (`resolved_filters` in `__post_init__`).
- §5.3 `/api/modules` serializes resolved filters incl. `server_filter` → **Task 4**.
- §5.3 replace `request.args.to_dict()` at `modules.py:91/:140/:171` with multi/range-aware `_parse_filters` → **Task 5** (helper + all three sites).
- §5.4 generalize `smartzone_query_body` to map `server_filter` tokens, keep `ZONE_ID`; fold `aps._filter_body` → **Task 6** (builder) + **Task 7** (aps).
- §5.2/§5.10 trim hand `filters=(…)` on aps/switches/ports/clients, keep needed overrides → **Task 7** (aps) + **Task 8** (switches/ports/clients).
- §5.5(a) `_applyFilters` multi-select + `search:<col>` + `range:<col>` + reserved `__search` → **Task 9**.
- §5.5(b) `renderFilters` from resolved list, per-kind controls, fix build-once staleness, clear-all, keep `_escape` → **Task 10**.
- §5.5(c) `applyKpiFilter` semantics unchanged; reflect loops understand new keys (select keys unprefixed) → **Task 11**.
- §5.7 drill sub-table client filters in `renderGenericTable`, namespaced state, infer by value type, no new endpoints → **Task 12**.
- §5.11 tests: `test_base` (resolve_filters), `test_columns` (coverage), `test_smartzone_query_body` (token), new routes `_parse_filters` test, `test_dashboard_js` new-symbol asserts → Tasks 1-3, 5, 6, 9-12.
- §5.6 UI placement: this plan keeps the compact `[data-filters]` bar (§5.6 (ii)) — header-cell layout (§5.6 (i)) is deferred (it is an open question, §6 Q1); no contract change, `module.html` untouched.

### Placeholder scan
No "TBD"/"similar to Task N"/"add error handling later" placeholders. Every code step contains complete, runnable code. Every test step shows the real test body, the exact command, and the concrete expected fail/pass reason.

### Type / name consistency
- `resolve_filters(columns: tuple[Column,...], overrides: tuple[Filter,...]) -> tuple[Filter,...]` — same signature used in Task 2 helper, Task 3 call site, and tests.
- `ModuleSpec.resolved_filters: tuple[Filter, ...]` (non-init `field`) — read in `routes/modules.py` Task 4 and `_parse_filters` Task 5; tests reference `m.resolved_filters`.
- `_parse_filters(args, resolved_filters) -> dict` — Task 5; consumed by `smartzone_query_body` via `filters["__server"]` (Task 6) and `aps._filter_body` (Task 7). The `__server` sub-dict shape `{token: value}` is produced in Task 5 and consumed identically in Task 6.
- Filter value shapes in `FetcherContext.filters`: `str | list[str] | {"min","max"} | {"__server": {...}}` — `FetcherContext.filters` stays typed `dict | None` (`_base.py:17`, unchanged), only value shapes grow, exactly as the spec states (§5.3).
- JS key schemes are consistent across `_applyFilters` (Task 9), `renderFilters` (Task 10), and drill `_applyDrillFilters` (Task 12): unprefixed = select scalar|array, `search:<col>`, `range:<col>` with `{min,max}`. `__search` reserved global box preserved.
- Every JS symbol asserted by the existing `test_dashboard_js.py` is retained (verified against the invariants list at the top).

### Risk notes the implementer must respect
- `aps.py` and the switches/ports/clients modules **import `Filter`** today; after trimming the `filters=(…)` tuples the import becomes unused → ruff F401. Tasks 7 and 8 explicitly drop `Filter` from each import line. Run `ruff check` after Task 8 (and Task 7) to catch it.
- `_parse_filters` must include `page`/`limit` passthrough (Task 5) because `aps.fetch` → `_filter_body` → `smartzone_query_body` reads them; otherwise paging silently resets. The unit test `test_page_and_limit_passthrough` pins this.
- The frozen-dataclass `resolved_filters` must use `object.__setattr__` inside `__post_init__` (Task 3) — a plain assignment raises `FrozenInstanceError`.
- Existing test `test_module_list_includes_columns_and_filters` checks `{"key","label","kind"} <= set(filter.keys())` (a **subset**), so adding `server_filter` (Task 4) is non-breaking — do not remove `key/label/kind`.
- Tasks 9-12 must not disturb `applyKpiFilter`/`_maybePoorApBreakdown` blocks; Task 11 is the explicit guard/regression for that.

---

## Execution Handoff

Two ways to execute this plan:

- **Subagent-driven (recommended):** Use **superpowers:subagent-driven-development**. Dispatch one subagent per Task (1→13) in order. Tasks 1-3 are sequential (same file, dependent fields). Tasks 4-8 depend on 1-3 but 6/7/8 touch independent files and can be parallelized *after* 4-5 land. Tasks 9-12 touch only `dashboard.js`/`styles.css` and must run **sequentially** (same file, overlapping regions) — do not parallelize them. Task 13 is the final gate. Each subagent: writes the failing test, runs it, implements, re-runs, commits with the exact message shown.

- **Inline (single session):** Use **superpowers:executing-plans**. Walk the checkboxes top-to-bottom in this session, ticking each as you go, pausing at each commit for a review checkpoint. Recommended when you want to watch the test-go-red-then-green cadence yourself.

Both paths keep the suite green at every commit and end with the CI-equivalent gate (ruff + pytest + 75% coverage) in Task 13.
