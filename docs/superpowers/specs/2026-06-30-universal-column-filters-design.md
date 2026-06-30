# SP1 — Universal Per-Column Filters (Design Spec)

**Status:** Design only (no implementation). **Date:** 2026-06-30.
**Author:** Architecture review.
**Scope:** Every column on every module tab gets a filter control; values flow
`dashboard.js → /api/modules/<slug>?…&<key>=<val> → FetcherContext.filters → fetcher`.
Covers list tables, grid view, and drill sub-tables.

> Paths below are relative to the repo root
> `C:\Users\sshoaib\OneDrive - Mohamed & Obaid Almulla LLC\Documents\RUCKUS-Dashboard`.
> Code modules are rooted at `RUCKUS\ruckus_dashboard\`.

---

## 1. Problem & current behavior (grounded in code)

Today a module declares **columns** and **filters as two unrelated tuples**, and
only a hand-curated subset of columns has a matching filter. The goal — "every
column gets a filter" — is blocked by five concrete facts in the code.

### 1.1 `Filter` carries no value-source and no server hint
`RUCKUS\ruckus_dashboard\modules\_base.py:36-41`:

```python
@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    kind: str = "select"   # select | search
```

A `Filter` is just `(key, label, kind)`. There is no link to a `Column`, no
declared option set, and no flag saying whether the controller can filter
server-side. `Column` (`_base.py:29-34`) is `(label, key, kind)` with
`kind ∈ {text,status,bytes,uptime,number,link}` (the test vocabulary in
`tests\unit\modules\test_columns.py:10` also allows `rate`).

### 1.2 Filters are declared sparsely and by hand
- `modules\aps.py:135-138` declares only `zone`, `status` — but the table has 9
  columns (`aps.py:124-134`: name, model, zone, status, clients, signal_db, fw,
  ip, mac). Six columns have no filter.
- `modules\switches.py:218-220` declares only `status` for a 9-column table
  (`switches.py:207-217`).
- `modules\ports.py:94-96` declares only `model` for an 8-column table.
- `modules\clients.py:207-214` is the richest (6 filters) yet still omits
  columns like `channel`, `vlan`, `rx_bytes`, `os`-vs-`user` coverage gaps.

So "universal" is currently false by construction: filters are an opt-in
curated list, not derived from columns.

### 1.3 Filter values flow as a flat dict, and the server mostly ignores them
`routes\modules.py:91` builds the filter dict and threads it into every
`FetcherContext`:

```python
filters = request.args.to_dict()                      # modules.py:91 (flat, last-wins)
ctx = FetcherContext(connection=conn, config=...,     # modules.py:95-97
                     filters=filters, ...)
