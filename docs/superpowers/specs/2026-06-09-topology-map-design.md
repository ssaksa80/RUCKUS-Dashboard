# Topology Map Tab — Design

Date: 2026-06-09
Status: Approved

## Problem

Operators want a single visual map of the RUCKUS estate — controller, zones,
APs, switch groups/stacks and switches — like the OpManager-style topology in
the reference screenshot (device icons, colored links, traffic labels, a
status legend, pan/zoom). The existing dashboard is all tables/KPIs; there is
no spatial view of how the fabric hangs together.

## Constraints

SmartZone's public API exposes only **per-device** neighbor data
(`GET /aps/{apMac}/operational/neighbor`, `GET /bgpevpn/neighbors/{switchId}`).
Drawing true physical L2 cabling would require ~800+ AP calls plus per-switch
calls — too slow for a live tab and only partially populated. Therefore the map
shows a **logical hierarchy**, built entirely from data the dashboard already
caches, not literal wiring.

The app is a no-build static-JS Flask app; the renderer must be **zero
dependency** (hand-rolled SVG), consistent with existing patterns.

## Goals

- A new `topology` tab rendering a hierarchy graph that visually resembles the
  reference: device-type icons/badges, status-colored links, traffic labels,
  legend, pan/zoom.
- Built from cached data with a small fixed number of bulk calls (no per-device
  crawl).
- Node click navigates to the relevant existing module page.
- Readable at a glance (~30–90 nodes), not 800 AP leaves.

## Non-Goals (YAGNI)

- Physical L2 / LLDP neighbor discovery (deferred; possible phase 2 opt-in).
- AP-leaf expansion under a zone (deferred).
- Force-directed/drag physics (deferred; deterministic radial layout instead).

## Graph model

`_build_graph(cluster, zones, aps, switches)` returns:

```
{
  "nodes": [ {id, label, type, status, meta} ... ],
  "edges": [ {source, target, status, label} ... ],
  "legend": {"status": {...}},
  "items": []          # keeps the ModuleSpec/table contract happy
}
```

Node types and rules:
- `controller` — one, center. status from clusterState (In_Service → online).
- `zone` — one per rkszone. APs are **aggregated**: label `"<name> (N APs)"`,
  `meta.ap_total` / `meta.ap_down`, status = `offline` if all down, `flagged`
  if some down, else `online`. (AP counts derived from the AP list grouped by
  zoneId — same approach as the zones module.)
- `group` / `stack` — one per switch group (or stack) derived from the switch
  list (`groupId`/`groupName`, `stackId`). status = worst child switch status.
- `switch` — one per switch, leaf under its group/stack. status from switch
  `status`; `meta.traffic_bytes` from the traffic module's MAC→bytes map.

Edges:
- `controller → zone` (neutral)
- `controller → group` (neutral)
- `group → switch`, `status` = switch status, `label` = humanBytes(traffic) if known.

Status palette (reused): online `#2ecc71`, flagged `#f1c40f`,
offline `#e74c3c`, unknown `#7c8aa0`.

## Rendering (`static/topology.js`, zero-dep SVG)

- **Layout** (`layoutGraph(nodes, edges)`): deterministic radial tiers.
  - Tier 0: controller at center `(0,0)`.
  - Tier 1: zones + groups spread on a ring (even angle slices).
  - Tier 2: switches fanned in a small arc around their parent group's angle.
  - Pure function returning `{id: {x, y}}`; unit-reasoned, no DOM.
- **Draw** (`renderTopology(root, payload)`): build `<svg viewBox>`; edges as
  `<line>` colored by status; nodes as `<g>` with a type glyph (emoji/text) +
  label; status drives node ring color.
- **Pan/zoom**: mutate `viewBox` — wheel to zoom, pointer-drag to pan, `+/−/fit`
  buttons.
- **Click**: node → `location.href` of its module
  (`zone→/m/zones`, `switch→/m/switches/<id>`, `group→/m/switch-groups`,
  `controller→/m/controller`).
- **Legend**: status swatches bottom-left.

## Wiring

- `modules/topology.py`: `fetch()` calls existing client helpers
  (`smartzone_get cluster/state`, `smartzone_paged_get rkszones`,
  `smartzone_query_paged query/ap`, `fetch_switches`, `traffic` usage) and
  returns the graph dict; `summary()` = `{nodes, online, offline, switches}`;
  `merge()` preserves `nodes`/`edges`/`legend` (default merge keeps only items).
  `requires_capabilities=(("GET","/cluster/state"),)`; `warmup=True`.
- `templates/topology.html`: extends base; SVG container + legend + zoom
  controls; loads `topology.js`.
- `routes/pages.py`: `/m/topology` special-cases to render `topology.html`
  (like `/m/overview`); it has no drill page.
- `static/styles.css`: graph + legend styles.
- Nav link auto-appears (registered module, group Cross-cutting).

## Data flow

```
poller → /api/modules/topology → fetch()/_build_graph → {nodes,edges,legend}
       → renderTopology() draws SVG (pan/zoom, click→module)
warmup → summary() feeds the tile + health bar
```

## Error handling

- Any upstream fetch failure inside `fetch()` is caught per-source; the graph is
  built from whatever resolved (controller-only map if zones/switches fail).
- The data route already wraps fetch in try/except → never 500.

## Testing

- `_build_graph`: nodes/edges/types/status from sample cluster+zones+aps+switches.
- `summary`: counts; `merge`: preserves nodes/edges.
- `layoutGraph` shape is deterministic (reasoned; JS covered by symbol presence +
  `node -c`).
- Route: `GET /m/topology` returns the SVG container markup.
- JS: `renderTopology` / `layoutGraph` symbols present in served `topology.js`.
