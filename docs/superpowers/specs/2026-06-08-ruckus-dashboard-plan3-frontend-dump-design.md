# RUCKUS Dashboard Plan 3 — Frontend Depth + Data Dump

**Date:** 2026-06-08
**Status:** Approved
**Builds on:** Plan 1 + Plan 2 (all 18 modules real, live-validated against SmartZone 7.1.1).

## Goal

Make the dashboard genuinely usable: replace the raw key-value tables with friendly columns, working filters, and clickable drill-in detail pages — for firmware, the 8 wireless modules, and switches (whose detail view is currently missing). Add a one-command data dump that captures everything the dashboard collects into a single JSON file for offline debugging and future enhancement.

## Decisions (locked during brainstorm)

| Question | Decision |
|---|---|
| Dump command | CLI flag `--dump` → one timestamped JSON file (headless, no server) |
| Frontend depth | Full: friendly tables + filters + drill-in tabs |
| Rich views (heatmap/charts/tree) | Deferred to a later pass; tables + drill now |
| Decomposition | 3 plans: 3a dump, 3b frontend core, 3c drill-in |

## 1 — Data dump command

New module `ruckus_dashboard/dump.py`, exposed via `python -m ruckus_dashboard --dump`.

`run_dump(connection, config) -> dict`:
1. `discover_capabilities(connection, config)` → `available_ops` + op count + OpenAPI source summary.
2. For each module in `MODULES`: build `FetcherContext`, run `fetcher(ctx)`, capture `{status, summary, item_count, items, error}`. Catch `RuckusClientError`/`Exception` → `status:"error"`, `error: message` (with raw upstream body).
3. For each drillable module (`drill_fetcher` is not None) with at least one item: run `drill_fetcher(ctx, first_item_id)` → `sample_drill: {entity_id, data}`.
4. Redact secrets (auth tokens, passwords) everywhere via existing `_redact`.

Output JSON:
```json
{
  "dumped_at": "2026-06-08T...Z",
  "app_version": "...",
  "controller": {"platform": "smartzone", "version": "7.1.1.0.872", "api_base": "..."},
  "capabilities": {"op_count": 1116, "available_ops": [["GET","/aps"], ...]},
  "modules": {
    "switches": {
      "status": "complete",
      "summary": {...},
      "item_count": 12,
      "items": [...],
      "sample_drill": {"entity_id": "...", "data": {...}},
      "error": null
    },
    ...
  }
}
```

CLI:
- `--dump` triggers dump mode (no Flask server started).
- Credentials: `--smartzone-host`, `--smartzone-user`, `--smartzone-pass`, `--smartzone-api-version` (default auto), `--smartzone-skip-tls-verify`; OR `--platform ruckus_one` with `--tenant-id`/`--client-id`/`--client-secret`/`--region`. If creds absent, read from `RUCKUS/.env`.
- `--dump-file PATH` overrides default `ruckus-dump-<UTCstamp>.json` (written to CWD).
- On success prints the path + per-module status line. Exit 0; exit 1 on connect failure.

Secrets never written to the dump (redacted). This file is the artifact the operator sends for enhancement/fixes.

## 2 — Switches detail fix

Two gaps cause "cannot see switches details":
1. `dashboard.js` never makes rows clickable / never navigates to drill.
2. `switches.fetch_drill` is a stub returning only `{"identity": {"id": entity_id}}`.

Fix:
- **Real switch drill** `switches.py::fetch_drill(ctx, switch_id)`: query Switch Manager for the switch detail + its ports (`switch/ports/summary` for that switch) + health (`health/cpu/agg`, `health/mem/agg` where available). Return `{identity, ports, health, raw}`. Each sub-call wrapped in try/except so one failure doesn't blank the page.
- Drill tabs: `Summary` · `Ports` · `Health` · `Raw`.

## 3 — Generic drill-in (all modules)

`module.html` already renders with `data-entity` when on `/m/<slug>/<entity_id>`.

