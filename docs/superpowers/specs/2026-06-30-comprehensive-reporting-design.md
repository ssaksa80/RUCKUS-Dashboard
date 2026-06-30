# SP3+8 — Full-Coverage Reporting + Per-Tab Email — Design

Date: 2026-06-30
Status: Draft (design only — no implementation)
Scope: `ruckus_dashboard/reports/`, `ruckus_dashboard/notify/scheduler.py`,
`ruckus_dashboard/routes/notifications.py`, `ruckus_dashboard/modules/_base.py`,
frontend `static/dashboard.js` + templates.

---

## 1. Problem & Current Behavior (grounded in code)

### 1.1 The report sees 4 of 18 modules

`collect_report_data` hardcodes exactly four slugs and assumes every fetcher
returns an `items` list:

- `notify/scheduler.py:32-35` — the loop iterates a literal
  `(("aps","aps"),("clients","clients"),("alarms","alarms"),("switches","switches"))`
  and does `MODULES[slug].fetcher(ctx).get("items", [])`.

The other 14 registered modules (`modules/__init__.py:22-40`: zones, wlans,
rogues, controller, overview, switch_groups, ports, traffic, poe, stack,
vlans, firmware, security, api-explorer, topology) never run during a report.
Worse, two of the covered-by-design shapes do not even fit the `items`
contract:

- `topology.fetch` returns `{"nodes":[...], "edges":[...], "items":[]}`
  (`modules/topology.py:215-216`) — `.get("items")` yields `[]`.
- `overview.fetch` returns `{"items":[], "_overview":True}`
  (`modules/overview.py:13`) — intentionally empty; data arrives via warmup SSE.

### 1.2 The Excel writer is hand-coded per domain

`reports/excel.py:33-182` builds exactly six sheets (Overview, APs by Zone,
Clients, Alarms, Switches, Offline Devices). Every sheet hardcodes the field
keys it reads (e.g. `excel.py:117-119` reads `hostname,mac,ssid,ap,rx_bytes,
tx_bytes` for top-talkers; `excel.py:155-156` reads switch keys). There is no
use of the rich metadata each module already declares:

- `ModuleSpec.columns: tuple[Column,...]` — label + key + kind
  (`modules/_base.py:59`, e.g. `modules/aps.py:124-134`).
- `ModuleSpec.summary_fn` — per-module KPI dict (`modules/aps.py:46-53`).
- `ModuleSpec.drill_tabs` + `drill_fetcher` — per-entity detail and raw field
  maps (`modules/clients.py:58-82` returns `identity/connection/usage/raw`).
- `clients.fetch` already returns `raw_rows: rows[:2]` (`modules/clients.py:35`)
  — a pre-normalized field-map sample that no report consumes.

So the report cannot satisfy SP3's goal ("list + summary + drill samples + raw
field maps for all 18 modules") without either (a) hand-writing 14 more sheets
or (b) driving generation from the registry.

### 1.3 Filters are client-side; the server never sees them

SP8 says the per-tab email must "respect active filters from SP1." But:

- The browser holds filter state in `activeFilters[slug]` and applies it
  **after** fetch via `_applyFilters` (`static/dashboard.js:179-193`).
- The data fetch URL carries **no** query string —
  `static/dashboard.js:106-108` builds `/api/modules/<slug>` with nothing
  appended.
- Server-side, `routes/modules.py:91` does read `request.args.to_dict()` into
  `ctx.filters`, but **most fetchers ignore it**. Only `aps._filter_body`
  (`modules/aps.py:76-81`, ZONE_ID only), `api_explorer._apply_filters`
  (`modules/api_explorer.py:89-105`), and `topology` (`expand`) consult
  filters. There is no generic server-side row filter equivalent to the JS
  `_applyFilters`.

Consequence: an email endpoint that simply re-runs a fetcher will **not**
reproduce what the operator sees on screen. The filter set must be transported
to the server and applied generically (mirroring the JS predicate), because the
fetchers themselves won't honor arbitrary `key=value` filters.

### 1.4 The existing email-now path inherits all of the above

`routes/notifications.py:85-113` (`/api/reports/test`) and `:116-136`
(`/api/reports/generate`) both call `collect_report_data` + `build_report`, so
they share the 4-module blind spot. There is no per-tab endpoint at all today.

