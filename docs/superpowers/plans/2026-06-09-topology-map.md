# Topology Map Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A `topology` tab that draws a logical hierarchy map (controller → zones / switch-groups → switches) as a zero-dependency pan/zoom SVG, colored by status, built from already-cached data.

**Architecture:** A new `topology` ModuleSpec whose `fetch()` assembles a `{nodes, edges, legend}` graph from existing client helpers. A dedicated `topology.html` page (special-cased like `/m/overview`) loads `topology.js`, which polls `/api/modules/topology` and renders SVG with radial-tier layout + viewBox pan/zoom + click-to-module.

**Tech Stack:** Flask/Jinja, vanilla JS + SVG, pytest + responses.

---

### Task 1: topology graph builder (`_build_graph`, summary, merge)

**Files:**
- Create: `RUCKUS/ruckus_dashboard/modules/topology.py`
- Test: `tests/unit/modules/test_topology.py`

- [ ] **Step 1: Write failing test**

```python
from ruckus_dashboard.modules import topology as t

CLUSTER = {"clusterName": "AHD-SZ", "clusterState": "In_Service"}
ZONES = [{"id": "z1", "name": "HQ"}]
APS = [{"apMac": "a1", "zoneId": "z1", "status": "Online"},
       {"apMac": "a2", "zoneId": "z1", "status": "Offline"}]
SWITCHES = [{"id": "s1", "switchName": "SW-1", "groupId": "g1",
             "groupName": "Core", "status": "online"}]
TRAFFIC = {"S1": 1024}

def test_build_graph_shapes_nodes_and_edges():
    g = t._build_graph(CLUSTER, ZONES, APS, SWITCHES, {"s1": 1024})
    types = {n["type"] for n in g["nodes"]}
    assert {"controller", "zone", "group", "switch"} <= types
    ctrl = next(n for n in g["nodes"] if n["type"] == "controller")
    assert ctrl["status"] == "online"
    zone = next(n for n in g["nodes"] if n["type"] == "zone")
    assert zone["meta"]["ap_total"] == 2 and zone["meta"]["ap_down"] == 1
    assert zone["status"] == "flagged"           # some down, not all
    # edges: controller->zone, controller->group, group->switch
    pairs = {(e["source"], e["target"]) for e in g["edges"]}
    assert ("controller", "z1") in pairs
    assert ("controller", "g1") in pairs
    assert ("g1", "s1") in pairs
    sw_edge = next(e for e in g["edges"] if e["target"] == "s1")
    assert sw_edge["label"]            # traffic label present

def test_summary_counts():
    g = t._build_graph(CLUSTER, ZONES, APS, SWITCHES, {"s1": 1024})
    s = t.summary(g)
    assert s["nodes"] == len(g["nodes"])
    assert s["switches"] == 1

def test_merge_preserves_graph():
    g = t._build_graph(CLUSTER, ZONES, APS, SWITCHES, {})
    merged = t.merge([g])
    assert merged["nodes"] == g["nodes"]
    assert merged["edges"] == g["edges"]
```

- [ ] **Step 2: Run, expect FAIL** (module missing).

- [ ] **Step 3: Implement `topology.py`** (builder + summary + merge + register; `fetch` added in Task 2):

