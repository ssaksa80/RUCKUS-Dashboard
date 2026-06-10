# Topology v2 — Interactive Map with Alerts, Drag & Zone Expansion

Date: 2026-06-10
Status: Approved

## Problem

Topology v1 renders the logical hierarchy but: labels overlap in dense fans,
nodes are fixed (no rearranging), there is no alerting on the map, zones are
opaque (no per-AP visibility), and nodes carry no detail without navigating
away. Operators want an OpManager-grade interactive map.

## Scope (all approved)

1. **Readability pack** — scaled rings, min angular gaps, label collision
   handling, node size by role/AP count, curved traffic-weighted edges,
   search/highlight.
2. **Alerts pack** — alarm badges, pulsing offline/critical rings, slide-in
   toasts on state transitions, click-to-focus.
3. **Drag & persist pack** — drag nodes (pinned across polls), server-side
   layout persistence shared by all DSO screens, Reset layout.
4. **Zone expand/collapse** — click a zone to fan out its APs (capped),
   offline-first.

## Design

### Server (`modules/topology.py`)

- `fetch(ctx)` gains:
  - **Meta enrichment**: switch nodes carry `meta = {ip, model, fw,
    traffic_bytes}`; zone nodes `{ap_total, ap_down}`; controller
    `{cluster_state}`.
  - **Alarm matching** (best-effort): pull `alert/alarm/list` (single page);
    match `sourceName` against node labels/ids (case-insensitive substring on
    the name part); matched nodes get `meta.alarm_count`.
  - **Zone expansion**: `ctx.filters["expand"]` = comma-separated zone ids.
    For each expanded zone, append that zone's AP leaf nodes
    (`type="ap"`, `id=apMac`, status normalized) capped at **60 per zone**,
    offline APs first; if more, append one `type="more"` summary node
    (`label="+N more APs"`). Edges `zone → ap`.
- Status escalation: a node with `alarm_count > 0` and status `online`
  becomes `flagged`.

### Layout persistence (`routes/topology_layout.py`)

- `GET /api/topology/layout` → `{positions: {nodeId: {x, y}}}` (empty if none).
- `POST /api/topology/layout` body `{positions: {...}}` — requires auth +
  CSRF header (`X-CSRF-Token`); body capped at 256 KB; positions validated
  (numeric x/y); stored as JSON at `<instance_path>/topology-layout-<host>.json`
  where host is derived from the first connection's api_base (sanitized
  `[a-zA-Z0-9._-]`).
- `DELETE /api/topology/layout` — removes the file (auth + CSRF).
- All three 401 when unauthenticated.

### Client (`static/topology.js` rewrite)

- **Layout v2** (`layoutGraph`):
  - `R1 = max(340, tier1Count * 70 / (2π))` so ring circumference fits nodes.
  - Switch fan: per-group arc with minimum angular gap `0.12 rad`; radius
    grows `R2 = R1 + 220`; AP fans (expanded zones) at `R1 + 180` around the
    zone's angle.
  - One-shot relaxation: 30 iterations; any node pair closer than
    `minDist = 56` gets pushed apart along their separation vector
    (controller excluded — stays centered).
  - Saved positions override computed ones; pinned (dragged) nodes are
    never relaid.
- **Rendering**:
  - Curved edges: quadratic bezier with perpendicular offset 12% of length;
    `stroke-width = 1.5 + min(4.5, log10(bytes+1) - 8)` clamped ≥1.5.
  - Node radius: controller 30, group/stack 24, switch 18,
    zone `16 + min(14, ap_total/40)`, ap 10, more 12.
  - Alarm badge: red circle + count at node top-right when `alarm_count > 0`.
  - Pulse: nodes with status offline (or alarm_count>0 and critical-ish) get
    `class="pulse"` — CSS keyframes animate the ring.
  - Labels: alternate above/below placement by index parity to reduce overlap.
- **Interaction**:
  - Pointer-drag ≥5px on a node = move node (updates positions map, marks
    pinned, re-renders edges); <5px pointerup = click.
  - Click: switch → `/m/switches/<id>`; controller → `/m/controller`;
    zone → toggle expansion (re-fetch with `expand=` param); ap → no-op;
    background drag = pan; wheel = zoom (unchanged).
  - Hover: tooltip div (absolute, near cursor) listing meta fields.
  - Search input: on input, nodes whose label/id contains the query get
    `highlight` class, all others `dimmed`; first match centered (viewBox
    recentre); empty query clears.
  - Toolbar buttons: 💾 Save layout (POST), ↺ Reset (DELETE + auto layout),
    +/−/fit (existing).
  - **Toasts**: keep previous poll's `{id: status, alarms}` map; on poll,
    transitions (online→offline, alarm_count increase, new offline node) emit
    a toast into `[data-topo-toasts]`; auto-dismiss 10 s; click → centre node.
- CSRF: POST/DELETE read the token from a `<meta name="csrf-token">` tag
  added to `topology.html`.

### Template (`topology.html`)

- Toolbar adds: search input `[data-topo-search]`, Save `[data-topo-save]`,
  Reset `[data-topo-reset]`.
- Adds `<meta name="csrf-token" content="{{ csrf_token }}">`, tooltip host
  `[data-topo-tooltip]`, toast host `[data-topo-toasts]`.

### CSS

- `.topo-node.pulse circle` keyframed ring; `.topo-badge`; `.topo-tooltip`
  card; `.topo-toast` slide-in/out; `.dimmed`/`.highlight` opacity states;
  search/save/reset toolbar styles.

## Error handling

- Alarm fetch failure → no badges, map still renders.
- Layout file corrupt/missing → auto layout.
- POST layout: invalid JSON/oversize/non-numeric → 400.
- Expanded zone with no APs → zone simply has no children.

## Non-goals

- Physical L2 cabling (unchanged from v1).
- Multi-select drag, undo history, animation physics.
- WebSocket push (polling diff is sufficient at 60 s).

## Testing

- Builder: meta enrichment, alarm matching → badge counts + escalation,
  expand cap (61 APs → 60 + "+1 more"), offline-first ordering.
- Layout API: 401 unauth; POST→GET roundtrip; DELETE clears; 400 on garbage.
- JS in Node: layout invariants — all nodes positioned, finite, min-distance
  respected after relaxation, saved positions honored.
- Symbol tests: new JS functions, CSS keyframes, template hooks.