JS:
- `renderModule` branches: `data-entity` present → `renderDrill`; else → list render.
- `renderDrill` builds a tab bar from the module's `drill_tabs` (exposed in `/api/modules`), shows a hero identity card, and per-tab content.
- Tab content fetched from `/api/modules/<slug>/<entity_id>` (summary/raw) and `/api/modules/<slug>/<entity_id>/<tab_slug>` for entity-specific tabs.

Routes:
- `GET /api/modules/<slug>/<entity_id>` exists (Plan 2b).
- Add `GET /api/modules/<slug>/<entity_id>/<tab_slug>` → looks up `module.drill_tabs[tab].fetcher`; if the tab has no fetcher, falls back to the main drill data filtered to that tab's key. 401/404/502 handling mirrors `module_drill`.

Row-click: list render wraps each row in a link to `/m/<slug>/<row.id>`. Every module's normalized items already carry an `id`.

## 4 — Friendly tables + column maps

New lightweight types in `modules/_base.py`:
```python
@dataclass(frozen=True)
class Column:
    label: str
    key: str
    kind: str = "text"     # text | status | bytes | uptime | number | link

@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    kind: str = "select"   # select | search
```
`ModuleSpec` gains optional `columns: tuple[Column, ...] = ()` and `filters: tuple[Filter, ...] = ()`.

`/api/modules` list endpoint serializes `columns` + `filters` so the client renders labeled headers, colored status pills, and humanized `bytes`/`uptime` cells. Modules with no `columns` fall back to raw-key rendering (keeps any future stub working).

Modules getting `columns` + `filters` this pass: firmware, switches, and the 8 wireless (overview is tile-only so skipped), plus the cheap switching siblings (ports, traffic, poe, stack, vlans, switch-groups) get `columns`. Rich views (heatmap/charts/tree) deferred.

## 5 — Filters

`data-filters` placeholder in `module.html`. JS renders a chip/dropdown per declared `Filter`. Options for `select` filters come from distinct values in the current result set. Changing a filter re-fetches `/api/modules/<slug>?<key>=<value>`. Fetchers already accept `zone`/`page`/`limit`; per-module `_build_query`/normalization extended where a new filter key needs upstream translation (else client-side filter on the returned items).

## 6 — Testing

- `dump.py`: unit test with a mocked connection asserts JSON shape (modules keys, redaction, error capture for a failing module).
- `--dump` CLI: integration test against mocked SmartZone asserts file written + valid JSON + exit 0.
- `switches.fetch_drill`: `responses`-mocked tests for detail + ports + health, plus graceful partial when one sub-call 4xxs.
- `ModuleSpec.columns`/`filters` + `Column`/`Filter` contract tests; each module with `columns` asserts every `Column.key` exists in a normalized item.
- New tab route: 401 unauth, 404 unknown module/tab, 200 envelope.
- JS served-asset symbol checks: `renderDrill`, `renderColumns`, `renderFilters`, row link markup, humanize helpers.

CI matrix unchanged. Coverage gate ≥75%.

## 7 — Decomposition

- **Plan 3a — Data dump**: `dump.py` + `--dump` CLI + tests. Ships first; its output guides 3b/3c.
- **Plan 3b — Frontend depth core**: `Column`/`Filter` types, `ModuleSpec.columns`/`filters`, `/api/modules` serialization, JS friendly-table + filter render + row-click, `columns`/`filters` for firmware + wireless + switching modules.
- **Plan 3c — Drill-in**: tab route, generic `renderDrill` + tab bar JS, real `switches.fetch_drill`, drill fetchers/tabs for firmware + wireless + switches.

## 8 — Out of scope

- Rich visualizations (ports heatmap, PoE budget bars, traffic Top-N charts, zones/groups tree)
- Pagination beyond page 1 (separate follow-up)
- Production WSGI swap
- RUCKUS One live validation
- Profiles UI, multi-controller add-mode, rogues geo-map, sparklines

## Next step

`superpowers:writing-plans` → Plan 3a first; 3b/3c follow each prior ship.