```python
"""Topology — logical hierarchy map (controller → zones / switch-groups → switches)."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import FetcherContext, ModuleSpec
from ..clients.smartzone import (
    smartzone_get, smartzone_paged_get, smartzone_post, smartzone_query_body,
    smartzone_query_paged,
)
from ..clients.switchm import fetch_switches, switch_manager_query

POLL_SECONDS = 60
ICON = "\U0001F578"  # spider web (map-like)

_ONLINE = {"online", "in_service", "connected", "run", "operational", "registered", "up"}

STATUS_COLORS = {"online": "#2ecc71", "flagged": "#f1c40f",
                 "offline": "#e74c3c", "unknown": "#7c8aa0"}


def _norm_status(raw: str) -> str:
    r = str(raw or "").lower()
    if r in _ONLINE:
        return "online"
    if r in {"offline", "disconnected", "down", "gone", "unregistered"}:
        return "offline"
    if r in {"flagged", "warning", "degraded"}:
        return "flagged"
    return "unknown"


def _build_graph(cluster, zones, aps, switches, traffic_by_mac):
    cluster = cluster or {}
    nodes: list[dict] = []
    edges: list[dict] = []

    ctrl_status = "online" if str(cluster.get("clusterState") or "").lower() in _ONLINE else "unknown"
    nodes.append({"id": "controller", "label": cluster.get("clusterName") or "Controller",
                  "type": "controller", "status": ctrl_status, "meta": {}})

    # Zones with aggregated AP counts.
    ap_by_zone: dict[str, list[str]] = {}
    for ap in aps or []:
        zid = str(ap.get("zoneId") or "")
        ap_by_zone.setdefault(zid, []).append(_norm_status(ap.get("status")))
    for z in zones or []:
        zid = str(z.get("id") or z.get("zoneId") or "")
        statuses = ap_by_zone.get(zid, [])
        total = len(statuses)
        down = sum(1 for s in statuses if s == "offline")
        zstatus = "online" if total == 0 or down == 0 else ("offline" if down == total else "flagged")
        nodes.append({"id": zid or z.get("name"), "label": f"{z.get('name') or 'Zone'} ({total} APs)",
                      "type": "zone", "status": zstatus,
                      "meta": {"ap_total": total, "ap_down": down}})
        edges.append({"source": "controller", "target": zid or z.get("name"),
                      "status": zstatus, "label": ""})

    # Switch groups/stacks + switch leaves.
    groups: dict[str, dict] = {}
    for sw in switches or []:
        gid = str(sw.get("groupId") or sw.get("stackId") or "ungrouped")
        gname = sw.get("groupName") or sw.get("stack") or "Switches"
        groups.setdefault(gid, {"name": gname, "switches": []})
        groups[gid]["switches"].append(sw)
    for gid, g in groups.items():
        child_statuses = [_norm_status(s.get("status")) for s in g["switches"]]
        gstatus = "online"
        if any(s == "offline" for s in child_statuses):
            gstatus = "flagged"
        if child_statuses and all(s == "offline" for s in child_statuses):
            gstatus = "offline"
        nodes.append({"id": gid, "label": f"{g['name']} ({len(g['switches'])})",
                      "type": "group", "status": gstatus, "meta": {}})
        edges.append({"source": "controller", "target": gid, "status": gstatus, "label": ""})
        for sw in g["switches"]:
            sid = sw.get("id") or sw.get("macAddress")
            mac = str(sid).upper() if sid else ""
            bytes_ = traffic_by_mac.get(mac) or traffic_by_mac.get(str(sid)) if sid else None
            nodes.append({"id": sid, "label": sw.get("switchName") or sw.get("name") or sid,
                          "type": "switch", "status": _norm_status(sw.get("status")),
                          "meta": {"traffic_bytes": bytes_}})
            edges.append({"source": gid, "target": sid,
                          "status": _norm_status(sw.get("status")),
                          "label": _human_bytes(bytes_) if bytes_ else ""})

    return {"nodes": nodes, "edges": edges,
            "legend": {"status": STATUS_COLORS}, "items": []}


def _human_bytes(n) -> str:
    v = float(n or 0)
    if v <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if v < 1024:
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} EB"


def summary(data: dict[str, Any]) -> dict[str, Any]:
    nodes = data.get("nodes", [])
    return {"nodes": len(nodes),
            "online": sum(1 for n in nodes if n.get("status") == "online"),
            "offline": sum(1 for n in nodes if n.get("status") == "offline"),
            "switches": sum(1 for n in nodes if n.get("type") == "switch")}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    # Single controller; preserve the full graph (default merge keeps only items).
    for r in results:
        if r.get("nodes"):
            return r
    return {"nodes": [], "edges": [], "legend": {"status": STATUS_COLORS}, "items": []}


register(ModuleSpec(
    slug="topology", title="Topology", group="Cross-cutting", icon=ICON,
    poll_seconds=POLL_SECONDS, fetcher=fetch, drill_fetcher=None, drill_tabs=(),
    summary_fn=summary, requires_platforms=("smartzone",),
    requires_capabilities=(("GET", "/cluster/state"),),
    supports_views=("graph",), warmup=True, merge=merge,
))
```

