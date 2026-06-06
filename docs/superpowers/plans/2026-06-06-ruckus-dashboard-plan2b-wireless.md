# Plan 2b — Wireless Modules End-to-End

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Tasks are larger than usual — each delivers one fully-working module with fetcher + summary + drill + tests. Subagent TDD inside the task.

**Goal:** Replace stub fetchers with real implementations for the 8 wireless modules. After login, warmup pre-populates each tile with live counts from SmartZone (or RUCKUS One where supported). Click any tile to drill into rows, click a row to drill into entity detail.

**Architecture:** Each `modules/<slug>.py` follows the file template from Plan 2 design Section 2. Single file owns: registration, primary fetcher, summary, drill fetcher(s), filter dialect, normalization, merge. Routes generic in `routes/modules.py` (already from Plan 1 Task 24) — just add `/api/modules/<slug>/<entity_id>` for drill-in.

**Tech Stack:** existing — `clients.smartzone.smartzone_*`, `clients.ruckus_one._fetch_ruckus_one_*`, `ParallelFetcher`, `WarmupScheduler`, `pytest` + `responses` for mocks.

**Spec:** `docs/superpowers/specs/2026-06-06-ruckus-dashboard-plan2-design.md`

**Monolith reference** (for fetcher logic):
- Pre-refactor monolith is in `Claude_Projects` repo at commit `26d5e91` — `git show 26d5e91:RUCKUS/ruckus_dashboard.py` from that path.
- Functions of interest: `_fetch_smartzone_inventory` (line ~1098 → AP rows), `_fetch_smartzone_operational` (~1242 → AP stats + alarms), `_smartzone_alarm_summary` (~1415).

---

## File Structure

```
RUCKUS/ruckus_dashboard/
├── modules/
│   ├── __init__.py              # MODIFY — auto-import sibling files
│   ├── _registry.py             # MODIFY — drop entries for modules built below
│   ├── overview.py              # CREATE
│   ├── zones.py                 # CREATE
│   ├── aps.py                   # CREATE
│   ├── wlans.py                 # CREATE
│   ├── clients.py               # CREATE
│   ├── alarms.py                # CREATE
│   ├── rogues.py                # CREATE
│   └── controller.py            # CREATE
├── routes/
│   └── modules.py               # MODIFY — add drill-in routes
└── clients/
    └── smartzone.py             # MODIFY only if missing public helpers

tests/
├── fixtures/smartzone/          # CREATE — JSON response samples
│   ├── apiInfo.json
│   ├── rkszones.json
│   ├── query_ap.json
│   ├── query_wlan.json
│   ├── query_client.json
│   ├── alarm_summary.json
│   ├── query_alarm.json
│   ├── query_rogues.json
│   └── cluster_state.json
├── unit/modules/
│   ├── test_overview.py         # CREATE
│   ├── test_zones.py            # CREATE
│   ├── test_aps.py              # CREATE
│   ├── test_wlans.py            # CREATE
│   ├── test_clients.py          # CREATE
│   ├── test_alarms.py           # CREATE
│   ├── test_rogues.py           # CREATE
│   └── test_controller.py       # CREATE
```

---

### Task 1: Auto-import modules + drill-in route

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/modules/__init__.py` (auto-import siblings — but only when files exist; this task does NOT delete `_registry.py` yet)
- Modify: `RUCKUS/ruckus_dashboard/routes/modules.py` (add `GET /api/modules/<slug>/<entity_id>`)

- [ ] **Step 1: Failing test for drill route**

Append to `tests/integration/test_routes_new_ui.py`:

```python
def test_drill_route_unauthenticated_401():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/api/modules/aps/AB:CD:EF:01:02:03")
        assert r.status_code == 401


def test_drill_route_unknown_module_404():
    from ruckus_dashboard.app import create_app
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/api/modules/does-not-exist/abc")
        assert r.status_code == 404
