# SP4 — Topology Redesign: Four Visualization Concepts (Design Spec)

Date: 2026-06-30
Status: Draft — concept exploration (no implementation)
Author: Architecture review
Scope: Visualization concept selection for the RUCKUS DSO dashboard topology page. This is a **design spec only** — no implementation code is included beyond tiny illustrative type signatures.

---

## 1. Problem & Current Behavior (grounded in code)

### 1.1 What exists today

The topology feature is a **logical hierarchy map**, not a physical L2 wiring diagram. This is a deliberate constraint stated at the top of the fetcher:

> "SmartZone's public API exposes only per-device neighbor data, so this builds a logical hierarchy from already-cached sources rather than physical L2 wiring."
> — `RUCKUS\ruckus_dashboard\modules\topology.py:1-4`

The server builds a three-tier graph in `_build_graph(...)` (`topology.py:115-216`):

- **Tier 0 — Controller**: a single root node from `cluster/state`. Status is `online` if `clusterState` is in the `_ONLINE` set, else `unknown` (`topology.py:128-131`).
- **Tier 1 — Zones and Switch Groups**: WLAN zones from `rkszones` (`topology.py:138-151`) and switch groups/stacks bucketed by `groupId`/`stackId` (`topology.py:181-196`). Each zone carries an aggregated AP count and a roll-up status (`online`/`flagged`/`offline`) computed from its child APs (`topology.py:142-148`).
- **Tier 2 — Leaves (APs / Switches)**: AP leaves are rendered **only when a zone is expanded** (`node_id in expand`, `topology.py:153`), capped at 60 with offline-first ordering and a synthetic `+N more` node (`topology.py:154-178`). Switch leaves are always rendered under their group with a live-traffic edge label (`topology.py:197-213`).

Status is normalized to one of four states — `online`, `flagged`, `offline`, `unknown` — via `_norm_status` (`topology.py:25-33`) and escalated to `flagged` when a node has active alarms (`_escalate`, `topology.py:125-126`). Alarm counts are matched by fuzzy name substring (`_alarms_for`, `topology.py:85-94`).

**Data sources pulled per poll** (each best-effort, wrapped in `_safe`, `topology.py:97-101`):
| Source | Client call | Purpose | `topology.py` |
|---|---|---|---|
| Cluster state | `smartzone_get("cluster/state")` | controller node | :37 |
| Zones | `smartzone_paged_get("rkszones")` | tier-1 zones | :38 |
| APs | `smartzone_query_paged("query/ap")` | AP leaves + zone roll-up | :39 |
| Switches | `fetch_switches(...)` | switch groups + leaves | :40 |
| Traffic | `switch_manager_query("traffic/top/usage")` | edge weights | :104-112 |
| Alarms | `smartzone_post("alert/alarm/list")` | badges / escalation | :69-82 |
| Client RSSI | `smartzone_query_paged("query/client")` | per-AP avg signal — **only when a zone is expanded** | :54-66 |

The output envelope is `{nodes, edges, legend, items}` (`topology.py:215-216`). `merge` is overridden to preserve the single-controller graph rather than the default item-concatenation (`topology.py:238-243`).

### 1.2 The renderer

`static\topology.js` is a **zero-dependency SVG renderer** (~667 lines). Key facts:

- **Layout** is a hand-rolled **radial tier layout** (`layoutGraph`, `topology.js:76-133`): controller at origin, tier-1 on a ring of radius `R1 = max(340, tier1.count·70 / 2π)`, leaves fanned in arcs facing outward, followed by a fixed 30-iteration O(n²) collision-relaxation pass with `minDist = 56` (`topology.js:115-131`).
- **Interaction** is a single pointer state machine (`_wireTopo`, `topology.js:416-553`): background pan, node drag with **subtree drag** (parents carry children, `topology.js:435-463`), re-fan on drop (`refanChildren`, `topology.js:135-169`), wheel zoom (`topology.js:420-425`), and click semantics — switch/controller navigate via `nodeHref` (`topology.js:223-227`), zones expand by re-fetching the server with `?expand=` (`topology.js:492-496, 644-654`), groups collapse locally via `visibleGraph` (`topology.js:171-179, 498-502`).
- **Live traffic rate** is derived client-side from cumulative byte counters: `updateRates` converts deltas to bps with baseline-hold semantics (`topology.js:31-56`), edge width keys off magnitude hints (`edgeWidth`, `topology.js:237-243`).
- **State / alarm awareness**: `diffAndToast` compares the previous poll's `{status, alarms}` and raises toast notifications on offline transitions and new alarms (`topology.js:245-273`); offline/alarmed nodes pulse (`.topo-node.pulse`, `styles.css:181-186`); alarm badges drawn as a red circle (`topology.js:368-371`).
- **Persistence**: positions saved per-controller-host as `{nodeId:{x,y}}` JSON in the instance folder via `POST/GET/DELETE /api/topology/layout` (`routes\topology_layout.py:23-79`), keyed by sanitized controller netloc (`topology_layout.py:23-31`), capped at 2000 nodes / 256 KB (`topology_layout.py:19-20, 58`).
- **Polling**: full refetch every 60 s when the tab is visible (`topology.js:665`), matching `POLL_SECONDS = 60` (`topology.py:15`).
- **Export**: clones the live SVG, inlines styles, downloads `topology-YYYYMMDD-HHMM.svg` (`topology.js:611-641`).
- **Host markup**: `templates\topology.html` provides `[data-topo-canvas]`, toolbar buttons (`data-topo-arrange/export/save/reset/zoom-in/zoom-out/fit`), `[data-topo-legend]`, `[data-topo-tooltip]`, `[data-topo-toasts]` (`topology.html:7-25`). Served by `pages.py:32-36`.

The v3 spec (`docs\superpowers\specs\2026-06-10-topology-v3-design.md`) added subtree drag, collapse, auto-arrange, edge hover, and export — all client-only. The current renderer is the implementation of that spec.

### 1.3 Why redesign — the problems

