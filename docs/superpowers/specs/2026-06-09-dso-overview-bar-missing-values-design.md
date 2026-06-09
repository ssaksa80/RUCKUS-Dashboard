# DSO Overview Restructure + Missing-Value Fixes — Design

Date: 2026-06-09
Status: Approved

## Problem

Live run against SmartZone 7.1.1 surfaced two classes of issue from UI snapshots:

1. **Missing values** in several modules:
   - **Alarms**: severity KPI cards (Critical/Major/Minor/Warning/Total) read 0 even though list rows show `major` alarms. `alert/alarmSummary` returns zeros.
   - **Controller**: License/Nodes KPIs all 0, table "No results" — field keys don't match live cluster/license payloads.
   - **Traffic**: `TOP_SWITCH = null`, switch column "—", all bytes `0 B` — `traffic/top/*` row keys don't match.
   - **VLANs**: list now populates (500 VLANs, names + ids) but `MEMBER_SWITCH_COUNT`, `MEMBER_SWITCHES`, `TAGGED_PORTS`, `UNTAGGED_PORTS` all 0/"—" — member/port keys don't match.

2. **DSO Overview UX**:
   - `/m/overview` renders an empty data-table ("No results") because Overview is a tiles-only module with no list rows.
   - Overview should be the landing page, pinned at the top of navigation, and a compact health summary should stay visible while drilled into any resource.

## Goals

- DSO Overview is the landing route and first sidebar item.
- A slim, always-visible DSO health bar above every module page (chips with key counts; click → module; red when alarms/rogues > 0).
- `/m/overview` renders the tile grid, not an empty table.
- Populate Alarms KPIs, Controller, Traffic, and VLAN member/port columns with real data.
- No guessing of API field names — drive fixes from captured raw response shapes.

## Non-Goals (YAGNI this round)

- Charts / heatmaps / PoE bars / traffic graphs.
- Collapsible left rail (deferred; slim top bar chosen).
- Pagination UI beyond existing render cap.

## Approach

### A. Persistent DSO health bar
- New template partial `partials/health_bar.html` mounted **once in the shell** (not per-module) so it persists across resource navigation.
- `renderHealthBar()` in `dashboard.js` populates chips from the **already-cached warmup summaries** via the existing `/api/warmup/status` endpoint and refreshes on the existing warmup SSE stream. No new server fetching.
- Chips: APs, Clients, Alarms, Rogues, Switches, PoE, VLANs, Zones + a cluster status dot. Each chip links to `#/m/<slug>`. Alarms/Rogues chips get a `danger` class when count > 0.

### B. Overview as landing + nav top
- Sidebar: render "DSO Overview" as the first item.
- Router: empty/`#/` hash → overview tile grid (existing landing grid markup).
- `/m/overview`: detect the tiles-only module and render the tile grid instead of the table.

### C. Missing-value data fixes
- **Alarms**: replace `summary_fn` reliance on `alert/alarmSummary` with counts derived from the fetched list rows: group by normalized `severity`, summing `count`. Deterministic; no extra call.
- **Controller / Traffic / VLAN members**: extend the dump (`dump.py`) to capture a **raw upstream sample** per module — first response body, redacted and truncated — under `modules.<slug>.raw_sample`. One dump reveals real keys; then update `_normalize` mappings in `controller.py`, `traffic.py`, `vlans.py`. The raw-capture itself is a debugging tool, shipped first.

### D. Tests
- JS integration: health bar renders chips from a warmup-status payload; overview route renders tiles.
- `test_alarms`: summary derives from items.
- Updated module mocks for whatever field fixes land (controller/traffic/vlans) once shapes are known.

## Data Flow

```
warmup scheduler ──> ModuleResultCache ──> /api/warmup/status ──┬─> tile grid (landing + /m/overview)
                                            (SSE: /api/warmup)   └─> health bar (every page)

module page ──> /api/modules/<slug> ──> table/cards (unchanged)
```

## Risk / Rollback
- Health bar reads cache only → if warmup not done, chips show skeleton "…"; no errors.
- Field-fix changes are isolated to each module's `_normalize`; reverting one does not affect others.
- All gated behind the existing `RUCKUS_ENABLE_NEW_UI` flag.