(`fetch` is defined in Task 2 above the register call.)

- [ ] **Step 4: Run, expect PASS** for the three tests once Task 2's `fetch` stub exists. (Define `fetch` now as a stub returning `{}` so the module imports; real body in Task 2.)
- [ ] **Step 5: Commit** `feat(topology): graph builder + summary/merge`

---

### Task 2: topology `fetch()` wiring

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/modules/topology.py`
- Test: `tests/unit/modules/test_topology.py`

- [ ] **Step 1: Write failing test** (mock the 4 upstreams):

```python
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.infra.capability_gate import CapabilityGate

CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None}

def _ctx():
    conn = ConnectionConfig(platform="smartzone",
        api_base="https://sz.example:8443/wsg/api/public", display_name="SZ",
        auth_token="t", api_version="v11_0", verify_tls=False, token_expires_at=9999999999)
    return FetcherContext(connection=conn, config=CFG, filters=None,
        capability_gate=CapabilityGate(set()), connection_label="SZ")

@responses.activate
def test_topology_fetch_assembles_graph():
    base = "https://sz.example:8443/wsg/api/public"
    sw = "https://sz.example:8443/switchm/api"
    responses.add(responses.GET, f"{base}/v11_0/cluster/state",
                  json={"clusterName": "AHD-SZ", "clusterState": "In_Service"}, status=200)
    responses.add(responses.GET, f"{base}/v11_0/rkszones",
                  json={"list": [{"id": "z1", "name": "HQ"}], "totalCount": 1, "hasMore": False}, status=200)
    responses.add(responses.POST, f"{base}/v11_0/query/ap",
                  json={"list": [{"apMac": "a1", "zoneId": "z1", "status": "Online"}], "totalCount": 1}, status=200)
    responses.add(responses.POST, f"{sw}/v11_0/switch",
                  json={"list": [{"id": "s1", "switchName": "SW-1", "groupId": "g1",
                                  "groupName": "Core", "status": "online"}],
                        "totalCount": 1, "hasMore": False}, status=200, match_querystring=False)
    responses.add(responses.POST, f"{sw}/v11_0/traffic/top/usage",
                  json={"list": [{"key": "s1", "value": 2048}]}, status=200, match_querystring=False)
    out = topology_mod.fetch(_ctx())
    assert any(n["type"] == "controller" for n in out["nodes"])
    assert any(n["type"] == "switch" for n in out["nodes"])
```

- [ ] **Step 2: Run, expect FAIL** (stub `fetch` returns `{}`).

- [ ] **Step 3: Implement `fetch`** (place above `register`):

```python
def fetch(ctx: FetcherContext) -> dict[str, Any]:
    cluster = _safe(lambda: smartzone_get(ctx.connection, "cluster/state", ctx.config, None, []))
    zones = _safe(lambda: smartzone_paged_get(ctx.connection, "rkszones", ctx.config, debug=[])) or []
    aps = _safe(lambda: smartzone_query_paged(ctx.connection, "query/ap", ctx.config, [])) or []
    sw_resp = _safe(lambda: fetch_switches(ctx.connection, ctx.config)) or {}
    switches = sw_resp.get("switches") or []
    traffic_by_mac = _traffic_map(ctx)
    return _build_graph(cluster, zones, aps, switches, traffic_by_mac)


