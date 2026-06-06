# RUCKUS Dashboard Plan 2 — Real Modules + Auto-Discovery + Bootstrap

**Date:** 2026-06-06
**Status:** Approved
**Builds on:** `2026-06-05-ruckus-dashboard-expansion-design.md` + Plan 1 foundation merged on `main`.
**Audience:** Digital Services Operations (DSO) room.

## Goal

Promote all 18 dashboard modules from stub to fully working: real fetchers, drill-ins, filters, multi-controller merge. After login, auto-discover controller capabilities and warm up every applicable module so the operator sees live data without clicking. Ship a single-command install + start script so deploying to another server is one `./scripts/install.sh` away.

## Decisions (locked during brainstorm)

| Question | Decision |
|---|---|
| Module scope | All 18: 8 Wireless + 7 Switching + 3 Cross-cutting |
| Auto-discovery UX | Async with progress strip (SSE); login redirects to Overview immediately |
| Bootstrap shape | `./scripts/install.sh` (interactive .env) + `./scripts/start.sh` (foreground daemonization to operator) — no systemd/NSSM by default |
| Decomposition | 4 sub-plans (2a/2b/2c/2d) under this single design spec |
| Multi-controller add mode | Deferred to Plan 3+ |
| Profile save UI | Deferred to Plan 3+ |
| Time-series persistence | Still out of scope (per Plan 1 spec) |
| Write actions | Still out of scope (read-only) |

## 1 — Architecture additions

Three new infra pieces on top of Plan 1 foundation:

### 1.1 `infra/warmup.py` — `WarmupScheduler`

Triggered by successful `POST /connect`. Spawns a daemon thread that:

1. Calls `discover_capabilities(connection, config)` → populates `app.available_ops` (already in capabilities client).
2. Iterates `MODULES` registry. For each module whose `requires_capabilities` is satisfied AND `requires_platforms` matches connected platform AND `warmup=True`, schedules its fetcher onto a `concurrent.futures.ThreadPoolExecutor` (default `max_workers=4`, env `RUCKUS_WARMUP_WORKERS`).
3. Each fetcher result lands in `app.module_cache` with TTL = `poll_seconds * 2` (first browser poll = cache hit).
4. Records per-module status (`pending` / `running` / `done` / `failed` / `disabled` / `timed_out`) on `app.warmup_state: dict[slug, WarmupStatus]`.

Per-task timeout: `RUCKUS_WARMUP_TIMEOUT` (default 30s). On timeout → status `timed_out`, no exception escalates.

Lifecycle: scheduler is per-session. Logout calls `scheduler.cancel()` which sets a shutdown event, executor stops accepting new tasks, in-flight tasks complete naturally.

### 1.2 `routes/warmup.py` — SSE + status endpoints

- `GET /api/warmup` — Server-Sent Events stream. Client opens once on Overview load. Each module completion pushes one event:

  ```
  event: module-ready
  data: {"slug":"aps","status":"done","summary":{"total":142,"online":140}}
  ```

  When all modules report terminal status, server pushes `event: complete` and closes.

- `GET /api/warmup/status` — synchronous snapshot (for SSE fallback). Returns `{"states": {slug: {...}, ...}, "complete": bool}`.

Both endpoints require auth (`session["auth"]`).

### 1.3 `static/dashboard.js` warmup integration

On Overview page load:
1. Render `templates/partials/warmup_strip.html` (progress bar at top).
2. Open `EventSource("/api/warmup")`.
3. On each `module-ready` event: update corresponding tile value, change tile state from `skeleton` → `ready` / `error` / `disabled`.
4. On `complete`: hide strip, close stream.
5. On `EventSource` error: fall back to polling `/api/warmup/status` every 2s until complete.

### 1.4 `infra/parallel_fetch.py` — `ParallelFetcher`

Reusable wrapper around `ThreadPoolExecutor` with timeout-per-task and result aggregation. Used by `WarmupScheduler` and by any drill-in page that needs to fetch multiple tabs in parallel.