1. **The radial map does not scale visually.** Beyond ~30 tier-1 nodes or an expanded large zone, the ring + O(n²) relaxation produces overlap and label collisions; the 60-AP cap (`topology.py:156`) and `+N more` node are tacit admissions that the layout cannot show a full zone. Edge labels and glyphs crowd at the controller hub.
2. **It answers "what is connected to what," not "what is wrong right now."** For a DSO **wall display** (the primary consumer — `body.dso-mode`, `styles.css:155-156`), the operator standing across the room needs *health at a glance*, not a hierarchy they must zoom and pan to read. Today, health is encoded only as ring color + pulse on individual small nodes.
3. **No spatial/geographic context.** Zones and APs have no location on the map; an operator cannot see "Site B is dark." (Constraint: AP/zone rows in this codebase carry **no lat/long** — confirmed by absence of any latitude/longitude/gps field across `clients\` except IP/MAC fields, `smartzone.py:376-413`, `ruckus_one.py:75-225`.)
4. **Traffic is shown but not as flow.** Edge labels carry bps (`topology.js:339-357`), but there is no view that answers "where is the bandwidth going" — uplinks, hot switches, congested paths.
5. **Interaction is per-node.** Expansion is one-zone-at-a-time round-trips to the server (`topology.js:644-654`); there is no time dimension, no incident triage flow, no "show me only problems" filter.

The redesign question is therefore **not** "make the radial map prettier" — it is "what is the right *primary* visualization for a 24/7 NOC wall, plus a *secondary* analysis view, given the data the controllers actually expose."

---

## 2. The Four Concepts

Each concept below specifies: **what it shows best**, **interaction model**, **data needs** (and whether they exist today), **rendering tech** (zero-dep SVG vs. a library), and **DSO wall-display fit**.

A shared design fact governs all four: the controller exposes **logical hierarchy + status + alarms + cumulative traffic**, and **no geo coordinates and no physical L2 link table** (`topology.py:1-4`; geo-field absence confirmed in §1.3). Concepts are ranked by how well they fit *that* reality, not an idealized data model.

---

### Concept A — NOC Dark-Canvas "Health Glow" Wall (status-first)

**What it shows best.** Aggregate fleet health, readable across a room. The same logical hierarchy as today, but re-skinned and re-prioritized so the dominant visual signal is **health, not topology**. Nodes become health-weighted: a node's *size*, *glow intensity*, and *position prominence* are driven by problem severity, not by tree depth. Healthy zones recede into a calm dim field; a zone with offline APs blooms a red halo proportional to `ap_down`; alarm badges and pulse become the loudest element. A persistent top "status ribbon" summarizes counts (online / flagged / offline / alarms) — a scaled-up version of `summary()` (`topology.py:230-235`).

**Interaction model.** Optimized for *passive viewing first, drill second*:
- Default: ambient mode — slow auto-rotate/breathe of the canvas, no operator needed. Worst-N problem nodes auto-labeled; healthy nodes unlabeled.
- "Triage" affordance: a single toggle (`Problems only`) hides all-green subtrees (reuse the `visibleGraph` filter pattern, `topology.js:171-179`) so the wall shows only what's broken.
- Click a glowing node → existing drill navigation (`nodeHref`, `topology.js:223-227`) or zone expand (`topology.js:492-496`).
- Toasts on transition already exist (`diffAndToast`, `topology.js:245-260`) and become the primary "something just changed" cue.

**Data needs.** **100% satisfied by current fetch.** Status (`topology.py:142-148`), `ap_down`/`ap_total` (`topology.py:149-150`), `alarm_count` (`topology.py:146,160,203`). No new controller calls. Optionally enrich with a short rolling history of `summary()` for a sparkline ribbon (client-side ring buffer; no API change).

**Rendering tech.** **Keep zero-dep SVG.** This is an incremental evolution of the existing renderer: new color/glow theme (CSS `filter: drop-shadow` + radial gradients, extending `styles.css:181-204`), severity-weighted `nodeRadius` (`topology.js:68-74`), a status ribbon partial, and a "problems-only" filter. SVG filters and CSS keyframes are sufficient; no canvas/WebGL needed at DSO node counts.

**DSO wall fit.** **Excellent — purpose-built for it.** This is the concept that most directly answers "the operator is 4 m away." Lowest engineering risk because it reuses the entire data path and most of the renderer.

**Weakness.** Still fundamentally the radial logical map underneath, so it inherits the layout-scaling ceiling for very large fabrics (mitigated, not solved, by problems-only filtering).

---

### Concept B — Geographic / Site Map (spatial)

**What it shows best.** "Where, physically, is the problem." Zones (and optionally sites/venues) placed on a real map or a floor/campus plan, each rendered as a health-colored marker or heat region; clusters of offline APs read as a dark patch over a building.

**Interaction model.** Pan/zoom map (native to any map lib); click a site marker → expand to that site's zone/AP detail (reusing the existing expand round-trip, `topology.js:644-654`); marker clustering at low zoom that aggregates child status the way zones already aggregate AP status (`topology.py:142-148`).

**Data needs — THIS IS THE BLOCKER.** Requires per-zone or per-AP **latitude/longitude**, which **does not exist in the current data path**. Searched `clients\` for latitude/longitude/gps/geo/coordinate — only IP/MAC fields are present (`smartzone.py:376-413`, `ruckus_one.py:75-225`). SmartZone *can* hold AP GPS and zone/venue location in some deployments, but: (a) it is frequently unpopulated in real installs; (b) fetching it means new client calls + new capability gates (`requires_capabilities`, `topology.py:250`); (c) a fallback "manual placement" mode would require an admin to pin every site — heavy operational cost. A floor-plan variant additionally needs uploaded plan images + a calibration UI.

**Rendering tech.** Would require **adopting a library** (e.g., a tile-map renderer) or a substantial custom SVG map projection layer — a real dependency-policy departure from the current zero-dep stance, plus offline-tile concerns for an air-gapped DSO network (the dashboard runs against private controllers behind an SSRF allowlist, `net/allowlist.py`; external map tiles may be unreachable).

**DSO wall fit.** **High *if* data existed** — a geographic dark-map is the canonical NOC wall view. But given no coordinates, it is the **highest-risk, lowest-certainty** concept and is effectively blocked on a data-availability question (see Open Questions).

---

### Concept C — Live Force-Directed Graph (organic / exploratory)

**What it shows best.** Emergent structure and clustering of a flat, relationship-rich graph — useful when you do *not* know the hierarchy ahead of time and want dense interconnection to self-organize. Nodes repel, edges act as springs, the layout finds equilibrium continuously.

**Interaction model.** Grab-and-fling nodes, watch the graph settle; hover to highlight neighborhoods; the simulation runs continuously so new/changed nodes animate in.

**Data needs.** Satisfied by current data (same nodes/edges as today). **But the data is a strict tree** (controller → tier-1 → leaf; every edge has a single parent, `topology.py:151,196,211`). A force simulation on a tree produces a wobbly radial blob that conveys *less* than today's deterministic radial layout — and it never sits still, which is actively bad on a wall (motion with no information).

**Rendering tech.** A continuous force simulation at hundreds–thousands of nodes effectively forces **adopting a library** (and likely a canvas/WebGL renderer) for acceptable frame rates — again a dependency departure. The current code already has a *deterministic* one-shot relaxation (`topology.js:115-131`) that gives 80% of the visual benefit without the cost.

**DSO wall fit.** **Poor.** Perpetual motion is distracting on a 24/7 display; non-deterministic placement means the map "looks different every time," defeating operator muscle memory; physics jitter reads as instability. Force-directed shines for *ad-hoc analysis of unknown graphs*, which is not the DSO wall job.

---

### Concept D — Layered Traffic-Flow / Sankey (flow analysis)

**What it shows best.** "Where is the bandwidth going." A left-to-right layered diagram — Controller → Groups/Zones → Switches/APs — where **band thickness encodes throughput**. Instantly surfaces the heavy uplinks, the hot switch group, the zone consuming the most traffic. This reframes the *traffic* data the system already computes (`updateRates`, `topology.js:31-56`; `_traffic_map`, `topology.py:104-112`) from thin edge labels into the primary visual variable.

**Interaction model.** Hover a band → exact rate + endpoints (the edge-hover tooltip already exists, `topology.js:522-538`); click a node-bar → drill; optional time-range selector to compare flow now vs. earlier. Layered DAG layout is deterministic and stable (good for muscle memory).

**Data needs.** Traffic edge weights exist today (`topology.py:200-213`, client rates `topology.js:46-48`). For a *richer* Sankey, port-level throughput is available but unused: `switch/ports/summary`, `switch/ports/details`, `traffic/top/portusage` (`clients\switchm.py:70-76`) — these are already in the SwitchM capability list, so enabling them is incremental, not a new integration. **Caveat:** SmartZone reports *cumulative* counters refreshed only periodically, so "live flow" is a smoothed rate, not instantaneous (the renderer already documents this baseline-hold behavior, `topology.js:31-55`); the Sankey must visually honor that (e.g., "measuring…" state, mirroring `topology.js:530-531`).

**Rendering tech.** A layered/Sankey ribbon layout is **achievable in zero-dep SVG** (cubic-Bézier ribbons are the same primitive as the existing `edgePath`, `topology.js:229-235`; layered node placement is simpler than the current radial+relaxation math). No library strictly required, though a layout helper would be written from scratch.

**DSO wall fit.** **Good as a secondary/analysis view, mediocre as the always-on primary.** Flow is a *diagnostic* lens (capacity planning, congestion hunting) more than an *at-a-glance health* lens — a fully-green network still shows fat bands, so "all bands thick" does not mean "all healthy." Best paired with a status-first primary.

---

## 3. Comparison & Trade-offs

| Concept | Shows best | New controller data? | Rendering | DSO wall fit | Eng. risk |
|---|---|---|---|---|---|
| **A. NOC Health-Glow** | Fleet health at a glance | **None** | Keep zero-dep SVG (evolve) | **Excellent** | **Low** |
| **B. Geo / Site map** | Physical "where" | **Yes — lat/long absent today** | Adopt map lib / tiles | High *if data existed* | **High / blocked** |
| **C. Force-directed** | Unknown-graph structure | None (but data is a tree) | Adopt lib (canvas/WebGL) | **Poor** (perpetual motion) | Medium |
| **D. Traffic Sankey** | Bandwidth flow / congestion | Optional (port stats exist, unused) | Zero-dep SVG feasible | Good (analysis), weak as primary | Medium |

**Reading the table:** the dominant axis for a DSO wall is *"answers health at a glance with data we already have."* A wins it outright. B is the most visually compelling NOC archetype but is gated on a coordinate-availability question the code says is currently unmet. D is the strongest *complement* to A because it reuses the traffic pipeline and a deterministic layout to add the one analytical lens A lacks. C is the weakest fit for this specific job.

---

## 4. Recommendation

**Primary: Concept A — NOC Dark-Canvas Health-Glow wall.**
**Secondary: Concept D — Layered Traffic-Flow / Sankey, offered as a *view toggle* alongside A.**

Rationale:
- **A** is the lowest-risk, highest-fit answer to the actual primary consumer (a 24/7 wall display), it requires **zero new controller calls**, and it is an *evolution* of the existing renderer rather than a rewrite — preserving the drill/expand/persist/toast machinery that already works and is test-covered.
- **D** adds the single analytical capability A cannot provide (flow/congestion), reuses the existing traffic-rate pipeline (`topology.js:31-56`) and edge-hover tooltip (`topology.js:522-538`), and is feasible in zero-dep SVG — so it stays within the project's dependency posture.
- The two share one data fetch and one host page, differing only in layout + visual encoding, which makes a **`supports_views`-style toggle** (`graph` ↔ `flow`) the natural seam — the view-toggle markup already exists in the generic module shell (`module.html:21-22`).
- **B** is explicitly **deferred** pending the geo-data Open Question; if/when per-AP coordinates prove reliably available, B becomes the strongest *future* primary and can reuse A's health encoding as map-marker styling. **C** is **declined** for the wall (perpetual motion, non-determinism); it could survive only as an optional "explore" toy, which is not worth the dependency.

This gives the DSO one calm, glanceable health wall plus one deliberate flow-analysis lens — both deterministic, both zero-dependency, both built on data the controllers already return.

---

## 5. Design of the Recommended Approach (A primary + D secondary)

### 5.1 Component overview

```
templates/topology.html  ──► hosts canvas + toolbar + NEW view toggle [graph|flow] + NEW status ribbon
static/topology.js        ──► dispatches on active view:
        ├── renderHealthWall(...)   (Concept A — evolves current radial render)
        └── renderFlow(...)         (Concept D — new layered/Sankey render)
   shared: loadTopology(), state, drill/expand, layout persistence, toasts
modules/topology.py        ──► fetch() unchanged for A; OPTIONAL flow enrichment for D (port stats)
routes/topology_layout.py  ──► unchanged (positions still persist; flow view is deterministic, no pins)
static/styles.css          ──► NEW glow/ribbon theme + flow-ribbon styles
```

The **server contract stays the envelope it is today** (`{nodes, edges, legend, items}`, `topology.py:215`). Both views consume the same payload; D may consume an *additional optional* `flow`/port-rate field when available, defaulting gracefully to the existing edge weights.

### 5.2 Data flow

1. **Page load** (`topology.js:656-665`): fetch saved layout, then `loadTopology(root)` — unchanged.
2. **Fetch** `GET /api/modules/topology[?expand=…]` (`topology.py:36-51`) — unchanged for A.
3. **View dispatch** (new): a small `topoState.view` (`"graph"` default | `"flow"`) selects the renderer inside `renderTopology` (`topology.js:310`). Health-glow is the default `graph` render with the new theme; `flow` calls the layered renderer.
4. **A render**: same nodes/edges; severity-weighted sizing/glow; `Problems only` filter reuses `visibleGraph`-style filtering (`topology.js:171-179`); status ribbon reads `summary()` counts (`topology.py:230-235`) recomputed client-side from nodes.
5. **D render**: layered DAG placement (controller column → tier-1 column → leaf column) using the same node list; band thickness from `topoState.rates` (`topology.js:31-56`) / edge labels; ribbons drawn with the existing Bézier primitive (`edgePath`, `topology.js:229-235`).
6. **Poll** every 60 s (`topology.js:665`) re-runs the active renderer.

### 5.3 Interfaces (illustrative signatures only — no implementation)

```text
# client (static/topology.js) — new/changed pure-ish functions, Node-testable:
renderHealthWall(root, data)            # Concept A layout+paint (evolves renderTopology)
renderFlow(root, data)                  # Concept D layered Sankey paint
layoutLayered(nodes, edges) -> positions   # deterministic column layout (replaces radial for flow)
healthWeight(node) -> number            # severity → size/glow scalar (extends nodeRadius)
filterProblemsOnly(nodes, edges) -> {nodes, edges}   # green-subtree hiding (pattern of visibleGraph)
setView(root, "graph"|"flow")           # toggle + re-render

# server (modules/topology.py) — OPTIONAL, additive, only if D-rich is approved:
_port_flow(ctx) -> dict                 # best-effort port throughput from switchm (switchm.py:70-76)
# fetch() would attach an optional "flow" key; absence => D falls back to existing edge weights.
```

No change to the `/api/topology/layout` interface (`topology_layout.py:34-79`). No change to `ModuleSpec` other than possibly advertising `supports_views=("graph","flow")` (`topology.py:251`).

### 5.4 Error handling

- **Per-source failures** stay best-effort via `_safe` (`topology.py:97-101`); a missing source degrades a tier, never the whole map — unchanged.
- **Empty graph**: existing "No topology data." guard (`topology.js:315`) covers both views.
- **Flow with no traffic data**: bands fall back to uniform thin ribbons + a "measuring…" tooltip state, mirroring the existing idle/measuring copy (`topology.js:530-531`); never render NaN widths (guard like `fmtRate`'s `isFinite` check, `topology.js:23`).
- **View toggle on stale state**: re-render is idempotent from `topoState.nodes/edges`; `rerenderFromState` already exists (`topology.js:216-221`).
- **Persistence**: flow view is deterministic and does **not** write pins, so `topology_layout.py` limits (`:19-20,58`) are untouched; graph-view pins continue to persist as today.
- **Auth/CSRF**: layout writes still go through `validate_csrf()` (`topology_layout.py:51,74`); 401 handling in `loadTopology` (`topology.js:649`) unchanged.

### 5.5 Testing

Follows the existing Node-symbol + pytest pattern used by the v3 spec (`2026-06-10-topology-v3-design.md:51-57`):
- **Node-run unit**: `layoutLayered` produces finite, column-separated, deterministic positions (same input → identical output); `healthWeight` monotonic in severity (offline ≥ flagged ≥ online); `filterProblemsOnly` removes exactly all-green subtrees and their edges; `renderFlow` never emits non-finite ribbon widths.
- **Symbol tests**: presence of `renderHealthWall`, `renderFlow`, `layoutLayered`, `setView`, `[data-topo-view]` toggle, and new CSS classes (glow/ribbon/status-ribbon), mirroring the v3 symbol-test approach.
- **Server (pytest)**: if D-rich enrichment is built, `_port_flow` is best-effort (returns `{}` on client error) and `fetch()` output still validates against the `{nodes, edges, legend, items}` shape; existing topology tests stay green.
- **Regression**: HTML-escaping of controller-derived strings remains enforced (the `_esc` usage throughout render, e.g. `topology.js:354,376`) — keep the escaping test passing.
- **Full suite** green (currently 301 tests).

### 5.6 Concrete files / functions that change

| File | Change |
|---|---|
| `RUCKUS\ruckus_dashboard\static\topology.js` | Add `renderHealthWall`, `renderFlow`, `layoutLayered`, `healthWeight`, `filterProblemsOnly`, `setView`; dispatch in `renderTopology` (`:310`); status-ribbon update from node counts. |
| `RUCKUS\ruckus_dashboard\templates\topology.html` | Add `[data-topo-view]` graph/flow toggle and `Problems only` toggle to the toolbar (`:8-19`); add a status-ribbon element. |
| `RUCKUS\ruckus_dashboard\static\styles.css` | Add glow/gradient theme, status-ribbon styles, and flow-ribbon/column styles (extend `:158-204`). |
| `RUCKUS\ruckus_dashboard\modules\topology.py` | **Optional / D-rich only**: add `_port_flow(ctx)` and attach optional `flow` key in `fetch()` (`:36-51`); advertise `supports_views=("graph","flow")` (`:251`). |
| `RUCKUS\ruckus_dashboard\routes\topology_layout.py` | **No change.** |
| Tests | New Node-symbol + pytest cases per §5.5. |

### 5.7 Phasing

1. **Phase 1 (A, no server change):** re-theme to health-glow, add status ribbon + problems-only filter. Ships value immediately, zero API risk.
2. **Phase 2 (D, client-only):** add `flow` view using existing edge weights + client rates and a zero-dep layered layout.
3. **Phase 3 (D-rich, optional):** enrich flow with port-level throughput from SwitchM (`switchm.py:70-76`) behind capability gating.
4. **Phase 4 (B, deferred):** revisit geographic map only if the geo-data Open Question resolves favorably.

---

## 6. Open Questions

1. **Geo data (gates Concept B):** Do the target DSO SmartZone/RUCKUS One deployments reliably populate AP GPS and/or zone/venue coordinates? If yes, by which API and is it within the SSRF allowlist? If only sometimes, is manual site-pinning acceptable operational cost? Without a "yes" here, B stays deferred.
2. **Wall vs. desk consumer split:** Is the topology page primarily a passive wall display (`dso-mode`, `styles.css:155-156`), an interactive operator tool, or both on the same screen? This decides whether ambient auto-motion in A is desirable or a distraction.
3. **Traffic semantics for D:** Is the periodically-refreshed cumulative counter (baseline-hold rate, `topology.js:31-55`) accurate enough to label bands as "throughput," or should D explicitly frame bands as "relative usage" to avoid implying real-time precision?
4. **Dependency policy:** Is the project willing to relax zero-dependency for any concept (relevant only if B's map or C's force layout were ever pursued), given the air-gapped/allowlisted network posture? The recommendation (A+D) assumes **no** — stay zero-dep.
5. **Scale ceiling:** What is the realistic upper bound on zones/switches/APs per controller in production? This sets whether A's problems-only filter is sufficient or whether server-side aggregation/LOD is eventually needed (the 60-AP cap at `topology.py:156` is the current stopgap).
6. **View persistence:** Should the chosen view (graph vs. flow) and the problems-only toggle persist per user/controller (reusing the layout-persistence pattern, `topology_layout.py`), or reset to the health-wall default on every load?