def _safe(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001 — each source is best-effort
        return None


def _traffic_map(ctx) -> dict:
    out: dict = {}
    data = _safe(lambda: switch_manager_query(ctx.connection, "traffic/top/usage", ctx.config)) or {}
    for r in (data.get("list") or []):
        if isinstance(r, dict):
            key = r.get("key") or r.get("id")
            if key:
                out[str(key).upper()] = int(r.get("value") or 0)
    return out
```

Remove the temporary `fetch` stub.

- [ ] **Step 4: Run, expect PASS.** Then full module test file.
- [ ] **Step 5: Commit** `feat(topology): fetch assembles graph from cached sources`

---

### Task 3: topology page route + template

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/routes/pages.py` (`module_page` special-case)
- Create: `RUCKUS/ruckus_dashboard/templates/topology.html`
- Test: `tests/integration/test_pages.py`

- [ ] **Step 1: Write failing test**

```python
def test_topology_route_renders_graph_container():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/m/topology")
        assert r.status_code == 200
        assert b"data-topology" in r.data
        assert b"topology.js" in r.data
```

- [ ] **Step 2: Run, expect FAIL** (renders module.html).

- [ ] **Step 3a: Implement** — extend the overview special-case in `module_page`:

```python
    if slug == "overview":
        return render_template("overview.html", modules=all_modules(),
                               csrf_token=session.get("csrf_token", ""))
    if slug == "topology":
        return render_template("topology.html", modules=all_modules(),
                               active_slug="topology",
                               csrf_token=session.get("csrf_token", ""))
```

- [ ] **Step 3b: Create `topology.html`**

```html
{% extends "base.html" %}
{% set active_slug = "topology" %}
{% block title %}Topology{% endblock %}
{% block breadcrumb %}Topology{% endblock %}
{% block content %}
<section class="topology" data-topology>
  <div class="topo-toolbar">
    <h1>Network Topology</h1>
    <div class="topo-controls">
      <button data-topo-zoom-in title="Zoom in">+</button>
      <button data-topo-zoom-out title="Zoom out">−</button>
      <button data-topo-fit title="Fit">⤢</button>
    </div>
  </div>
  <div class="topo-canvas" data-topo-canvas><p class="empty">Loading topology…</p></div>
  <div class="topo-legend" data-topo-legend></div>
</section>
<script src="{{ url_for('static', filename='topology.js') }}"></script>
{% endblock %}
```

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(topology): page route + template`

---

### Task 4: topology renderer (`topology.js`) + CSS

**Files:**
- Create: `RUCKUS/ruckus_dashboard/static/topology.js`
- Modify: `RUCKUS/ruckus_dashboard/static/styles.css`
- Test: `tests/integration/test_topology_js.py`

- [ ] **Step 1: Write failing test**

```python
import pathlib
def test_topology_js_symbols_present():
    js = pathlib.Path("RUCKUS/ruckus_dashboard/static/topology.js").read_text(encoding="utf-8")
    for sym in ["layoutGraph", "renderTopology", "/api/modules/topology", "viewBox"]:
        assert sym in js, f"missing {sym}"
```

- [ ] **Step 2: Run, expect FAIL** (file missing).

- [ ] **Step 3: Create `topology.js`** (radial layout + SVG draw + pan/zoom + click):

```javascript
"use strict";
const TOPO_COLORS = { online: "#2ecc71", flagged: "#f1c40f", offline: "#e74c3c", unknown: "#7c8aa0" };
const TOPO_GLYPH = { controller: "🛰️", zone: "📶", group: "🗄️", stack: "🗄️", switch: "🔀" };

function layoutGraph(nodes, edges) {
  const pos = {};
  const byType = t => nodes.filter(n => n.type === t);
  pos["controller"] = { x: 0, y: 0 };
  const ctrl = byType("controller")[0];
  const tier1 = nodes.filter(n => n.type === "zone" || n.type === "group");
  const R1 = 320;
  tier1.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, tier1.length);
    pos[n.id] = { x: Math.cos(a) * R1, y: Math.sin(a) * R1, angle: a };
  });
  // switches fan around their parent group's angle
  const childrenOf = {};
  edges.forEach(e => { (childrenOf[e.source] = childrenOf[e.source] || []).push(e.target); });
  nodes.filter(n => n.type === "group").forEach(g => {
    const base = (pos[g.id] && pos[g.id].angle) || 0;
    const kids = (childrenOf[g.id] || []).filter(id => nodes.find(n => n.id === id && n.type === "switch"));
    const R2 = 540, spread = 0.5;
    kids.forEach((id, i) => {
      const off = kids.length > 1 ? (i / (kids.length - 1) - 0.5) * spread : 0;
      const a = base + off;
      pos[id] = { x: Math.cos(a) * R2, y: Math.sin(a) * R2 };
    });
  });
  return pos;
}