```

- [ ] **Step 2: Run → FAIL (404 because route missing)**

- [ ] **Step 3: Add drill route to `routes/modules.py`**

After `module_data` handler, add:

```python
@bp.get("/api/modules/<slug>/<entity_id>")
def module_drill(slug: str, entity_id: str):
    spec = MODULES.get(slug)
    if spec is None:
        abort(404, description=f"unknown module: {slug}")
    if not session.get("auth"):
        return jsonify({"error": "Connection expired. Please reconnect.", "reauth": True}), 401
    if spec.drill_fetcher is None:
        return jsonify({"error": "Module has no drill-in.", "slug": slug}), 404

    conn_ids = tuple(session.get("connection_ids", []))
    pairs = [(cid, current_app.connection_store.get(cid)) for cid in conn_ids]
    pairs = [(cid, c) for cid, c in pairs if c is not None]
    if not pairs:
        return jsonify({"error": "Connection expired.", "reauth": True}), 401

    gate = CapabilityGate(available=getattr(current_app, "available_ops", set()))
    filters = request.args.to_dict()
    _, conn = pairs[0]  # drill always uses first controller
    ctx = FetcherContext(connection=conn, config=dict(current_app.config),
                         filters=filters, capability_gate=gate,
                         connection_label=conn.display_name)
    try:
        data = spec.drill_fetcher(ctx, entity_id)
    except Exception as exc:
        return jsonify({"error": str(exc), "slug": slug, "entity_id": entity_id}), 502
    env = build_envelope(data=data, summary={}, errors=[])
    return jsonify(env)
```

- [ ] **Step 4: Modify `modules/__init__.py`**

Replace the existing stub-registry side-effect import. Final content:

```python
"""Module registry. Built modules call register() at import time."""
from ._base import ModuleSpec

MODULES: dict[str, ModuleSpec] = {}


def register(spec: ModuleSpec) -> ModuleSpec:
    if spec.slug in MODULES:
        # Override allowed: real module supersedes its earlier stub.
        MODULES[spec.slug] = spec
        return spec
    MODULES[spec.slug] = spec
    return spec


def all_modules() -> list[ModuleSpec]:
    return sorted(MODULES.values(), key=lambda m: (m.group, m.title))


# Auto-import every module side-effect-registers itself.
from . import _registry  # noqa: F401,E402 (stubs first — replaced when real lands)

# Real modules below. Each call to register() in these files overrides the stub.
```

(The trailing comment is a placeholder. Each Task 2-9 will append `from . import <slug>` here.)

- [ ] **Step 5: Run + commit**

```bash
pytest -q
```

Expected: 128 passed.

```bash
git add RUCKUS/ruckus_dashboard/modules/__init__.py RUCKUS/ruckus_dashboard/routes/modules.py tests/integration/test_routes_new_ui.py
git commit -m "feat: add drill-in route + allow real modules to override stubs"
```

---

### Task 2: `modules/aps.py` — Access Points

**Files:**
- Create: `RUCKUS/ruckus_dashboard/modules/aps.py`
- Create: `tests/fixtures/smartzone/query_ap.json`
- Create: `tests/unit/modules/test_aps.py`
- Modify: `RUCKUS/ruckus_dashboard/modules/__init__.py` (append `from . import aps`)

**Fetcher behavior:** Calls `smartzone_query_paged(connection, "query/ap", ...)`. Normalizes each row into `{id, name, model, zone, status, clients, fw, ip, mac, last_seen}`. Summary: `{total, online, offline, flagged, clients}`. Drill fetcher: `smartzone_get(connection, f"aps/{mac}/operational/summary")` returning AP detail.

- [ ] **Step 1: Capture fixture**

Create `tests/fixtures/smartzone/query_ap.json` with hand-crafted shape:

```json
{
  "list": [
    {"apMac": "AA:BB:CC:DD:EE:01", "deviceName": "AP-Lobby", "model": "R650",
     "zoneId": "z1", "zoneName": "HQ", "status": "Online",
     "numClients": 12, "firmwareVersion": "7.0.0.300", "ip": "10.0.1.21",
     "lastSeenTime": 1736140000000},
    {"apMac": "AA:BB:CC:DD:EE:02", "deviceName": "AP-Mtg-3", "model": "R770",
     "zoneId": "z1", "zoneName": "HQ", "status": "Offline",
     "numClients": 0, "firmwareVersion": "7.0.0.300", "ip": "10.0.1.22",
     "lastSeenTime": 1736130000000},
    {"apMac": "AA:BB:CC:DD:EE:03", "deviceName": "AP-Cafe", "model": "R650",
     "zoneId": "z2", "zoneName": "DXB", "status": "Flagged",
     "numClients": 3, "firmwareVersion": "6.1.2.100", "ip": "10.0.2.21",
     "lastSeenTime": 1736140500000}
  ],
  "totalCount": 3,
  "hasMore": false
}
```

- [ ] **Step 2: Write failing test**

```python
# tests/unit/modules/test_aps.py
import json, pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import aps as aps_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

