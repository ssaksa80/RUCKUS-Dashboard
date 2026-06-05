# RUCKUS Dashboard — DSO Expansion Design

**Date:** 2026-06-05
**Status:** Approved
**Audience:** Digital Services Operations (DSO) wall display + operator console
**Source file:** `RUCKUS/ruckus_dashboard.py` (single-file, 5076 lines, v1.0.0)

## Goal

Surface all 1354 discovered controller API operations (1116 SmartZone + 238 Switch Manager) in a coherent, modular dashboard, replacing the current 4-card single-page view. Read-only. Live snapshots only (no time-series persistence).

## Decisions (locked during brainstorm)

| Question | Decision |
|---|---|
| Scope | Surface everything (all 14+ API categories) |
| Navigation | Hub + drill-in (Overview = DSO wall, click tile → full module) |
| Side nav | Sidebar groups by domain (Wireless / Switching / Cross-cutting) |
| Actions | Read-only (no reboot/config/ack) |
| History | Live snapshots only (no DB, no time-series) |
| Phasing | Single big P1 ship: wireless core + full switching + cross-cutting. P2 reserved for advanced/nice-to-have (rogues map, sparklines, advisory feed, R1 timeline). |
| Code shape | Convert single file → installable package, single-file shim preserved |
| Audience | DSO room = Digital Services Operations (service-health language) |

## 1 — Package architecture

Convert `ruckus_dashboard.py` (5076 lines) → installable package `ruckus_dashboard/`. Top-level `ruckus_dashboard.py` shim re-exports `main` so `python ruckus_dashboard.py` continues to work.

```
ruckus_dashboard/
├── __init__.py           # version, public exports
├── __main__.py           # python -m ruckus_dashboard → main()
├── app.py                # create_app(), routes registration
├── cli.py                # argparse, main(), launcher (cert, port scan, browser)
├── config.py             # build_config, env parsers
├── certs.py              # self-signed cert
├── logging_setup.py      # JSON log formatter, configure_logging
│
├── auth/
│   ├── session_store.py  # ConnectionStore, ConnectionConfig
│   ├── secrets.py        # SecretsManager (Fernet + DPAPI)
│   ├── profiles.py       # ProfileStore
│   └── csrf.py
│
├── clients/              # API client layer — pure data, no Flask
│   ├── base.py           # _request_json, RuckusClientError, paging, allowlist
│   ├── smartzone.py
│   ├── switchm.py        # NEW (currently inlined)
│   ├── ruckus_one.py
│   └── capabilities.py   # OpenAPI discovery
│
├── modules/              # ONE FILE PER DASHBOARD MODULE
│   ├── _base.py          # ModuleSpec dataclass + registry
│   ├── overview.py       # DSO hub: KPIs + tiles
│   ├── zones.py
│   ├── access_points.py
│   ├── wlans.py
│   ├── clients.py
│   ├── alarms.py
│   ├── controller.py
│   ├── switches.py
│   ├── switch_groups.py
│   ├── ports.py
│   ├── traffic.py
│   ├── poe.py
│   ├── stack.py
│   ├── vlans.py
│   ├── firmware.py
│   ├── rogues.py
│   └── api_explorer.py
│
├── security/
│   └── validator.py      # CISA KEV + NVD
│
├── net/
│   ├── allowlist.py      # HostAllowList (SSRF)
│   └── port_scan.py
│
├── templates/
│   ├── base.html         # shell, header, sidebar
│   ├── overview.html     # DSO hub
│   ├── module.html       # generic module page
│   └── partials/         # kpi_card, status_pill, freshness_strip, etc.
│
└── static/
    ├── styles.css
    ├── dashboard.js      # hash router, polling loop, visibility hook
    ├── modules/          # per-module JS where needed
    └── assets/ruckus-logo.png

tests/
├── clients/              # one file per client
├── modules/              # one file per module
├── auth/
├── security/
├── fixtures/smartzone/   # sanitized real-controller response JSONs
└── smoke/test_launch.py
```

### ModuleSpec contract

```python
@dataclass(frozen=True)
class ModuleSpec:
    slug: str                                          # "aps", "wlans", ...
    title: str                                         # sidebar label
    group: str                                         # "Wireless" | "Switching" | "Cross-cutting"
    icon: str                                          # emoji or svg id
    poll_seconds: int                                  # client refresh cadence
    fetcher: Callable[[ConnectionConfig, dict, dict | None], dict]
                                                       # (conn, config, filters) -> normalized dict
    drill_fetcher: Callable | None
    drill_tabs: tuple[TabSpec, ...]
    summary_fn: Callable[[dict], dict]                 # extracts hub KPIs
    requires_platforms: tuple[str, ...]                # ("smartzone",) | ("smartzone","ruckus_one")
    requires_capabilities: tuple[tuple[str, str], ...] # ((method, path), ...)
    supports_views: tuple[str, ...]                    # ("table","grid","heatmap","chart","tree")
```