### 1.5 Capability gating is bypassed by reports

`collect_report_data` constructs `CapabilityGate(set())`
(`notify/scheduler.py:29`) — an **empty** gate. The HTTP path gates each module
on `spec.requires_capabilities` before running (`routes/modules.py:82-89`), but
the report path does not, so a generic enumerator must decide explicitly which
modules to attempt against the live `available_ops`.

---

## 2. Goals / Non-Goals

**Goals**
- Report covers all 18 modules generically from the registry: per-module list
  (column-projected), summary KPIs, a small drill sample, and a raw field-map
  sample.
- `collect_report_data` enumerates `MODULES` instead of a hardcoded 4.
- A per-tab "Email this report" button + endpoint that emails the **current
  tab only**, honoring the operator's active filters.
- Reuse `ModuleSpec` metadata (columns/summary/drill_tabs) — no per-module
  report code.

**Non-Goals**
- Changing the alert path (`evaluate`/`state_from_data`) — out of scope.
- Fixing the known scheduler/security issues (redirect SSRF, baseline spam,
  durable dedup) — tracked separately; this design must not regress them.
- A report-builder UI / column-picker. Fixed projection from existing specs.
- Historical/time-series reporting. Snapshot only, as today.

---

## 3. Approaches (2–3, with trade-offs)

### Approach A — Generic registry-driven report (one sheet per module) + reuse summary_fn/columns

A single generic engine walks `all_modules()`, runs each fetcher under the live
capability gate, and emits a uniform per-module sheet: a summary block (from
`summary_fn`), a column-projected list (from `spec.columns`), and a raw
field-map sample. Drill samples come from `drill_fetcher` on the first N
entities. The existing curated sheets (charts) are kept as a small "highlights"
front section for the four core domains; everything else is generic.

- **Pros:** Scales to all 18 (and any future module) with zero per-module code.
  Uses metadata that already exists and is already unit-tested
  (`tests/unit/modules/test_columns.py`). Naturally produces "list + summary +
  drill + raw" per SP3. Per-tab email becomes "render one module's sheet."
- **Cons:** Generic sheets are less visually curated than the hand-built charts.
  Running 18 fetchers (some heavy: clients pages, topology pulls clients+alarms)
  is slower than 4 — needs bounded concurrency + per-module timeouts and
  drill-sample caps. Non-`items` shapes (topology graph) need a typed adapter.

### Approach B — Extend the hand-coded writer with 14 more bespoke sheets

Keep `build_report`'s style; add a function per remaining module.

- **Pros:** Maximum visual control per domain; keeps the charts idiom.
- **Cons:** ~14 new hand-maintained sheet writers, each re-encoding field keys
  that already live in `Column` specs — exactly the duplication that bit
  `excel.py` today. Drifts whenever a module's normalize keys change. Per-tab
  email still needs a generic "render this one" path, so you build the generic
  engine anyway. High effort, high maintenance, contradicts SP3's "generic
  enumeration" ask. **Rejected.**

### Approach C — Two-layer: generic JSON "report model" + thin renderers (Excel now, others later)

Introduce a pure `collect_report_model(connection, config, gate, slugs,
filters)` that returns a typed, serializable model (per-module: summary,
columns, projected rows, drill samples, raw samples, errors). Excel becomes one
renderer over that model; the per-tab endpoint reuses the same model for a
single slug. Future CSV/PDF/HTML renderers attach to the same model.

- **Pros:** Clean separation (collection vs rendering) makes both unit-testable
  without openpyxl or SMTP. Per-tab and full-report share one collector. Models
  are trivially filterable (apply the generic predicate to `rows` in-model).
  Easiest to test the "covers 18 modules" guarantee (assert on the model, not
  on a binary xlsx). Sets up SP-future formats cheaply.
- **Cons:** One extra abstraction layer (the model dataclasses) vs Approach A's
  fetch→write. Slightly more upfront design.

---

## 4. Recommendation

**Adopt Approach C (generic report model) and render Approach A's layout from
it.** C and A are complementary: C is the data layer, A is the Excel layer.
Rationale grounded in what the code already gives us:

1. The registry already carries everything the report needs
   (`columns`, `summary_fn`, `drill_fetcher`, `drill_tabs`) — a model that
   harvests these eliminates per-module report code (kills the `excel.py`
   duplication and the hardcoded 4-slug loop).
2. A typed model lets us **test the SP3 coverage guarantee directly** ("every
   slug in `all_modules()` appears in the model with summary+rows+raw") without
   parsing xlsx bytes — which the current suite cannot do.
3. The per-tab endpoint (SP8) and the full report (SP3) become the **same
   collector** invoked with one slug vs all slugs, so filters and capability
   gating behave identically in both.
4. Filters are applied **in the model** by a single generic predicate that
   mirrors `dashboard.js:_applyFilters`, solving §1.3 without touching 18
   fetchers.

Keep the four curated chart sheets as an optional "Highlights" section layered
on top of the generic per-module sheets, so we lose no existing visual value.

---

## 5. Design of the Recommended Approach

### 5.1 Component overview & data flow

```
                         ┌─────────────────────────────────────────┐
  GET/POST report  ─────▶│ collect_report_model(conn, cfg, gate,    │
  (scheduler / route)    │   slugs, filters_by_slug) -> ReportModel │
                         └───────────────┬─────────────────────────┘
                                         │ per slug (bounded pool)
                          ┌──────────────▼───────────────┐
                          │ _collect_module(spec, ctx,    │
                          │   filters) -> ModuleReport     │
                          │  • run fetcher (timeout)       │
                          │  • adapt shape -> rows         │
                          │  • apply generic filter pred.  │
                          │  • summary_fn(merged)          │
                          │  • drill sample (N entities)   │
                          │  • raw field-map sample        │
                          └──────────────┬─────────────────┘
                                         │ ReportModel (typed, JSON-able)
              ┌──────────────────────────┼───────────────────────────┐
              ▼                          ▼                           ▼
   reports/excel.py            routes (per-tab JSON              future CSV/
   build_report(model)         preview / download)               PDF renderers
        │
        ▼
   xlsx bytes ──▶ mailer.send_email(..., attachment=xlsx)
```

### 5.2 New module: `reports/model.py` (pure, no openpyxl / no Flask)

Typed dataclasses (illustrative signatures only):

```python
@dataclass(frozen=True)
class ColumnSpec:        # mirror of modules._base.Column, decoupled
    label: str; key: str; kind: str

@dataclass
class DrillSample:
    entity_id: str
    sections: dict[str, Any]     # e.g. {"identity":..., "raw":...}
    error: str | None = None

@dataclass
class ModuleReport:
    slug: str; title: str; group: str
    status: str                  # "ok" | "disabled" | "error"
    columns: list[ColumnSpec]
    summary: dict[str, Any]      # from spec.summary_fn
    rows: list[dict[str, Any]]   # column-projected, post-filter
    row_total: int               # pre-filter count (raw_count)
    raw_samples: list[dict]      # unnormalized upstream rows (field map)
    drill_samples: list[DrillSample]
    filters_applied: dict[str, str]
    errors: list[dict]           # controller errors, str-safe
    note: str | None = None      # e.g. "no list (graph module)"

@dataclass
class ReportModel:
    generated_at: str
    connection_label: str
    modules: list[ModuleReport]
    def by_slug(self, slug) -> ModuleReport | None: ...
```

The model is JSON-serializable so the per-tab endpoint can return it directly
for an in-browser preview if desired, and so tests assert on structure.

### 5.3 New module: `reports/collect.py`

Replaces the narrow `collect_report_data`. Key functions (signatures only):

```python
def collect_report_model(
    connection, config: dict, *,
    available_ops: set[tuple[str, str]],
    slugs: Iterable[str] | None = None,           # None => all_modules()
    filters_by_slug: dict[str, dict[str, str]] | None = None,
    drill_sample_size: int = 3,
    raw_sample_size: int = 2,
    per_module_timeout: float = 20.0,
    max_workers: int = 4,
) -> ReportModel: ...

def _collect_module(spec, ctx, *, drill_n, raw_n) -> ModuleReport: ...

def _rows_from_payload(spec, payload) -> tuple[list[dict], int, list[dict]]:
    """Adapt a fetcher payload to (rows, row_total, raw_samples)."""

def apply_filter(rows: list[dict], filters: dict[str, str]) -> list[dict]:
    """Generic predicate mirroring dashboard.js _applyFilters
       (exact-match per key; '__search' = substring over all values)."""

def project_columns(rows, columns) -> list[dict]:
    """Keep only spec.columns keys, preserving label order; passthrough id."""
```

**Shape adaptation (`_rows_from_payload`) — handles the real variants found in
§1.1:**

| Payload shape (observed)                                   | Rows / total / raw                                   |
|------------------------------------------------------------|------------------------------------------------------|
| `{"items":[...], "raw_count":N}` (aps, clients, ports, …)  | rows=items; total=raw_count or len; raw=`raw_rows` if present (`clients.py:35`) else first `raw_n` items |
| `{"items":[], "_overview":True}` (overview)                | rows=[]; note="overview tiles (warmup-driven), no list" |
| `{"nodes":[...], "edges":[...], "items":[]}` (topology)    | rows = node dicts; total=len(nodes); raw=first `raw_n` nodes; note="graph module" |
| `{"items": [...]}` with no raw_count                       | rows=items; total=len(items)                         |

The adapter is keyed off presence of `nodes`/`_overview` first, then `items`.
This isolates all shape knowledge in one tested function.

**Capability gating (fixes §1.5):** build a real
`CapabilityGate(available=available_ops)` and, per module, set
`status="disabled"` when `not gate.satisfied(spec.requires_capabilities)`
instead of running the fetcher. This mirrors `routes/modules.py:82-89` so the
report matches the dashboard's enabled/disabled view.

**Drill samples (SP3 "drill samples"):** for modules where
`spec.drill_fetcher is not None`, take the first `drill_n` post-filter rows that
have an `id`, call `drill_fetcher(ctx, id)`, and capture the returned section
dict. Each call is wrapped — a drill failure records `DrillSample.error` (the
str) and never aborts the module. Tab-specific fetchers (`TabSpec.fetcher`,
`modules/_base.py:26`) are honored when present, matching
`routes/modules.py:178`. Modules without drill (`drill_fetcher is None`, e.g.
topology, api-explorer, overview) simply yield `drill_samples=[]`.

**Concurrency & timeouts:** run modules through a `ThreadPoolExecutor`
(`max_workers=4`) with a per-`future.result(timeout=...)`. On timeout, emit a
`ModuleReport(status="error", note="timed out")` and move on. (Note: the
existing `ParallelFetcher` has the documented "`__exit__` waits on stragglers"
weakness — known issue (d); this collector uses `future.result(timeout=)`
directly so a slow module bounds its own slot rather than relying on pool
shutdown. We do not reuse `ParallelFetcher` here.)

**Error containment:** every fetcher/drill call is wrapped; `RuckusClientError`
and generic exceptions become `ModuleReport.errors` / `DrillSample.error`. The
collector never raises for a single module — consistent with
`scheduler.py:36-38` and `routes/modules.py:100-111`. Error strings are stored
str-safe; the renderer decides exposure (see §5.7 security).

### 5.4 Backward-compatibility shim for `collect_report_data`

`notify/scheduler.py` and `routes/notifications.py` import
`collect_report_data`. To avoid a breaking change and keep the **alert** path
(which needs `state_from_data`'s `{aps,clients,alarms,switches}` items)
working, keep a thin `collect_report_data(connection, config)` that:

- still returns the legacy `{"aps":[...], "clients":[...], "alarms":[...],
  "switches":[...]}` dict (so `state_from_data`, `scheduler.py:42-53`, is
  untouched), now implemented by pulling those four slugs' `rows` out of a
  `collect_report_model(..., slugs=("aps","clients","alarms","switches"))`
  call. This keeps alerts byte-for-byte equivalent while the report path moves
  to the model.

This isolates the change: **alerts keep their 4-domain state; reports gain all
18.**

### 5.5 `reports/excel.py` — render from the model

`build_report` gains a model-aware signature while preserving the old one for
the alert/legacy callers during transition:

```python
def build_report(data_or_model) -> bytes:
    """Accept either a ReportModel (new) or the legacy
       {'aps':..,'clients':..} dict (wrapped into a minimal model)."""
```

Workbook structure (Approach A layout over the model):

1. **Overview** — global KPI table (kept; derive from the four core
   `ModuleReport.summary` dicts so numbers match today's `excel.py:52-61`).
   Plus a **Coverage** block: one row per module (title, status, row_total,
   #errors) so a reader sees all 18 were attempted.
2. **Highlights (curated charts)** — the existing APs-by-Zone / Clients /
   Alarms / Switches chart sheets (`excel.py:68-158`), unchanged visually, fed
   from the model's core-module rows. Keeps the charts SP investment.
3. **Per-module sheets** — one sheet per module in `all_modules()` order
   (`modules/__init__.py` registers 18; `all_modules()` sorts by group/title,
   `modules/__init__.py:14-15`). Each sheet:
   - Title + status pill + "filters applied" line.
   - **Summary** block: key/value from `ModuleReport.summary`.
   - **List** table: header from `columns[*].label`, rows are projected values;
     `kind` drives light formatting (bytes/number/status) reusing the same
     idioms as `excel.py:_autofit`/headers.
   - **Raw field map**: the `raw_samples` rendered as key/value pairs (one
     block per sample) so operators see real upstream field names — satisfies
     SP3 "raw field maps."
   - **Drill samples**: for each `DrillSample`, a labeled block dumping its
     `sections` (flattened key→value). Satisfies SP3 "drill samples."
4. **Offline Devices** — kept (`excel.py:160-178`), now sourced from the model.

Sheet-name collisions/length (Excel ≤31 chars, no `:[]/\?*`) handled by a
`_safe_sheet_name(title, used:set)` helper (truncate + dedupe suffix).

### 5.6 Per-tab email — API + frontend (SP8)

**New endpoints in `routes/notifications.py`:**

```
POST /api/reports/tab        # email the current tab (xlsx of one module)
POST /api/reports/tab/preview  (optional) # return ReportModel JSON for one slug
```

`POST /api/reports/tab` request body (JSON):

```json
{ "slug": "clients",
  "filters": { "band": "5 GHz", "quality": "poor" },
  "recipients": ["noc@x"]            // optional; default report.recipients
}
```

Handler flow (mirrors existing `/api/reports/test`, `notifications.py:85-113`):
1. `session.get("auth")` else `_unauth()` (401).
2. `validate_csrf()` (POST mutation — consistent with `notifications.py:45`,
   `:58`).
3. Resolve connection from `session["connection_ids"]` via
   `connection_store.get` (the existing loop, `notifications.py:91-97`); 401 if
   expired.
4. Validate `slug` against `MODULES`; 404 if unknown. Validate `filters` is a
   flat `dict[str,str]`; drop unknown keys not in `spec.filters` keys (+ allow
   `__search`).
5. `model = collect_report_model(conn, dict(current_app.config),
   available_ops=current_app.available_ops, slugs=(slug,),
   filters_by_slug={slug: filters})`.
6. `xlsx = build_report(model)` (single-module workbook: Overview/coverage +
   that one module's sheet).
7. Recipients: use posted `recipients` if present **and** validated, else
   `cfg["report"]["recipients"]`. Empty → 400 (mailer also guards,
   `mailer.py:70-72`).
8. `send_email(... subject=f"[RUCKUS DSO] {spec.title} report {ts}",
   filename=f"ruckus-{slug}-{ts}.xlsx", attachment=xlsx)`.
9. Return `{"sent": True, "recipients": [...], "slug": slug,
   "rows": model.by_slug(slug).len, "filtered": bool(filters)}`; on failure
   `{"sent": False, "error": <safe>}` 502 (same idiom as `:112-113`).

**Filter transport (resolves §1.3):** the browser already owns
`activeFilters[slug]` (`dashboard.js:9,179`). The per-tab button reads it and
POSTs it as `filters`. No change to the data-fetch URL is required; we add a
dedicated POST. Optionally, also send the active **view** and `__search` so the
email reflects exactly what's rendered.

**Frontend (`static/dashboard.js` + a partial template):**
- Add an "Email this tab" button into the module toolbar (near the
  filters/view controls rendered around `dashboard.js:365-396`).
- On click: gather `slug`, `activeFilters[slug]` (skipping empty values, same
  rule as `_applyFilters`, `dashboard.js:183`), POST to `/api/reports/tab`
  with `X-CSRF-Token` (token already in the page via templates; the dashboard
  reads it like other CSRF posts). Show a toast with sent/again-error.
- A small confirm/recipient affordance: default to configured report
  recipients; allow a one-off override field (optional, can defer).

**Capability/disabled modules:** if `gate` reports the module disabled, the
endpoint returns `{"sent": False, "error": "module unavailable on this
controller"}` (422) so the button gives clear feedback rather than emailing an
empty sheet.

### 5.7 Error handling & security

- **Auth + CSRF** on every new mutation (matches `notifications.py:44-45`,
  `routes/modules.py:72`). The optional preview GET requires auth only.
- **Info-disclosure parity:** the model stores raw error strings, but the
  **Excel/JSON renderer must gate raw upstream error bodies behind
  `RUCKUS_SHOW_DEBUG`**, mirroring `routes/modules.py:_upstream_message`
  (`routes/modules.py:28-37`). By default sheets show a generic
  "fetch failed (HTTP 502)" line; full detail only when debug is on. This keeps
  us from regressing into the known drill-endpoint leak (issue (e)).
- **SSRF:** unchanged — all upstream calls still go through the existing
  clients (`clients/base.request_json` SSRF allowlist). No new outbound paths.
  (The redirect-SSRF known issue (a) is out of scope and not reintroduced.)
- **Raw-sample scrubbing:** raw field maps may include identifiers (MACs/IPs)
  but those are already shown in the dashboard; no secrets are in fetcher
  payloads. Cap `raw_sample_size` (default 2) and `drill_sample_size` (default
  3) to bound size and exposure.
- **Recipients validation:** trim + non-empty (mailer already enforces,
  `mailer.py:70-72`); reject obviously invalid input early with 400.
- **Resource bounds:** per-module timeout + `max_workers` cap stop a slow
  controller (e.g. clients pagination, `clients.py:31`) from hanging the
  scheduler tick (`scheduler.py:132-173` runs on the single daemon thread) or a
  request worker.

### 5.8 Files & functions that change

| File | Change |
|------|--------|
| `ruckus_dashboard/reports/model.py` | **New.** Dataclasses: `ColumnSpec`, `DrillSample`, `ModuleReport`, `ReportModel`. |
| `ruckus_dashboard/reports/collect.py` | **New.** `collect_report_model`, `_collect_module`, `_rows_from_payload`, `apply_filter`, `project_columns`. |
| `ruckus_dashboard/notify/scheduler.py` | `collect_report_data` → thin wrapper over `collect_report_model(slugs=core4)` returning legacy `{aps,clients,alarms,switches}`. Daily-report block (`:158-173`) builds the model (all 18) and passes it to `build_report`. `state_from_data` unchanged. |
| `ruckus_dashboard/reports/excel.py` | `build_report` accepts `ReportModel` (or legacy dict); add generic per-module sheets + Coverage block + `_safe_sheet_name`; keep curated chart sheets fed from the model. |
| `ruckus_dashboard/routes/notifications.py` | New `POST /api/reports/tab` (+ optional `/api/reports/tab/preview`). `/api/reports/test` & `/api/reports/generate` switch to `collect_report_model(slugs=None)` so manual/download reports also cover 18. |
| `ruckus_dashboard/static/dashboard.js` | "Email this tab" button; POST `activeFilters[slug]` with CSRF; toast feedback. |
| `ruckus_dashboard/templates/partials/*` | Button markup in the module toolbar; reuse existing CSRF token exposure. |
| `ruckus_dashboard/modules/_base.py` | No structural change required. *(Optional, deferred)* a `report: bool = True` flag on `ModuleSpec` to let a module opt out of the generic list (e.g. overview); default keeps all in. |

### 5.9 Testing

Unit (pure, no openpyxl/SMTP — `tests/unit/reports/`):
- `apply_filter`: exact-match per key, empty values ignored, `__search`
  substring over all values — assert parity with `dashboard.js:_applyFilters`
  cases (band/quality, search).
- `project_columns`: keeps only `spec.columns` keys + `id`; order preserved.
- `_rows_from_payload`: all four shapes in §5.3 table (items+raw_count,
  `_overview`, topology nodes/edges, items-only) → correct rows/total/raw.
- `collect_report_model` with a **fake registry / monkeypatched fetchers**:
  - **Coverage guarantee:** every slug in `all_modules()` yields a
    `ModuleReport` (status ok/disabled/error) — the SP3 invariant.
  - Disabled gating: a module whose `requires_capabilities` aren't in
    `available_ops` gets `status="disabled"` and is not fetched.
  - A fetcher that raises → `status="error"`, model still complete for others.
  - A slow fetcher → per-module timeout path (inject a sleeper; small timeout).
  - Drill sampling: `drill_fetcher` called for first N rows; a raising drill →
    `DrillSample.error` set, others still captured.

Renderer (`tests/unit/reports/test_excel.py`, extend existing style):
- `build_report(model)` returns bytes that **load in openpyxl**; assert a sheet
  exists per module title (via `_safe_sheet_name`) + Overview + Coverage.
- Legacy dict still renders (backward-compat path).
- Charts present on the four curated sheets (parity with current
  expectations).

Integration (`tests/integration/test_notifications_api.py`, extend):
- `POST /api/reports/tab` — 401 unauth; 403/400 missing CSRF; 404 unknown slug;
  200 happy path with `send_email` monkeypatched (assert subject/filename carry
  the slug; assert filters forwarded into the collector via a patched
  `collect_report_model`).
- Filter respect: post `filters={"band":"5 GHz"}`, patch the fetcher to return
  mixed bands, assert the model/sheet only contains 5 GHz rows.
- `/api/reports/test` & `/api/reports/generate` now exercise the 18-module
  collector (patch fetchers; assert no crash on topology/overview shapes —
  directly covers the §1.1 regression).
- Debug gating: with `RUCKUS_SHOW_DEBUG` off, a failing module's sheet shows the
  generic message, not the raw body (mirror of `routes/modules.py` test).

Frontend (`tests/integration/test_dashboard_js.py`, static-assert style used
today): assert the "Email this tab" handler posts to `/api/reports/tab` with a
CSRF header and includes `activeFilters` (string-presence checks, consistent
with the existing dashboard.js tests).

---

## 6. Open Questions

1. **Per-module sheet volume.** 18 modules + curated highlights + per-entity
   drill blocks could make a large workbook. Cap drill samples at 3 and raw at
   2 by default — acceptable, or do you want per-module overrides (e.g. more
   drill detail for aps/switches)?
2. **List row caps in the report.** The dashboard paginates upstream (clients
   can be thousands). Should per-module list sheets cap rows (e.g. 1,000 with a
   "+N more" note like topology's `+N more APs`, `topology.py:174-176`), or dump
   everything? A cap is strongly recommended for file size.
3. **Filter source of truth for the daily (unattended) report.** SP8's
   per-tab email is interactive (browser sends `activeFilters`). The **daily**
   report has no browser — should it be unfiltered (all rows), or should we
   persist a per-module "report filter" in `notifications.json` alongside
   `report`? Default proposal: daily = unfiltered; per-tab = live filters.
4. **Recipients for per-tab email.** Default to `report.recipients`, or always
   prompt for a one-off recipient in the UI? Proposal: default to configured,
   with an optional override field.
5. **Topology/graph representation in Excel.** Render topology as a node table
   (id/type/status/label/parent) — sufficient, or do you want an edge sheet too
   (source/target/status)? Proposal: node table + optional edge sheet behind a
   flag.
6. **Overview module.** It's intentionally empty server-side
   (`overview.py:13`, warmup-driven). Include it as a "(no standalone list —
   see KPIs)" placeholder sheet, or omit via an opt-out flag (`report=False`)?
7. **`collect_report_data` removal timeline.** Keep the legacy wrapper
   indefinitely for the alert path, or migrate `state_from_data` to consume a
   `ReportModel` too and delete the wrapper in a follow-up?
8. **Format scope.** This design renders Excel only (as today). The model
   supports CSV/PDF/HTML cheaply — is any non-Excel format in scope for this
   round, or strictly deferred?