### 1.5 `ModuleSpec` extensions

- `warmup: bool = True` — set `False` on modules too heavy to warm up (e.g. `api-explorer` which polls 1354 ops).
- `merge: Callable[[list[dict]], dict] | None = None` — per-module multi-controller merge. If `None`, default is concat-items behavior (current `routes/modules.py` logic).

## 2 — Per-module fetcher pattern

Every `modules/<slug>.py` follows this file shape:

```python
"""<title> module — <one-line purpose>."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_post, smartzone_paged_get
from ..infra.envelope import ControllerError

POLL_SECONDS = 30
ICON = "📶"


# ─── primary fetcher ────────────────────────────────────────────────────
def fetch(ctx: FetcherContext) -> dict[str, Any]:
    rows = smartzone_post(ctx.connection, "query/ap",
                          payload=_build_query(ctx.filters),
                          config=ctx.config, debug=[])
    items = [_normalize(row) for row in rows]
    return {"items": items, "raw_count": len(rows)}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    return {"total": len(items),
            "online": sum(1 for i in items if i.get("status") == "online"),
            "clients": sum(int(i.get("clients") or 0) for i in items)}


# ─── drill-in fetchers (one per tab) ────────────────────────────────────
def fetch_drill(ctx, entity_id):
    ap = smartzone_get(ctx.connection, f"aps/{entity_id}/operational/summary",
                       config=ctx.config, debug=[])
    return {"identity": _normalize(ap), "radios": ap.get("radios", [])}


def fetch_drill_clients(ctx, entity_id):
    return {"items": smartzone_post(ctx.connection,
                                    f"aps/{entity_id}/operational/client", ...)}


# ─── filter dialect ─────────────────────────────────────────────────────
def _build_query(filters):
    f = filters or {}
    payload = {"page": int(f.get("page", 0)),
               "limit": int(f.get("limit", 500))}
    if f.get("zone"):
        payload["filters"] = [{"type": "ZONE", "value": f["zone"]}]
    return payload


# ─── normalization (upstream → stable UI shape) ─────────────────────────
def _normalize(row):
    return {"id": row.get("apMac"),
            "name": row.get("deviceName") or "-",
            "model": row.get("model"),
            "zone": row.get("zoneName"),
            "status": _bucket_status(row.get("status")),
            "clients": row.get("numClients") or 0,
            "fw": row.get("firmwareVersion")}


# ─── multi-controller merge ─────────────────────────────────────────────
def merge(results):
    items, raw_count = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw_count += r.get("raw_count", 0)
    return {"items": items, "raw_count": raw_count}


# ─── registration ───────────────────────────────────────────────────────
register(ModuleSpec(
    slug="aps", title="Access Points", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="clients", title="Clients", fetcher=fetch_drill_clients),
        TabSpec(slug="alarms", title="Alarms"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone", "ruckus_one"),
    requires_capabilities=(("POST", "/query/ap"),),
    supports_views=("table", "grid"),
    warmup=True,
    merge=merge,
))
```

### Why this shape

- **Single file owns everything** for one module — fetchers, filters, normalization, merge, registration. One file per reviewer focus.
- **Each `TabSpec` carries its own fetcher**. Route `/m/<slug>/<id>/<tab>` looks up `module.drill_tabs[tab_slug].fetcher`. Adding a tab = adding a callable.
- **Normalization functions** convert messy SmartZone payloads into stable UI shape. Tests pin this contract.
- **Filter dialect** = query-string → upstream payload mapping. Owned per module.

### Required client refactor (Plan 2a)

Promote private `_smartzone_*` and `_switch_*` helpers to public (drop underscore prefix). Pure rename, no behavior change, but lets modules cleanly `from ..clients.smartzone import smartzone_post`. Same for `switchm`.

### Registry change

`modules/__init__.py` auto-imports siblings so they self-register:

```python
from . import (
    overview, zones, aps, wlans, clients, alarms, rogues, controller,
    switches, switch_groups, ports, traffic, poe, stack, vlans,
    firmware, security, api_explorer,
)
```

Existing `modules/_registry.py` (single file with 18 stubs) is deleted by Plan 2b.

### Routes update

`routes/modules.py::module_data` calls `spec.fetcher(ctx)` per connection, then `spec.merge(results)` if present. Currently does naive `items.extend` — replace with merge dispatch.

New routes:
- `GET /api/modules/<slug>/<entity_id>` — drill-in summary tab.
- `GET /api/modules/<slug>/<entity_id>/<tab_slug>` — specific tab.

## 3 — Bootstrap scripts

### 3.1 `scripts/install.sh` (Linux/macOS)

Idempotent. Re-runnable.

1. Detect `python3 --version`, accept 3.10/3.11/3.12/3.13.
2. Create `.venv/` if absent. Activate.
3. `pip install --quiet -e RUCKUS`.
4. If `RUCKUS/.env` missing: interactive prompts for bind host, port, allowed-hosts CSV (mandatory if non-loopback bind), new-UI flag, browser-open flag. Auto-generate `FLASK_SECRET_KEY` via `secrets.token_urlsafe(48)`. Write `RUCKUS/.env` with `chmod 600`.
5. Launch `python -m ruckus_dashboard` in foreground for first verify. Operator hits Ctrl+C when satisfied.

Non-interactive mode (CI): if `RUCKUS_INSTALL_NONINTERACTIVE=1` env present, read all answers from `RUCKUS_INSTALL_HOST`, `RUCKUS_INSTALL_PORT`, etc. instead of stdin.

### 3.2 `scripts/start.sh`

1. Source `RUCKUS/.env`.
2. Activate `.venv/`.
3. `exec python -m ruckus_dashboard --no-browser`.

Operator daemonizes via systemd / nohup / tmux as they prefer.

### 3.3 `scripts/install.ps1` + `scripts/start.ps1` (Windows)

Mirror behavior. ACL on `.env` restricts to current user (`icacls /inheritance:r /grant:r "$env:USERNAME:F"`).

### 3.4 Docs

- `README.md` — quickstart (clone → `./scripts/install.sh` → done).
- `docs/DEPLOY.md` — production deployment: systemd unit, NSSM service, nginx reverse-proxy sample, real-cert installation, upgrade flow.

## 4 — Sub-plan breakdown

### Plan 2a — Auto-discovery + Warmup infrastructure

**Goal:** wire WarmupScheduler + SSE + progress strip. All 18 modules still stubs but warmup state flows end-to-end. Promote private `_smartzone_*` / `_switch_*` helpers to public (rename pass).

**Build:**
- `infra/warmup.py`, `infra/parallel_fetch.py`
- `routes/warmup.py` (SSE + status endpoints)
- `routes/connect.py` mod (kick off warmup on login, cancel on logout)
- `static/dashboard.js` warmup integration
- `templates/partials/warmup_strip.html`, `tile_skeleton.html`
- `ModuleSpec.warmup` field
- `api-explorer` stub flipped to `warmup=False`
- Public renames of `clients/smartzone.py` and `clients/switchm.py` helpers (`_smartzone_post → smartzone_post`, etc.)
- Tests: WarmupScheduler unit, SSE stream integration, cancellation on logout

**Ship criterion:** Login → progress bar visible → all 18 stub modules report `done` within 5s → tiles show 0 counts → SSE closes cleanly.

**Size:** ~7 tasks, 1-2 days.

### Plan 2b — Wireless modules end-to-end

**Goal:** 8 wireless modules with real fetchers, drill-ins, filters.

**Modules:** `overview`, `zones`, `aps`, `wlans`, `clients`, `alarms`, `rogues`, `controller`.

Each module: ~3 tasks (fetcher + drill + tests). Plus shared work: delete `modules/_registry.py`, update `modules/__init__.py` auto-import, capture `tests/fixtures/smartzone/` JSONs.