function nodeHref(n) {
  if (n.type === "zone") return "/m/zones";
  if (n.type === "switch") return `/m/switches/${encodeURIComponent(n.id)}`;
  if (n.type === "group" || n.type === "stack") return "/m/switch-groups";
  if (n.type === "controller") return "/m/controller";
  return "";
}

function renderTopology(root, payload) {
  const canvas = root.querySelector("[data-topo-canvas]");
  const data = payload.data || payload;
  const nodes = data.nodes || [], edges = data.edges || [];
  if (!nodes.length) { canvas.innerHTML = `<p class="empty">No topology data.</p>`; return; }
  const pos = layoutGraph(nodes, edges);
  const xs = nodes.map(n => (pos[n.id] || {}).x || 0), ys = nodes.map(n => (pos[n.id] || {}).y || 0);
  const minX = Math.min(...xs) - 120, minY = Math.min(...ys) - 80;
  const w = Math.max(...xs) - minX + 200, h = Math.max(...ys) - minY + 160;
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  const lines = edges.map(e => {
    const a = pos[e.source], b = pos[e.target];
    if (!a || !b) return "";
    const col = TOPO_COLORS[e.status] || TOPO_COLORS.unknown;
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    const lbl = e.label ? `<text class="edge-label" x="${mx}" y="${my}">${e.label}</text>` : "";
    return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${col}" stroke-width="2"/>${lbl}`;
  }).join("");
  const glyphs = nodes.map(n => {
    const p = pos[n.id]; if (!p) return "";
    const col = TOPO_COLORS[n.status] || TOPO_COLORS.unknown;
    const g = TOPO_GLYPH[n.type] || "•";
    return `<g class="topo-node" data-href="${nodeHref(n)}" transform="translate(${p.x},${p.y})">` +
           `<circle r="22" fill="#0d1b2a" stroke="${col}" stroke-width="3"/>` +
           `<text class="glyph" text-anchor="middle" dy="6">${g}</text>` +
           `<text class="topo-label" text-anchor="middle" y="40">${n.label || n.id}</text></g>`;
  }).join("");
  canvas.innerHTML =
    `<svg class="topo-svg" viewBox="${minX} ${minY} ${w} ${h}" preserveAspectRatio="xMidYMid meet">` +
    `<g data-topo-scene>${lines}${glyphs}</g></svg>`;
  _wireTopo(root, canvas.querySelector("svg"), { minX, minY, w, h });
  _renderTopoLegend(root, data.legend);
}

function _renderTopoLegend(root, legend) {
  const el = root.querySelector("[data-topo-legend]");
  const status = (legend && legend.status) || TOPO_COLORS;
  el.innerHTML = Object.entries(status).map(([k, c]) =>
    `<span class="topo-key"><i style="background:${c}"></i>${k}</span>`).join("");
}