Registry `MODULES: dict[str, ModuleSpec]` in `modules/__init__.py`. App scans registry at startup → registers `/<slug>` and `/<slug>/<id>` routes + sidebar entries automatically. New module = add file + register. Zero plumbing changes.

## 2 — Module catalog (18 modules: 8 wireless + 7 switching + 3 cross-cutting)

### Wireless domain

| Slug | Title | Source ops | Key fetchers |
|---|---|---|---|
| `overview` | DSO Overview | aggregates others | none of its own |
| `zones` | Zones | 220 | `GET /rkszones`, `GET /rkszones/{id}`, `GET /rkszones/{id}/apgroups`, `GET /rkszones/{id}/wlans`, `GET /rkszones/{id}/apFirmware` |
| `aps` | Access Points | 175 | `POST /query/ap`, `GET /aps/{mac}/operational/summary`, `GET /aps/{mac}/operational/wlan`, `GET /aps/{mac}/operational/client/totalCount` |
| `wlans` | WLANs | 53 | `POST /query/wlan`, `GET /rkszones/{id}/wlans/{wlanId}` |
| `clients` | Wireless Clients | 42 | `POST /query/client` |
| `alarms` | Alarms & Events | 16 | `POST /alert/alarmSummary`, `POST /query/alarm`, `POST /query/event`, `POST /alert/eventSummary` |
| `rogues` | Rogues | subset Other Wireless | `POST /query/roguesInfoList` |
| `controller` | Controller | 51 | `GET /cluster/state`, `GET /system/devicesSummary`, `GET /system/inventory`, `GET /licensesSummary` |

### Switching domain

| Slug | Title | Source ops | Key fetchers |
|---|---|---|---|
| `switches` | Switches | 36 | `POST /switch/view/details`, `GET /switch/{id}`, `POST /health/cpu/agg`, `POST /health/mem/agg` |
| `switch-groups` | Switch Groups | 33 | switch-manager group endpoints |
| `ports` | Ports | 26 | `POST /switch/ports/summary`, `POST /switch/ports/details` |
| `traffic` | Traffic | 15 | `POST /traffic/top/usage`, `POST /traffic/top/portusage`, `POST /traffic/top/poeutilization` |
| `poe` | PoE | slice of switches | `POST /traffic/top/poeutilization`, `POST /switch/ports/details` |
| `stack` | Stack | subset switches | `GET /stack/{switchId}` |
| `vlans` | VLANs | 8 | switch-manager VLAN endpoints |

### Cross-cutting

| Slug | Title | Source ops | Notes |
|---|---|---|---|
| `firmware` | Firmware | existing | Per-zone catalog, per-AP/switch posture, compliance % |
| `security` | Security | existing | KEV/CVE timeline, advisory links, patch action queue |
| `api-explorer` | API Explorer | live OpenAPI | Searchable browser over **all 1354 ops** (both SmartZone 1116 + Switch Manager 238). Filter by source (wireless/switch), tag (Zones, APs, WLANs, Switches, Groups, Ports, Traffic, Firmware, VLANs, Other Wireless, Other Switch, …), method, and "tested in this dashboard" flag. GET-only fetch-sample button executes the op against the live controller and pretty-prints the response. **This is how the 98 "Other Switch" + 533 "Other Wireless" long-tail ops are surfaced** — without forcing a dedicated curated page per op. |

### Per-module drill-in tabs (typical)

`Summary` · `<entity-specific>` · `Alarms` (scoped) · `Raw` (debug-only JSON dump).

- AP drill: Summary, Radios (2.4/5/6 GHz), Clients, Neighbors, Alarms, Raw
- Switch drill: Summary, Ports (matrix), VLANs, MAC table, LLDP, PoE, Health, Raw
- WLAN drill: Summary, Auth/Encryption, RADIUS, Top Clients, AP Coverage, Raw
- Client drill: Summary, Roams, Signal trend (live only), Apps (if visible), Raw
- Zone drill: APs, WLANs, AP Groups, Firmware Catalog, WIPS, Raw

## 3 — Data flow & polling

### Polling cadence (defaults, env-overridable `RUCKUS_POLL_<SLUG>`)