**Ship criterion:** Logged in to lab SmartZone → all 8 wireless tiles populate within 30s → drill-ins render real rows.

**Size:** ~24 tasks, 5-7 days.

### Plan 2c — Switching modules end-to-end

**Goal:** 7 switching modules.

**Modules:** `switches`, `switch_groups`, `ports`, `traffic`, `poe`, `stack`, `vlans`.

Plus: expand `clients/switchm.py` with missing endpoints (MAC table query, LLDP, stack details). Capture `tests/fixtures/switchm/`.

**Ship criterion:** Switching tiles populate from live SwitchM. Ports heatmap renders. PoE budget visible per switch.

**Size:** ~21 tasks, 5-7 days.

### Plan 2d — Cross-cutting + Bootstrap

**Goal:** Firmware + Security + API Explorer modules + `install.sh` / `install.ps1` + `start.sh` / `start.ps1` + DEPLOY docs.

**Modules:**
- `firmware` — port monolith firmware-posture logic.
- `security` — port `validate_assets` + KEV/NVD validator.
- `api_explorer` — searchable browser over `available_ops`. Filter chips. GET-only sample-fetch proxy.

**Bootstrap:** scripts per Section 3 above + DEPLOY docs.

**Ship criterion:** Fresh Ubuntu/Windows VM → `git clone && ./scripts/install.sh` → dashboard live within 90s of first prompt. Firmware/Security/API Explorer tiles populated.

**Size:** ~12 tasks, 3 days.

**Total Plan 2 budget:** ~64 tasks, 14-19 dev days end-to-end.

## 5 — Testing

Per sub-plan, same shape:

- **Unit (~70%)**: per-module fetcher with mocked `request_json`. Normalization tests. Merge logic with 2+ controllers. Filter dialect. Summary fn shape. WarmupScheduler with mocked fetchers.
- **Integration (~20%)**: Flask test_client. `/api/modules/<slug>` returns envelope. Drill-in routes. SSE warmup stream emits events on `module-ready`. Connect → warmup completion. Capability gating disables modules whose ops missing.
- **Fixtures**: `tests/fixtures/smartzone/` + `tests/fixtures/switchm/` — sanitized real-controller response JSONs. Module tests load these.
- **Smoke (~10%)**: bootstrap test — fresh tmpdir, run `install.sh` with `RUCKUS_INSTALL_NONINTERACTIVE=1`, verify dashboard boots + `/healthz` 200.

CI: matrix unchanged from Plan 1 (Ubuntu + Windows × Python 3.10/3.11/3.12). Coverage gate ≥75%.

## 6 — Risks + mitigations

| Risk | Mitigation |
|---|---|
| Warmup floods controller on big fabrics | Per-module timeout (30s), worker cap (4), back-off on 5xx, partial envelope for completed modules only. |
| SSE breaks behind reverse proxies | `/api/warmup/status` polling fallback in JS auto-degrades. |
| Module fetcher fails mid-warmup | Status flips to `failed`, tile shows error pill, polling resumes next cycle. |
| API drift between SmartZone versions | Fixture contract tests per touched endpoint. Capability gate disables modules whose ops missing. |
| Public-rename of `_smartzone_*` breaks Plan 1 imports | Renames executed in Plan 2a as single commit. Grep + replace across `clients/` + `routes/` + tests. |
| Bootstrap `.env` prompts hard to test | `RUCKUS_INSTALL_NONINTERACTIVE=1` mode reads from env vars. CI uses this. |
| Multi-controller stacking adds complexity | Single-controller scope only in Plan 2. Plan 3+ adds add-mode. |

## 7 — Out of scope

- Profile save/load UI (deferred from Plan 1 login flow)
- Multi-controller add-another mode
- RBAC, multi-tenant
- Time-series persistence
- Write actions (read-only mandate)
- i18n
- Docker containerization

## Next step

Invoke `superpowers:writing-plans` to produce Plan 2a implementation plan. Plans 2b/2c/2d follow each prior plan's ship.