function _wireTopo(root, svg, box) {
  let vb = { ...box };
  const apply = () => svg.setAttribute("viewBox", `${vb.minX} ${vb.minY} ${vb.w} ${vb.h}`);
  const zoom = f => { const cx = vb.minX + vb.w / 2, cy = vb.minY + vb.h / 2;
    vb.w *= f; vb.h *= f; vb.minX = cx - vb.w / 2; vb.minY = cy - vb.h / 2; apply(); };
  svg.addEventListener("wheel", e => { e.preventDefault(); zoom(e.deltaY > 0 ? 1.1 : 0.9); }, { passive: false });
  let drag = null;
  svg.addEventListener("pointerdown", e => { drag = { x: e.clientX, y: e.clientY }; });
  svg.addEventListener("pointermove", e => {
    if (!drag) return;
    const sx = vb.w / svg.clientWidth, sy = vb.h / svg.clientHeight;
    vb.minX -= (e.clientX - drag.x) * sx; vb.minY -= (e.clientY - drag.y) * sy;
    drag = { x: e.clientX, y: e.clientY }; apply();
  });
  svg.addEventListener("pointerup", () => { drag = null; });
  svg.addEventListener("pointerleave", () => { drag = null; });
  root.querySelector("[data-topo-zoom-in]").onclick = () => zoom(0.9);
  root.querySelector("[data-topo-zoom-out]").onclick = () => zoom(1.1);
  root.querySelector("[data-topo-fit]").onclick = () => { vb = { ...box }; apply(); };
  svg.querySelectorAll(".topo-node[data-href]").forEach(g => {
    const href = g.getAttribute("data-href");
    if (href) g.addEventListener("click", () => { location.href = href; });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("[data-topology]");
  if (!root) return;
  const load = () => fetch("/api/modules/topology", { credentials: "same-origin" })
    .then(r => r.status === 401 ? (location.href = "/", null) : (r.ok ? r.json() : null))
    .then(p => { if (p) renderTopology(root, p); })
    .catch(() => {});
  load();
  setInterval(() => { if (!document.hidden) load(); }, 60000);
});
```

- [ ] **Step 4: Append CSS** to `styles.css`:

```css
/* Topology map */
.topology{display:flex;flex-direction:column;height:calc(100vh - 160px)}
.topo-toolbar{display:flex;justify-content:space-between;align-items:center}
.topo-controls button{background:#1b263b;color:#e6edf3;border:1px solid #2a3b52;
  border-radius:6px;width:32px;height:32px;font-size:1rem;cursor:pointer;margin-left:4px}
.topo-canvas{flex:1;border:1px solid #1b263b;border-radius:8px;background:#0a1422;overflow:hidden}
.topo-svg{width:100%;height:100%;touch-action:none;cursor:grab}
.topo-svg:active{cursor:grabbing}
.topo-node{cursor:pointer}
.topo-node .glyph{font-size:20px}
.topo-node .topo-label{fill:#c7d3e0;font-size:12px}
.edge-label{fill:#7c8aa0;font-size:10px}
.topo-legend{display:flex;gap:1rem;padding:.5rem;color:#c7d3e0;font-size:.8rem}
.topo-key i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:4px;vertical-align:middle}
```

- [ ] **Step 5: `node -c topology.js`; run JS test; commit** `feat(topology): zero-dep SVG renderer + pan/zoom + legend`

---

### Task 5: full suite + push

- [ ] Run `python -m pytest -q` → all pass.
- [ ] Commit any remaining test files; push to main.
- [ ] Manual: pull + restart + open Topology tab.

---

## Self-Review

- **Spec coverage:** graph model (T1), fetch from cached sources (T2), page+template (T3), zero-dep SVG render + pan/zoom + legend + click-to-module (T4). Status palette, aggregated zones, switch leaves, traffic labels all in T1/T4. Covered.
- **Placeholders:** none — full code each step. (Task 1 notes a temporary `fetch` stub removed in Task 2 — explicit, not a placeholder.)
- **Type consistency:** `_build_graph(cluster, zones, aps, switches, traffic_by_mac)` and `{nodes,edges,legend,items}` consistent across T1/T2/T4; `layoutGraph(nodes,edges)` + `renderTopology(root,payload)` consistent in T4 and test.