```

The same `request.args.to_dict()` pattern repeats for drill
(`modules.py:140-144`) and drill-tab (`modules.py:171-175`). Two consequences:

1. **`to_dict()` collapses repeated query params** (`?status=online&status=flagged`
   keeps only the last). Multi-select is impossible without changing this.
2. **Almost no fetcher consumes `ctx.filters`.** The only server-side use is the
   AP zone filter: `modules\aps.py:76-81` (`_filter_body`) maps `zone` →
   `{"type":"ZONE_ID","value":…}`, mirrored by
   `clients\smartzone.py:648-670` (`smartzone_query_body`). Every other declared
   filter — including `aps` `status` — is **not** applied server-side. The
   `switches`, `ports`, and `clients` fetchers ignore `ctx.filters` entirely
   (`switches.py:20-29`, `ports.py:19-23`, `clients.py:29-35`).

Net: declared filters are *effectively client-side only* except AP→zone.

### 1.4 The client-side filter engine is global-substring + exact-match, build-once
`static\dashboard.js:179-193` (`_applyFilters`):

```js
if (key === "__search") {                       // dashboard.js:184-186
  const hay = Object.values(row).map(...).join(" ").toLowerCase();
  if (!hay.includes(String(val).toLowerCase())) return false;
} else if (String(row[key] ?? "") !== String(val)) {   // dashboard.js:187
  return false;                                  // exact string equality only
}
```

- **Only one free-text search box per module is possible.** `renderFilters`
  hard-codes `data-filter-key="__search"` for *every* `kind === "search"` filter
  (`dashboard.js:373-375`), and `__search` always means "match across all
  fields." Two search filters would collide on the same key and both behave
  globally — there is no per-column text search.
- **Select options are derived from the currently loaded rows**
  (`dashboard.js:379`: `Array.from(new Set(items.map(i => i[f.key])…))`), and the
  control set is **built once per page** (`dashboard.js:370`:
  `if (host.dataset.built === slug) return;`). After the first poll the option
  list never refreshes, so values that appear later (a zone that comes online,
  a new SSID) never get an option.
- Non-search filters are **exact equality** — no numeric ranges (`channel ≥ 36`),
  no "contains" on names, no case-insensitivity.
- KPI quick-filters write directly into the same `activeFilters[slug]` map with
  exact-match values (`dashboard.js:201-247`, e.g. `band:"5 GHz"`,
  `severity:"critical"`). Any redesign must keep these working.

### 1.5 Drill tables have no filters at all
Drill sections render through `renderGenericTable` (`dashboard.js:436-454`) and
`renderKeyVals` (`dashboard.js:405-417`). Neither consults `activeFilters` nor
emits any control. Switch **ports** (`switches.py:46-73`, tab at
`switches.py:198`) and **connected switches** (`switches.py:114-127`) can be long
tables with no way to filter. The drill payload is fetched whole and cached
(`dashboard.js:547-572`), so any drill filtering would naturally be client-side.

### 1.6 Security constraint that the design must preserve
All cell/option output is injected via `innerHTML`, so every controller-sourced
string is HTML-escaped through `_escape` (`dashboard.js:398-402`); the option
builder already escapes both attribute and text (`dashboard.js:380`). A
regression test enforces this (`tests\integration\test_dashboard_js.py:60-71`).
**Any new control-rendering code must route through `_escape`.**

---

## 2. Design goals & non-goals

**Goals**
- Every column is filterable by default, with the right control type inferred
  from `Column.kind` (status/enumerable → select; text → per-column search;
  number → numeric range/compare).
- One declaration site: filters derive from columns; modules can override.
- Keep server-side push-down where the controller supports it (AP/client zone
  today; extensible), client-side everywhere else.
- Drill sub-tables filterable client-side.
- Preserve KPI quick-filters, XSS escaping, and existing tests.

**Non-goals**
- No new SmartZone server-side filter endpoints beyond what the API already
  supports (`ZONE_ID` today; the spec defines the *extension seam*, not new
  upstream queries).
- No saved/shareable filter URLs in v1 (listed as an open question).
- No pagination redesign (current caps: 2000 table rows `dashboard.js:350`, 600
  cards `dashboard.js:317`, 500 generic-table rows `dashboard.js:446`).

---

## 3. Approaches considered

### Approach A — Derive filters from columns, filter client-side (with a server push-down seam)
Stop hand-declaring filters. The frontend (and `/api/modules`) treat **every
column as filterable**, choosing the control from `Column.kind`. All filtering
happens client-side in an upgraded `_applyFilters`, **except** a small, explicit
allow-list of columns that map to a server-side filter (zone today), declared on
the `Column` itself. Modules can suppress/override per column.

- **Pros:** Truly universal with near-zero per-module work; one source of truth
  (columns); minimal server change; instant filtering on already-fetched rows;
  drill tables get the same engine for free.
- **Cons:** Client filters the full polled dataset (fine within current row
  caps); free-text becomes per-column (good) which changes the single global
  search box; large fabrics still fetch all rows (already true today).

### Approach B — Server-side filtering for all columns
Push every filter into the fetcher / SmartZone `/query/*` body and re-fetch on
each filter change.

- **Pros:** Scales past client row caps; consistent counts across controllers.
- **Cons:** SmartZone `/query/*` only supports a narrow filter grammar
  (`smartzone.py:648-670` shows just `ZONE_ID`); most columns (model, fw, ip,
  os, band, quality, derived `signal_db`/`quality`) are **computed in
  `_normalize`** (e.g. `aps.py:84-106`, `clients.py:143-171`) and have **no
  upstream field to filter on**. Switch/ports come from a single inventory call
  (`switchm.fetch_switches`) with no server filter at all. Would require
  per-field, per-platform translation tables and a re-fetch on every keystroke
  (defeats the 20–60s poll cadence). High effort, partial coverage, worse UX.

### Approach C — Hybrid registry: keep explicit `Filter` tuples but auto-fill the gaps
Keep `ModuleSpec.filters`, but at registration auto-append a derived `Filter`
for any column lacking one, inferring `kind` from `Column.kind`.

- **Pros:** Backward compatible; explicit filters still win; smaller diff than
  rewriting declarations.
- **Cons:** Two parallel concepts (columns + filters) persist and can drift;
  the merge/order rules add complexity; still need the client-engine upgrade
  from A anyway. It is A's client work plus extra reconciliation logic.

---

## 4. Recommendation

**Adopt Approach A**, with a thin slice of C's compatibility: derive the filter
set from columns, infer control type from `Column.kind`, keep an **optional**
per-column override on `Column`, and retain a declarative **server push-down**
hint so the existing AP/client zone filter (and future ones) still execute
upstream. This delivers genuine universality with the smallest, most coherent
change, keeps server load flat, and reuses the existing client render path that
tests already pin.

Rationale: the data the user filters on is overwhelmingly **derived in
`_normalize`** and already present in the polled payload, so client-side is both
correct and instant; server push-down is reserved for the few keys the
controller can actually filter (zone), declared in one place.

---

## 5. Detailed design of the recommended approach

### 5.1 Data model changes (`modules\_base.py`)

Extend `Column` with optional, backward-compatible filter metadata, and extend
`Filter` so a derived or explicit filter can describe its control fully. No
existing positional args change.

```python
# _base.py — illustrative signatures only (no behavior in this spec)
@dataclass(frozen=True)
class Column:
    label: str
    key: str
    kind: str = "text"
    filterable: bool = True          # set False to suppress (e.g. raw blobs)
    filter_kind: str | None = None   # override inferred control: select|search|range|none
    server_filter: str | None = None # push-down token, e.g. "ZONE_ID"; None = client-only

@dataclass(frozen=True)
class Filter:                         # now the *resolved* control descriptor
    key: str
    label: str
    kind: str = "select"             # select | search | range
    server_filter: str | None = None
```

**Control inference** (single helper, e.g. `_base.resolve_filters(columns, overrides)`):

| `Column.kind`            | Inferred control      |
|--------------------------|-----------------------|
| `status`                 | `select`              |
| `text`, `link`           | `search` (per-column) |
| `number`, `bytes`, `rate`, `uptime` | `range` (min/max) |

- A module's existing `ModuleSpec.filters` tuple becomes an **override list**:
  entries matching a column `key` win; entries with no matching column are kept
  as-is (covers synthetic filters like `clients` `quality`/`band`, which *are*
  columns here, and any future non-column filter).
- `filterable=False` or `filter_kind="none"` removes a column from the filter
  bar (e.g. a future opaque `raw`/JSON column).
- The resolved, ordered filter list is what `/api/modules` serializes.

**Why on `Column`, not a new tuple:** keeps one source of truth, so adding a
column automatically yields a filter; avoids the column/filter drift that
Approach C institutionalizes.

### 5.2 Registration / resolution

In `modules\__init__.py:register()` (`__init__.py:7-11`) or in
`ModuleSpec.__post_init__` (`_base.py:62-74`), compute a resolved
`spec.resolved_filters` from `columns` + `filters` overrides via the helper
above. `all_modules()` ordering is unchanged. This keeps every module file
mostly untouched: the four reviewed modules (`aps`, `switches`, `ports`,
`clients`) can **drop or shrink** their hand `filters=(…)` tuples and rely on
column derivation; they only keep overrides for server push-down (`zone →
ZONE_ID`) and for renaming/suppression.

### 5.3 API surface (`routes\modules.py`)

**`GET /api/modules` (`modules.py:50-64`):** change line `:59` to serialize the
**resolved** filter list, adding `server_filter` and (for selects) optionally a
small `options` array when the server can enumerate values cheaply (usually
omitted — options come from data client-side). Shape:

```jsonc
"filters": [
  {"key":"zone","label":"Zone","kind":"select","server_filter":"ZONE_ID"},
  {"key":"name","label":"Name","kind":"search"},
  {"key":"clients","label":"Clients","kind":"range"}
]
```

**`GET /api/modules/<slug>` (`modules.py:67-120`):** the filter intake must stop
discarding repeated params. Replace `request.args.to_dict()` (`modules.py:91`,
and identically `:140`, `:171`) with a small parser that:
- keeps multi-valued select filters as lists (`request.args.getlist`), and
- packs range filters as `key__min` / `key__max` (or a `{min,max}` sub-dict).

A single helper `_parse_filters(request.args, spec.resolved_filters) -> dict`
centralizes this for list, drill, and drill-tab so the three call sites stay
consistent. `FetcherContext.filters` stays a `dict` (`_base.py:17`); only its
*value shapes* grow (str | list[str] | {min,max}).

### 5.4 Server-side push-down (kept narrow, extensible)

`FetcherContext.filters` already reaches every fetcher. The only behavioral
server change is to **generalize the existing zone push-down** so it is driven by
`server_filter` tokens instead of a hard-coded `zone` check:

- `clients\smartzone.py:smartzone_query_body` (`smartzone.py:648-670`) gains a
  mapping step: for each resolved filter with a `server_filter` token whose value
  is present, append `{"type": token, "value": v}` to `body["filters"]`. Today
  that yields exactly the current `ZONE_ID` behavior; tomorrow a module can opt a
  column in by setting `Column.server_filter="..."` **only if** the SmartZone
  `/query/*` grammar supports that field.
- `modules\aps.py:_filter_body` (`aps.py:76-81`) is folded into the same helper.
- **Everything not carrying a `server_filter` token is filtered client-side.**
  No fetcher is forced to understand new filters; unknown keys are simply ignored
  server-side and applied in the browser. This preserves the
  "one controller failure never 500s the page" contract (`modules.py:98-111`).

Counts: server-side push-down shrinks the payload (e.g. zone-scoped AP query),
and the client then applies the remaining column filters on what arrived.

### 5.5 Client engine (`static\dashboard.js`)

Upgrade three functions; keep all currently-tested symbol names
(`renderFilters`, `renderColumns`, `renderData`, `_applyFilters`, `_escape`,
`KPI_FILTER_MAP`, `applyKpiFilter`) so
`tests\integration\test_dashboard_js.py` keeps passing.

**(a) `_applyFilters` (`dashboard.js:179-193`)** — make it filter-kind aware:
- `select`: support **array** values (multi-select) — row passes if
  `row[key]` ∈ selected set; empty set = no constraint. Preserve exact-match
  semantics so KPI quick-filters (`band:"5 GHz"`) keep working (a scalar value
  is treated as a one-element set).
- `search` **per column** (new key scheme `search:<colKey>`): case-insensitive
  substring on `String(row[colKey])` only — not the whole row.
- `range` (key scheme `range:<colKey>`): numeric `min`/`max` compare with
  `Number(row[colKey])`; non-numeric rows fail a set range.
- Retain a single optional global box under the reserved `__search` key for
  "search all columns" (back-comp with current behavior and the KPI map).

**(b) `renderFilters` (`dashboard.js:365-396`)** — render from the **resolved
filter list** (`spec.filters`) instead of the sparse one, emitting per `kind`:
- `select` → `<select multiple>`-or-single from `Array.from(new Set(items…))`
  (keep `dashboard.js:379-380` escaping). **Fix the build-once staleness**:
  rebuild option lists on each render (or diff) so newly-arrived values appear;
  keep control identity stable so focus/selection is preserved (rebuild
  `<option>`s, not the whole `<select>`). Track via a per-control signature
  rather than the blunt `host.dataset.built === slug` gate (`dashboard.js:370`).
- `search` → `<input type="search" data-filter-key="search:<key>">` (distinct
  key per column — resolves the §1.4 single-search-box limitation).
- `range` → two `<input type="number">` (`…__min`,`…__max`) or a compact popover;
  `data-filter-key="range:<key>"`.
- A **"Clear filters"** affordance resets `activeFilters[slug]`.
- Because columns can be many, render the bar as a compact, horizontally
  scrollable/overflow row or a per-column filter affordance in the table header
  (see §5.6); the control *set* is still driven by the resolved list.

**(c) `applyKpiFilter` (`dashboard.js:228-247`)** — unchanged semantics; it
still writes scalar exact-match values into `activeFilters[slug]`. Ensure the
"reflect into visible controls" loop (`dashboard.js:242-245`) understands the new
key schemes (`select` keys are unprefixed, matching today).

**(d) `renderData`/`renderColumns`/`renderGrid`** — no change to row caps; both
already call `_applyFilters` (`dashboard.js:305`, `:337`).

### 5.6 UI placement (column-aligned filters)

Two presentations are compatible with this design; recommend **(i)** for "every
column" clarity:

- **(i) Header-row filter cells:** under each `<th>` in `renderColumns`
  (`dashboard.js:334-363`), render the column's control. This visually ties each
  filter to its column and scales to wide tables. Grid view
  (`dashboard.js:302-332`) and drill tables fall back to the compact bar.
- **(ii) Compact filter bar** in `[data-filters]` (`module.html:18-20`): the
  existing host, upgraded to render the full resolved set with overflow scroll.

Either way the data source and engine are identical; placement is a render
detail in `renderFilters`/`renderColumns`.

### 5.7 Drill tables (`dashboard.js` drill path)

- `renderGenericTable` (`dashboard.js:436-454`) gains an **optional** per-column
  header-search/select using the **same** `_applyFilters`-style helper, scoped to
  a drill-local filter state (e.g. `activeFilters["<slug>:drill:<tab>"]`) so it
  does not collide with list filters. Columns there are dynamic (union of row
  keys, `dashboard.js:441-444`), so all controls infer from value type
  (string→search, number→range) — no `Column` metadata is available for drill.
- Filtering stays **client-side** on the already-cached drill payload
  (`dashboard.js:547-572`); no new endpoints. Drill filters reset when the entity
  or tab changes (`root.dataset.drillBuilt` guard, `dashboard.js:529`).

### 5.8 Data flow (end to end)

```
Column metadata (filterable/kind/server_filter)              _base.py
        │  resolve_filters(columns, overrides)
        ▼
ModuleSpec.resolved_filters ──serialize──► GET /api/modules  modules.py:50-64
        │                                          │
        ▼                                          ▼
dashboard.js loadModuleSpecs() ◄───────────── moduleSpecs[slug].filters
        │
   renderFilters → activeFilters[slug] (select:list | search:<k> | range:<k>)
        │                                   ▲
        │ user edits control                │ KPI quick-filter (applyKpiFilter)
        ▼                                    │
   change/input handler                      │
        ├── server_filter token? ──► add &<key>=… to GET /api/modules/<slug>
        │                              │  modules.py:91 _parse_filters
        │                              ▼
        │                       FetcherContext.filters (str|list|{min,max})
        │                              │
        │                              ▼ (zone push-down only)
        │                       smartzone_query_body → /query/* body.filters
        │                              │
        ▼                              ▼
   _applyFilters(client)  ◄────── merged rows (payload.data.items)
        │
   renderColumns / renderGrid (capped)        dashboard.js:334 / :302
```

### 5.9 Error handling & edge cases
- **Unknown/unsupported filter keys**: ignored server-side (no 4xx), applied (or
  dropped) client-side — preserves the never-500 contract (`modules.py:98-111`).
- **Range on non-numeric / null**: row excluded from a *set* range, included when
  range empty; mirror `formatCell` null handling (`dashboard.js:68`).
- **Multi-value `select`**: empty selection = "All" (no filter); avoids the
  `to_dict()` last-wins bug by using `getlist` server-side.
- **Stale options**: fixed by rebuilding option sets per render (§5.5b).
- **XSS**: all option text/attrs and any header-cell control labels MUST pass
  through `_escape` (`dashboard.js:398-402`); keep the asserts in
  `test_dashboard_js.py:60-71` green.
- **Per-column search collision** (the current `__search` hard-code,
  `dashboard.js:373-375`) is resolved by the `search:<key>` scheme; the global
  box remains available under `__search`.
- **Drill filter isolation**: namespaced state key prevents bleed into list
  filters; reset on entity/tab switch.

### 5.10 Files & functions that change

| File | Change |
|------|--------|
| `RUCKUS\ruckus_dashboard\modules\_base.py` | Add `Column.filterable/filter_kind/server_filter`; extend `Filter` with `server_filter`; add `resolve_filters()` helper + control inference; optionally compute `resolved_filters` in `__post_init__`. |
| `RUCKUS\ruckus_dashboard\modules\__init__.py` | If not in `__post_init__`, resolve filters in `register()` (`:7-11`). |
| `RUCKUS\ruckus_dashboard\routes\modules.py` | Serialize resolved filters at `:59`; replace `request.args.to_dict()` at `:91`, `:140`, `:171` with `_parse_filters()` (multi/range aware). |
| `RUCKUS\ruckus_dashboard\clients\smartzone.py` | Generalize `smartzone_query_body` (`:648-670`) to map any `server_filter` token to `body["filters"]`; keep `ZONE_ID` behavior. |
| `RUCKUS\ruckus_dashboard\modules\aps.py` | Fold `_filter_body` (`:76-81`) into the token-driven push-down; mark `zone` column `server_filter="ZONE_ID"`; trim hand `filters=(…)`. |
| `RUCKUS\ruckus_dashboard\modules\switches.py`, `ports.py`, `clients.py` | Trim/override hand `filters=(…)`; rely on column derivation; keep `clients` band/quality/zone overrides. |
| `RUCKUS\ruckus_dashboard\static\dashboard.js` | Upgrade `_applyFilters` (`:179-193`), `renderFilters` (`:365-396`), key schemes; add per-column drill filtering in `renderGenericTable` (`:436-454`); keep symbol names. |
| `RUCKUS\ruckus_dashboard\templates\module.html` | Optional: header-cell filter layout vs. bar (`:18-26`); no contract change. |

### 5.11 Testing
Unit (pytest):
- `tests\unit\modules\test_base.py` — `resolve_filters`: status→select, text→search,
  number→range; `filterable=False`/`filter_kind="none"` suppresses; explicit
  override wins over derived; `server_filter` preserved.
- `tests\unit\modules\test_columns.py` — extend the existing contract
  (`:14-37`): every column yields a resolved filter unless suppressed; resolved
  filter kinds ∈ {select,search,range}.
- `tests\unit\clients\test_smartzone_query_body.py` — extend (`:29-36`): a
  generic `server_filter` token maps into `body["filters"]`; absent value omits
  it; multiple tokens accumulate; `ZONE_ID` still works.
- New `routes/modules` test — `_parse_filters` keeps repeated select params as a
  list (regression for the `to_dict()` last-wins bug, `modules.py:91`) and parses
  `key__min/max`.
Integration (`tests\integration\test_dashboard_js.py`):
- Keep existing symbol/escape asserts (`:39-47`, `:60-71`).
- Add asserts for new behavior: `search:` / `range:` key handling present;
  multi-select handling in `_applyFilters`; option-list rebuild (no permanent
  `dataset.built` short-circuit); drill table filter helper present.
JS behavior tests run today purely as **source-symbol assertions** (the suite has
no DOM harness). If true behavioral coverage is desired, that needs a jsdom/node
harness — flagged as an open question.

### 5.12 Rollout / compatibility
- Backward compatible: modules that keep their `filters=(…)` tuples still work;
  derivation only *adds* missing controls.
- Behind no flag by default, but can ride the existing `RUCKUS_ENABLE_NEW_UI`
  gate if a staged rollout is preferred.
- Performance: client-side filtering operates on already-polled rows within the
  current caps (2000 table / 600 grid / 500 drill); no extra network calls except
  when a `server_filter` value changes.

---

## 6. Open questions for the user
1. **Control density:** header-row filter cells under every `<th>` (§5.6 (i)) vs.
   a compact overflow bar (§5.6 (ii))? Header cells match "every column" best but
   widen tables.
2. **Numeric columns:** is a min/max **range** the right control for `clients`,
   `ports_up`, `poe_pct`, `channel`, `vlan`, or do you prefer equality/select
   buckets (e.g. channel bands)?
3. **Multi-select selects:** OK to switch single-select to multi-select (changes
   `?status=` to allow repeats and requires the `getlist` intake fix)?
4. **Server push-down scope:** beyond `ZONE_ID`, are there SmartZone `/query/*`
   filter fields you want pushed upstream (e.g. status), or keep everything
   client-side except zone?
5. **Drill filtering depth:** per-column controls on drill sub-tables (ports,
   connected switches) in v1, or defer drill to v2?
6. **Saved/shareable filters:** encode active filters in the URL/querystring for
   bookmarking and reload-persistence — in scope for v1?
7. **JS test harness:** acceptable to keep source-symbol assertions, or invest in
   a jsdom/node harness for real behavioral tests of `_applyFilters`?
8. **Suppression defaults:** any columns that should be non-filterable out of the
   box (e.g. `mac`/`serial` free-text, raw JSON-ish columns)?