| Module(s) | Cadence | Why |
|---|---|---|
| Overview KPIs | 15 s | DSO wall pulse |
| Alarms / Events | 10 s | Fastest signal needed |
| Wireless Clients | 20 s | High churn, heavy payload |
| Access Points, Ports, Traffic | 30 s | Status changes slow |
| WLANs, Zones, Switches, PoE, Stack, VLANs | 60 s | Config-shaped |
| Switch Groups, Controller, Firmware | 120 s | Mostly static |
| Security, API Explorer | 600 s | Cache-friendly |

Polling pauses on `document.hidden` (tab not visible).

### Fetch funnel

```
Browser polls /api/modules/<slug>?filters=...
        │
        ▼
Flask route → ModuleSpec lookup
        │
        ▼
For each session connection:
   ConnectionStore.get(cid) → ConnectionConfig
   ModuleSpec.fetcher(conn, app.config, filters)
        │  (uses clients/smartzone.py or clients/switchm.py)
        │  (paged GET / POST /query/*, capped page count, timeout)
        ▼
merge_<slug>(results_from_each_controller)
        │
        ▼
JSON: { status, data, summary, generated_at, controller_errors, stale_since }
```

### Caching layer

`ModuleResultCache` — in-memory, per-`(connection_set, module, filters)`, TTL = `poll_seconds / 2`. Multi-monitor DSO wall hitting same module collapses to one upstream call within window.

### Capability gating

`/api/inventory` returns the discovered capability set on initial load. Sidebar entries whose `requires_capabilities` are absent render **disabled** with tooltip "not supported on this controller version". Eliminates 404 noise.

### Error envelope (uniform across all modules)

```json
{
  "status": "complete" | "partial" | "error",
  "data": {...},
  "summary": {...},
  "generated_at": "2026-06-05T14:23:09Z",
  "controller_errors": [
    {"connection": "SZ-DXB-01", "endpoint": "POST /query/ap", "message": "...", "status": 502}
  ],
  "stale_since": "2026-06-05T14:22:09Z"
}
```

`partial` = at least one controller responded, at least one didn't. UI shows yellow "PARTIAL" pill with errors listed in panel head. Fixes today's hard-fail when one of two controllers is sick.

### Backpressure

- `RUCKUS_MAX_INFLIGHT_PER_MODULE = 1` per `connection_set`: duplicate concurrent fetches join the in-flight one.
- 502/503/timeout → client back-off: 15 → 30 → 60 → 120 s, reset on success. Banner after 3 consecutive failures.
- 401 anywhere → session-wide reauth flag, all pollers pause, banner with "Reconnect".

### Client-side state (no framework)

Hash router: `#/aps`, `#/aps/AB:CD:...`. `dashboard.js` state:
- `currentModule` — drives which `/api/modules/<slug>` poller is active
- `controllerCaps` — capability set from `/api/inventory`
- `moduleState[slug]` — `{ lastResponse, lastPoll, errorCount, filters }`
- Visibility API hook pauses/resumes pollers

## 4 — Per-module page template

One shared `module.html`. Differences live in config + data, not layout.

### Default layout

```
┌─ topbar (breadcrumb · refresh badge · DSO wall toggle) ─┐
│                                                         │
│ ┌── summary strip (4-6 KPI tiles) ──────────────────┐   │
│ └────────────────────────────────────────────────────┘   │
│                                                         │
│ ┌── filter chips row ───────────────────────────────┐   │
│ └────────────────────────────────────────────────────┘   │
│                                                         │
│ ┌── view toggles (table | grid | heatmap | chart) ──┐   │
│ └────────────────────────────────────────────────────┘   │
│ ┌── data area (table by default) ───────────────────┐   │
│ │   click row → drill-in /<slug>/<id>               │   │
│ └────────────────────────────────────────────────────┘   │
│                                                         │
│ ┌── freshness footer (controllers ok · last refresh)┐   │
│ └────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Drill-in layout

```
┌─ topbar ─┐
│ ┌── hero card: identity (name, MAC/serial, status, uptime, zone) ─┐│
│ ┌── 8-tile micro-KPI grid ─────────────────────────────────────────┐│
│ ┌── tabs (Summary · entity-specific · Alarms · Raw) ───────────────┐│
│ └ active tab content ──────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

### View toggles per module

| View | Modules | Renders |
|---|---|---|
| Table | all | Sort, paginate, filter, CSV export |
| Grid | APs, Switches, WLANs | Card per entity, status colour band |
| Heatmap | Ports, PoE | Switch × port matrix coloured by metric |
| Chart | Traffic, PoE | Top-N bar/donut (no time series) |
| Tree | Zones, Switch Groups, VLANs | Parent/child nesting |

### DSO wall mode