FIXTURE = json.loads(pathlib.Path("tests/fixtures/smartzone/query_ap.json").read_text())

CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None}


def _ctx(conn=None, filters=None):
    if conn is None:
        conn = ConnectionConfig(platform="smartzone",
                                api_base="https://sz.example:8443/wsg/api/public",
                                display_name="SZ", auth_token="t",
                                api_version="v11_0", verify_tls=False,
                                token_expires_at=9999999999)
    return FetcherContext(connection=conn, config=CFG, filters=filters,
                          capability_gate=CapabilityGate(set()),
                          connection_label="SZ")


@responses.activate
def test_aps_fetch_returns_normalised_rows():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.POST, f"{base}/v11_0/query/ap",
                  json=FIXTURE, status=200)
    out = aps_mod.fetch(_ctx())
    assert len(out["items"]) == 3
    first = out["items"][0]
    assert first["name"] == "AP-Lobby"
    assert first["mac"] == "AA:BB:CC:DD:EE:01"
    assert first["status"] == "online"
    assert first["clients"] == 12
    assert first["model"] == "R650"


def test_aps_summary_counts_by_status():
    data = {"items": [
        {"status": "online", "clients": 12},
        {"status": "online", "clients": 5},
        {"status": "offline", "clients": 0},
        {"status": "flagged", "clients": 3},
    ]}
    s = aps_mod.summary(data)
    assert s["total"] == 4
    assert s["online"] == 2
    assert s["offline"] == 1
    assert s["flagged"] == 1
    assert s["clients"] == 20


def test_aps_merge_concats_across_controllers():
    a = {"items": [{"mac": "AA"}], "raw_count": 1}
    b = {"items": [{"mac": "BB"}], "raw_count": 1}
    out = aps_mod.merge([a, b])
    assert len(out["items"]) == 2
    assert out["raw_count"] == 2


def test_aps_registered_in_modules_registry():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["aps"].slug == "aps"
    assert MODULES["aps"].fetcher is aps_mod.fetch
