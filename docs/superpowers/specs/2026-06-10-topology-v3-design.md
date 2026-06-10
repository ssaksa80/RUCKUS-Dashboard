# Topology v3 — Subtree Drag, Collapse, Arrange, Edge Hover, Export

Date: 2026-06-10
Status: Approved

## Problem

Dragging a group node leaves its switches behind (edges stretch across the
map). Operators also want one-click cleanup, clutter control for large
fabrics, traffic detail without squinting at edge labels, and a way to export
the map for reports.

## Scope (client-only; no server changes)

1. **Subtree drag** — pointerdown on a group/zone collects its children (from
   edges) with offsets relative to the parent; during drag the whole subtree
   translates together and edges follow live.
2. **Re-fan on drop** — on release, children re-arrange in an arc centred on
   the direction pointing away from the controller at the parent's new
   position (radius ≈ 180, spread scales with count), followed by a local
   collision pass against nearby nodes (min separation 56). Parent and
   children become pinned so polls don't undo the move.
3. **Auto-arrange button** (🧲, `data-topo-arrange`) — re-renders with a fresh
   layout pass (saved/pinned anchors respected). Reset ↺ still clears pins.
4. **Group collapse** — single-click a group/stack toggles hiding its switch
   children (consistent with zone single-click expand). Collapsed groups get
   a dashed ring. Implemented as a pure filter
   `visibleGraph(nodes, edges, collapsed)` applied before layout/render;
   `topoState.nodes/edges` keep the full graph (toast diffing unaffected).
5. **Edge hover tooltip** — pointerover on an edge path shows
   `source ⇄ target · <traffic|status>` in the existing tooltip host.
6. **Export snapshot** (⬇, `data-topo-export`) — clones the live SVG, inlines
   background + label styles, serializes to a Blob, downloads
   `topology-YYYYMMDD-HHMM.svg`.

## Functions (testable in Node)

- `refanChildren(parentId, positions, nodes, edges, controllerId)` — mutates
  `positions` for the parent's children; returns the child ids. Away-angle =
  `atan2(parent.y - ctrl.y, parent.x - ctrl.x)`; children placed on the arc
  `parent + 180·(cos/sin)(away + offset)`; collision pass keeps ≥ 50 apart.
- `visibleGraph(nodes, edges, collapsedSet)` — returns `{nodes, edges}`
  excluding switch children of collapsed groups and their edges.

## Error handling

- Subtree drag on a node with no children degrades to single-node drag.
- Export failure (serializer) is silent — button flashes ✗.

## Testing

- Node-run: refan positions finite, children ≥ 50 apart, oriented away from
  controller (dot product of (child-parent) and (parent-ctrl) ≥ 0 for the
  middle child); visibleGraph removes exactly the collapsed subtree.
- Symbol tests: `refanChildren`, `visibleGraph`, `data-topo-arrange`,
  `data-topo-export`, dashed-ring CSS.
- Full suite green.