`⛶ DSO` toggle (was "TV mode") → hides sidebar, topbar, filters; auto-rotates between modules user has bookmarked (`localStorage` list); larger KPI fonts. Reuses existing `body.display-mode` styles.

### Empty / loading / error states

- **Loading**: skeleton rows (3-5), KPI tiles show "…", no spinner.
- **Empty (filtered)**: "No results for current filters" + clear-filters button.
- **Empty (capability missing)**: full-panel "This controller version doesn't expose `<endpoint>`. Module disabled."
- **Error**: red banner above table, retain last good data with `stale-since` stamp. Never blank table on transient failure.

### Reusable partials (`templates/partials/`)

`kpi_card.html`, `status_pill.html`, `entity_link.html`, `freshness_strip.html`, `error_banner.html`, `table_pagination.html`, `filter_chip.html`.

### DSO ergonomics

- KPI numbers `aria-live="polite"` so changes announce.
- Status pills: colour + text + icon (not colour alone).
- Keyboard: `/` focus search, `[`/`]` cycle modules, `Esc` exit drill-in.
- No animation on data update — operators report motion fatigue on 24/7 walls.

### Service-health rollup (Overview only)

`summary_fn` of all modules contributes to a composite **WiFi Service Health** score on Overview:
- AP availability % (online / total)
- Auth success rate (last 15 min from event stream)
- Client RSSI distribution (% in "good" band ≥ -65 dBm)
- Alarm-impact weighting (critical = -10, major = -3 per active)

Rendered as a single 0-100 score + traffic-light pill. Reframes raw counts in service-health language for Digital Services Ops audience.

## 5 — Testing

### Unit (~80%)

- `tests/clients/` — one per client. `responses` library mocks HTTP. Cover: paging exhaust, 401 token expiry, 5xx retry, malformed JSON, allowlist denial, redacted password in error path.
- `tests/modules/` — one per `ModuleSpec`. Canned fetcher output → assert `summary_fn` shape, drill-fetcher contract, capability gating.
- `tests/security/` — KEV match, NVD parse, status escalation, cache TTL.
- `tests/auth/` — `ConnectionStore` TTL, `SecretsManager` round-trip, DPAPI wrap/unwrap (skipped non-Windows), `ProfileStore` save/load/delete, CSRF reject.

### Integration (~15%)

- Auth flow: connect → `/api/modules/aps` returns data → logout invalidates.
- Multi-controller merge: two mocked, one partial → `status: "partial"` + both errors surfaced.
- Capability gating: missing endpoint → 200 + `disabled: true`, not 500.
- Token expiry mid-poll → 401 + `reauth: true`.
- CSRF: POST without token → 400.
- Security headers: HSTS, X-Frame-Options, nosniff on every response.

### Contract fixtures

`tests/fixtures/smartzone/` and `tests/fixtures/switchm/` — sanitized real-controller response JSONs, captured once from lab, committed. Each client test loads fixture → asserts normalized shape. Catches upstream API drift between SmartZone / Switch Manager versions. Switch Manager fixtures cover at minimum the 7 curated module fetchers plus 5-10 representative "Other Switch" ops (MAC table, LLDP, STP state, 802.1X status, syslog config) so the API Explorer fetch-sample is exercised in tests too.

### Smoke (~5%)

`tests/smoke/test_launch.py`:
- App boots empty config, `/healthz` returns 200.
- Self-signed cert generated when missing.
- Port auto-scan finds free port when default busy.
- Clean Ctrl+C exit (regression for 2.0.2).

### Manual verify

`/verify` skill per phase against live lab controller. Checklist: connect → all phase modules load; disconnect mid-load → graceful banner; disable one controller → partial mode shows; filter/paginate/drill-in/back-button work; DSO wall mode rotates modules.

### CI

GitHub Actions matrix Windows + Linux × Python 3.10/3.11/3.12. Steps: install, ruff lint, mypy strict on `clients/` + `modules/` (lenient on templates), pytest with ≥75% coverage gate.

## 6 — Phase 1 scope (single big ship — everything except advanced features)

**Goal:** full DSO dashboard. All wireless modules + all curated switching modules + cross-cutting + API Explorer covering the 1354-op long tail. Only "nice-to-have" features deferred.

### Build end-to-end — 17 of 18 modules

**Foundation**
- Package refactor (Section 1) — full conversion
- Auth/secrets/profiles — ported to `auth/` package
- Module registry + shared `module.html` + drill-in template
- Sidebar with all 18 entries (only **Rogues** marked "Coming in Phase 2")
- Routes + capability gating + caching layer
- Error envelope across all responses
- Polling cadence env overrides
- DSO wall mode + module-rotation list (localStorage)
- Backward-compat: `python ruckus_dashboard.py` still works
- Tests per Section 5