```

- [ ] **Step 3: Run → FAIL**

- [ ] **Step 4: Create `modules/aps.py`**

```python
"""Access Points — primary wireless module."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_post

POLL_SECONDS = 30
ICON = "📶"

ONLINE_VALUES = {"online", "connected", "run", "operational", "registered", "up"}
OFFLINE_VALUES = {"offline", "disconnected", "down", "unregistered", "gone"}
FLAGGED_VALUES = {"flagged", "warning", "degraded"}


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    payload = _build_query(ctx.filters)
    response = smartzone_post(ctx.connection, "query/ap",
                              json=payload, config=ctx.config, debug=[])
    rows = response.get("list") or []
    items = [_normalize(r) for r in rows]
    return {"items": items, "raw_count": response.get("totalCount", len(rows))}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    online = sum(1 for i in items if i.get("status") == "online")
    offline = sum(1 for i in items if i.get("status") == "offline")
    flagged = sum(1 for i in items if i.get("status") == "flagged")
    clients = sum(int(i.get("clients") or 0) for i in items)
    return {"total": len(items), "online": online,
            "offline": offline, "flagged": flagged, "clients": clients}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    from ..clients.smartzone import smartzone_get
    try:
        detail = smartzone_get(ctx.connection,
                               f"aps/{entity_id}/operational/summary",
                               config=ctx.config, debug=[])
    except Exception as exc:
        return {"identity": {"id": entity_id}, "error": str(exc)}
    return {"identity": _normalize(detail), "raw": detail}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}


def _build_query(filters: dict | None) -> dict:
    f = filters or {}
    payload = {"page": int(f.get("page", 0)),
               "limit": int(f.get("limit", 500))}
    if f.get("zone"):
        payload["filters"] = [{"type": "ZONE_ID", "value": f["zone"]}]
    return payload


def _normalize(row: dict) -> dict:
    raw_status = str(row.get("status") or "").lower()
    if raw_status in ONLINE_VALUES:
        status = "online"
    elif raw_status in OFFLINE_VALUES:
        status = "offline"
    elif raw_status in FLAGGED_VALUES:
        status = "flagged"
    else:
        status = raw_status or "unknown"
    return {
        "id": row.get("apMac"),
        "name": row.get("deviceName") or row.get("name") or "-",
        "model": row.get("model"),
        "zone": row.get("zoneName"),
        "zone_id": row.get("zoneId"),
        "status": status,
        "clients": int(row.get("numClients") or 0),
        "fw": row.get("firmwareVersion") or row.get("firmware"),
        "ip": row.get("ip") or row.get("ipAddress"),
        "mac": row.get("apMac"),
        "last_seen": row.get("lastSeenTime"),
    }


register(ModuleSpec(
    slug="aps", title="Access Points", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("POST", "/query/ap"),),
    supports_views=("table", "grid"),
    warmup=True,
    merge=merge,
))
```

- [ ] **Step 5: Append `from . import aps` to `modules/__init__.py`** (under the comment block)

- [ ] **Step 6: Run + commit**

```bash
pytest tests/unit/modules/test_aps.py -v
pytest -q
git add RUCKUS/ruckus_dashboard/modules/aps.py RUCKUS/ruckus_dashboard/modules/__init__.py tests/fixtures/smartzone/query_ap.json tests/unit/modules/test_aps.py
git commit -m "feat(aps): real fetcher with normalization + summary + drill"
```

---

### Task 3: `modules/zones.py` — Zones

**Fetcher behavior:** GET `/rkszones` → list of zones. Normalize → `{id, name, ap_count, wlan_count, fw, country, mesh_mode}`. Drill: GET `/rkszones/{id}` for full detail.

- [ ] **Step 1: Fixture `tests/fixtures/smartzone/rkszones.json`:**

```json
{"list": [
  {"id": "z1", "name": "HQ", "countryCode": "AE",
   "version": "7.0.0.300", "meshMode": "Disabled",
   "apCount": 24, "wlanCount": 8},
  {"id": "z2", "name": "DXB-Branch", "countryCode": "AE",
   "version": "7.0.0.300", "meshMode": "Disabled",
   "apCount": 6, "wlanCount": 4}
], "totalCount": 2, "hasMore": false}
```

- [ ] **Step 2-6: Mirror Task 2 pattern.**

`modules/zones.py`:

```python
"""Zones module."""
from __future__ import annotations
from typing import Any
from urllib.parse import quote

from . import register
from ._base import FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_paged_get, smartzone_get

POLL_SECONDS = 60
ICON = "🏢"


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    rows = smartzone_paged_get(ctx.connection, "rkszones",
                               config=ctx.config, debug=[])
    items = [_normalize(r) for r in rows]
    return {"items": items, "raw_count": len(rows)}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    return {"total": len(items),
            "total_aps": sum(int(i.get("ap_count") or 0) for i in items),
            "total_wlans": sum(int(i.get("wlan_count") or 0) for i in items)}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    try:
        detail = smartzone_get(ctx.connection,
                               f"rkszones/{quote(entity_id)}",
                               config=ctx.config, debug=[])
    except Exception as exc:
        return {"identity": {"id": entity_id}, "error": str(exc)}
    return {"identity": _normalize(detail), "raw": detail}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for r in results:
        items.extend(r.get("items", []))
    return {"items": items, "raw_count": len(items)}


def _normalize(row: dict) -> dict:
    return {
        "id": row.get("id") or row.get("zoneId"),
        "name": row.get("name") or row.get("serviceName") or "-",
        "ap_count": int(row.get("apCount") or 0),
        "wlan_count": int(row.get("wlanCount") or 0),
        "fw": row.get("version") or row.get("firmwareVersion"),
        "country": row.get("countryCode"),
        "mesh_mode": row.get("meshMode"),
    }


register(ModuleSpec(
    slug="zones", title="Zones", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS, fetcher=fetch, drill_fetcher=fetch_drill,
    drill_tabs=(TabSpec(slug="summary", title="Summary"),
                TabSpec(slug="raw", title="Raw")),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("GET", "/rkszones"),),
    supports_views=("table", "tree"),
    warmup=True, merge=merge,
))
```

Tests mirror Task 2.

Commit message: `feat(zones): real fetcher + drill`.

---

### Task 4: `modules/wlans.py` — WLANs

**Fetcher:** `POST /query/wlan`. Normalize: `{id, ssid, zone, vlan, auth, encryption, clients}`. Drill: GET `/rkszones/{zone}/wlans/{id}`.

Fixture `query_wlan.json`:

```json
{"list": [
  {"id": "w1", "name": "Corp", "zoneId": "z1", "zoneName": "HQ",
   "vlanId": 10, "authType": "8021X", "encryption": "WPA2",
   "numClients": 45},
  {"id": "w2", "name": "Guest", "zoneId": "z1", "zoneName": "HQ",
   "vlanId": 20, "authType": "OPEN", "encryption": "NONE",
   "numClients": 12}
], "totalCount": 2}
```

Module file pattern same as aps. `requires_capabilities=(("POST","/query/wlan"),)`. Summary: `{total, clients, by_auth: {...}}`.

Commit: `feat(wlans): real fetcher + drill`.

---

### Task 5: `modules/clients.py` — Wireless Clients

**Fetcher:** `POST /query/client`. Normalize: `{id, mac, hostname, ip, ssid, ap, rssi, rx_bytes, tx_bytes, os, auth_method, connected_at}`. Drill: GET `/clients/{mac}/operational/summary` (if exists).

Fixture `query_client.json`:

```json
{"list": [
  {"clientMac": "11:22:33:44:55:01", "hostname": "laptop-1",
   "ipAddress": "10.0.1.50", "ssid": "Corp", "apMac": "AA:BB:CC:DD:EE:01",
   "rssi": -52, "rxBytes": 1024000, "txBytes": 256000,
   "osType": "Windows", "authMethod": "8021X", "connectionTime": 1736140000000},
  {"clientMac": "11:22:33:44:55:02", "hostname": "phone-2",
   "ipAddress": "10.0.1.51", "ssid": "Guest", "apMac": "AA:BB:CC:DD:EE:01",
   "rssi": -68, "rxBytes": 50000, "txBytes": 10000,
   "osType": "iOS", "authMethod": "OPEN", "connectionTime": 1736140100000}
], "totalCount": 2}
```

Module file: `requires_capabilities=(("POST","/query/client"),)`. Summary: `{total, by_band, low_rssi}` where low_rssi = clients with rssi < -70.

Commit: `feat(clients): real fetcher + drill`.

---

### Task 6: `modules/alarms.py` — Alarms & Events

**Fetcher:** `POST /alert/alarmSummary` for KPIs; `POST /query/alarm` for list. Normalize alarm: `{id, severity, category, source, message, first_seen, last_seen, ack_state, count}`. Summary: `{critical, major, minor, warning, total}`.

Fixture `alarm_summary.json`:

```json
{"critical": 2, "major": 5, "minor": 8, "warning": 12, "total": 27}
```

Fixture `query_alarm.json`:

```json
{"list": [
  {"alarmId": "a1", "severity": "Critical", "category": "AP",
   "sourceName": "AP-Lobby", "alarmType": "AP down",
   "firstAppearTime": 1736140000000, "lastAppearTime": 1736140500000,
   "ackState": "Outstanding", "alarmCount": 1},
  {"alarmId": "a2", "severity": "Major", "category": "Switch",
   "sourceName": "SW-1", "alarmType": "Port flap",
   "firstAppearTime": 1736139000000, "lastAppearTime": 1736140000000,
   "ackState": "Acknowledged", "alarmCount": 3}
], "totalCount": 2}
```

Module file: fetcher does BOTH calls (summary + list) and returns `{items, summary_raw}`. `summary_fn` reads `summary_raw` if present.

`requires_capabilities=(("POST","/alert/alarmSummary"), ("POST","/query/alarm"))`.

Commit: `feat(alarms): real fetcher with summary + list`.

---

### Task 7: `modules/rogues.py` — Rogues

**Fetcher:** `POST /query/roguesInfoList`. Normalize: `{id, ssid, bssid, channel, encryption, rssi, detecting_ap, classification, first_seen, last_seen}`. Summary: `{total, malicious, rogue, known}`.

Fixture `query_rogues.json`:

```json
{"list": [
  {"bssid": "DE:AD:BE:EF:00:01", "ssid": "FreeWifi", "channel": 6,
   "encryption": "OPEN", "rssi": -55, "detectingAp": "AA:BB:CC:DD:EE:01",
   "classification": "Malicious",
   "firstFoundTime": 1736140000000, "lastFoundTime": 1736140500000},
  {"bssid": "DE:AD:BE:EF:00:02", "ssid": "NeighborNet", "channel": 11,
   "encryption": "WPA2", "rssi": -78, "detectingAp": "AA:BB:CC:DD:EE:02",
   "classification": "Known",
   "firstFoundTime": 1736130000000, "lastFoundTime": 1736140000000}
], "totalCount": 2}
```

`requires_capabilities=(("POST","/query/roguesInfoList"),)`.

Commit: `feat(rogues): real fetcher`.

---

### Task 8: `modules/controller.py` — Controller

**Fetcher:** GET `/cluster/state`, GET `/system/devicesSummary`, GET `/licensesSummary`. Returns combined dict. Summary: `{nodes_online, license_used, license_total}`.

Fixture `cluster_state.json`:

```json
{"clusterName": "sz-cluster", "currentNodes": 3, "totalNodes": 3,
 "clusterRole": "ACTIVE"}
```

`requires_capabilities=(("GET","/cluster/state"),)`.

Commit: `feat(controller): cluster + licenses + devices summary`.

---

### Task 9: `modules/overview.py` — DSO Overview

**Fetcher:** No upstream call. Reads `app.warmup_scheduler.snapshot()` (via FetcherContext if accessible) OR returns empty summary that the SSE strip populates.

Pragmatic implementation: `fetch` returns `{items: []}`, `summary` returns `{}`. The Overview tile grid is already populated by the warmup SSE stream (Plan 2a Task 11). This module exists primarily to satisfy the sidebar entry + registry.

```python
def fetch(ctx): return {"items": [], "_overview": True}
def summary(data): return {}

register(ModuleSpec(
    slug="overview", title="DSO Overview", group="Wireless", icon="📡",
    poll_seconds=15,
    fetcher=fetch, drill_fetcher=None, drill_tabs=(),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(),
    supports_views=("table",),
    warmup=True, merge=None,
))
```

Commit: `feat(overview): registered (UI tiles driven by warmup SSE)`.

---

### Task 10: Drop stubs from `_registry.py` + verify all 8 modules present

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/modules/_registry.py`

- [ ] **Step 1:** Remove the 8 wireless module entries (`overview`, `zones`, `aps`, `wlans`, `clients`, `alarms`, `rogues`, `controller`) from the `_DEFS` list. Keep `switches`, `switch-groups`, `ports`, `traffic`, `poe`, `stack`, `vlans`, `firmware`, `security`, `api-explorer` stubs.

- [ ] **Step 2:** Test registry still has 18 entries:

```python
def test_registry_has_18_modules_after_wireless_promoted():
    from ruckus_dashboard.modules import MODULES
    assert len(MODULES) == 18
    # 8 promoted modules now use real fetcher (not stub_fetcher)
    from ruckus_dashboard.modules._stub import stub_fetcher
    for slug in ("overview","zones","aps","wlans","clients","alarms","rogues","controller"):
        assert MODULES[slug].fetcher is not stub_fetcher, f"{slug} still a stub"
    # Switching + cross-cutting remain stubs
    for slug in ("switches","ports","firmware","security"):
        assert MODULES[slug].fetcher is stub_fetcher, f"{slug} should still be stub"
```

- [ ] **Step 3:** Run full suite, commit.

Commit: `feat: drop wireless stubs from registry`.

---

## Acceptance criteria

- [ ] All 8 wireless modules have real fetchers (no `stub_fetcher` for them).
- [ ] Each module has unit tests covering fetch + summary + (where applicable) merge + drill.
- [ ] Each module's required SmartZone endpoints have a fixture.
- [ ] Drill route `/api/modules/<slug>/<entity_id>` returns 401 unauth, 200 envelope when auth + drill_fetcher.
- [ ] Full pytest count is at minimum the prior 126 + roughly 4 tests per module × 8 + 2 route tests = ~160.
- [ ] After live login: 8 wireless tiles populate via warmup; switching tiles still show `·` (skipped) or `0` (stub).

## Self-review

**Spec coverage** — Each of the 8 wireless modules in Plan 2 spec section 4 (Plan 2b list) has a task. Drill route + auto-import covered in Task 1. Stub deletion in Task 10.

**Placeholder check** — Fetcher code for `aps` and `zones` is complete. Tasks 4-8 give the fetcher pattern from Task 2 and the per-module specifics (capability, normalization fields, summary shape, fixture). Implementer adapts the Task 2 file template per-module — pure pattern repetition, low risk.

**Type consistency** — All modules return `{items: [...], raw_count: N}`. `summary_fn` returns dict. Drill returns `{identity, raw}` or `{identity, error}`. Consistent across tasks.

**Scope** — Wireless only. Switching + cross-cutting deferred to 2c/2d.