**Wireless modules**
- **Overview** with service-health rollup
- **Zones** + drill-in
- **Access Points** + drill-in
- **WLANs** + drill-in
- **Wireless Clients** + drill-in
- **Alarms & Events**
- **Controller**

**Switching modules (curated)**
- **Switches** + drill-in (drill tabs: Summary · Ports matrix · VLANs · MAC table · LLDP · PoE · Health · Raw)
- **Switch Groups** + drill-in (tree view)
- **Ports** (table + per-switch port-matrix heatmap view)
- **Traffic** (Top-N panels: top switches, top ports, top WLANs, top clients)
- **PoE** (per-switch budget/allocated/available; per-port class/draw/faults)
- **Stack** (table: stack ID, members, master/standby, port state, FW alignment)
- **VLANs** (table: VLAN ID, name, member switches, port count, tagged/untagged)

**Cross-cutting**
- **Firmware** (port existing — extend to switch FW posture)
- **Security** (port existing — KEV/CVE per device)
- **API Explorer** — surfaces **all 1354 ops** including the 98 "Other Switch" + 533 "Other Wireless" long-tail. Replaces today's "Controller API Surface" card. (see Section 2 for filter detail)

### Long-tail switch coverage strategy

The 7 curated switching modules cover the high-signal day-1 operator needs (real-time health, status, traffic, PoE budget, VLANs, stack). The remaining ~98 "Other Switch" ops (ACLs, QoS, STP, syslog, SNMP config, multicast, DHCP snooping, 802.1X status, AAA config, …) are not modelled as dedicated pages — instead:

1. **Discoverable** in API Explorer with switch source filter.
2. **Drillable**: each curated module's drill-in **Raw** tab exposes underlying op responses for debug.
3. **Future-promotable**: any "Other Switch" op that becomes operationally important gets promoted to a new `modules/<slug>.py` file later — zero plumbing change.

This keeps day-1 scope finite while guaranteeing no API endpoint is invisible.

### Deferred to Phase 2

- **Rogues** module (`POST /query/roguesInfoList` is built into clients; just no dedicated UI yet)
- Rogues map overlay (rogue density per zone, geographic)
- Per-AP signal sparklines (requires live ring buffer in browser memory)
- Advisory feed widget (RUCKUS vendor advisories beyond KEV/CVE)
- RUCKUS One activity timeline
- Promotion of any "Other Switch" op to dedicated module based on operator demand

### Sizing

~12-15 K lines new/moved. Estimated **7-10 day focused build** for a single dev. Plan will decompose into independently-shippable subtasks: foundation/refactor, then modules in parallel by domain (wireless, switching, cross-cutting), then integration + DSO wall polish.

## Risks & open items

| Risk | Mitigation |
|---|---|
| Single-file deploy property lost | Top-level `ruckus_dashboard.py` shim re-exports `main`; `pip install -e .` works; users see no regression. |
| 1354 ops × 2 controllers × frequent polling overwhelms controller | `ModuleResultCache` collapse, capability gating, env-tunable cadence, in-flight dedupe, exponential back-off. |
| API shape drift between SmartZone versions | Fixture-based contract tests in `tests/fixtures/smartzone/`. |
| Sidebar grows beyond 18 if controller exposes more categories | API Explorer covers everything not modelled; new categories added by dropping a `modules/<slug>.py` file. |
| 7-10 day single-ship build is risky for delivery | Plan decomposes into independently shippable subtasks per domain; foundation lands first as PR1, modules merge incrementally behind a feature flag (`RUCKUS_ENABLE_NEW_UI=1`) until full set ships. |
| Switch Manager API differs across switch FW versions | Capability discovery gates per-module endpoints; fixture-based contract tests in `tests/fixtures/switchm/` for each touched op. |
| Service-health score formula misleading | Weights documented in `overview.py`, env-overridable, exposed in `/api/health/explain` for transparency. |
| DSO wall fatigue from frequent updates | No motion on update; aria-live polite only; cadence configurable; user-pickable rotation set. |

## Out of scope

- Write actions (reboot, config push, alarm ack)
- Time-series persistence (SQLite, Prometheus, InfluxDB)
- Multi-tenant RBAC (single shared session today)
- Mobile/responsive layout (DSO wall = 1840 px+)
- Internationalization (English only)
- AI/LLM summaries of alarms

## Next step

Hand off to `superpowers:writing-plans` to produce a phased implementation plan for Phase 1.
