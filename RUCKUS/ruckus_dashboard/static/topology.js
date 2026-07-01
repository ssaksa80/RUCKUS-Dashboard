"use strict";

const TOPO_COLORS = { online: "#2ecc71", flagged: "#f1c40f", offline: "#e74c3c", unknown: "#7c8aa0" };
const TOPO_GLYPH = { controller: "🛰️", zone: "📶", group: "🗄️", stack: "🗄️", switch: "🔀", ap: "📡", more: "⋯" };
const NODE_R = { controller: 30, group: 24, stack: 24, switch: 18, ap: 10, more: 12 };

const topoState = {
  nodes: [], edges: [],   // full graph (collapse filtering happens at render)
  visEdges: [],           // edges actually rendered (collapse-filtered)
  positions: {},          // {id: {x, y}} — current layout
  saved: {},              // server-persisted positions
  pinned: new Set(),      // dragged this session — never relaid
  expanded: new Set(),    // zone ids fanned out
  collapsed: new Set(),   // group ids with switches tucked away
  prev: {},               // {id: {status, alarms}} from previous poll
  prevTraffic: {},        // {switchId: {bytes, t}} for live-rate deltas
  rates: {},              // {switchId: bps} — real-time throughput
  legend: null, root: null,
  problemsOnly: false,    // "Problems only" filter active
  view: "graph",          // active view: "graph" (health wall) | "flow"
  vb: null, box: null,    // viewBox state
};

function fmtRate(bps) {
  let v = Number(bps);
  if (!isFinite(v) || v < 0) return "";
  const units = ["bps", "Kbps", "Mbps", "Gbps", "Tbps"];
  let i = 0;
  while (v >= 1000 && i < units.length - 1) { v /= 1000; i += 1; }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function updateRates(nodes) {
  // Cumulative byte counters → bps. SmartZone refreshes the traffic aggregate
  // only periodically, so the baseline is kept until the counter actually
  // moves and the rate is averaged over the real elapsed window. An unchanged
  // counter keeps the last computed rate instead of collapsing to 0.
  const now = Date.now() / 1000;
  nodes.forEach(n => {
    if (n.type !== "switch" || !n.meta || n.meta.traffic_bytes == null) return;
    const bytes = Number(n.meta.traffic_bytes);
    const prev = topoState.prevTraffic[n.id];
    if (!prev) {
      topoState.prevTraffic[n.id] = { bytes, t: now };
      return;
    }
    const dt = now - prev.t;
    if (dt < 5) return;
    if (bytes > prev.bytes) {
      topoState.rates[n.id] = ((bytes - prev.bytes) * 8) / dt;
      topoState.prevTraffic[n.id] = { bytes, t: now };
    } else if (bytes < prev.bytes) {
      // Counter reset (reboot) — restart the baseline.
      topoState.prevTraffic[n.id] = { bytes, t: now };
    }
    // bytes unchanged → keep baseline + last rate until the counter ticks.
  });
}

function _esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function _csrf() {
  const m = document.querySelector('meta[name="csrf-token"]');
  return m ? m.content : "";
}

function nodeRadius(n) {
  if (n.type === "zone") {
    const total = (n.meta && n.meta.ap_total) || 0;
    return 16 + Math.min(14, total / 40);
  }
  return NODE_R[n.type] || 16;
}

const SEVERITY_BASE = { offline: 0.7, flagged: 0.45, online: 0.18, unknown: 0.05 };

function healthWeight(n) {
  // Severity scalar in [0,1] driving health-glow size/glow. Monotonic in
  // status (offline > flagged > online > unknown); within a status, grows
  // with the fraction of down APs and with active alarm count. Never NaN.
  const base = SEVERITY_BASE[n.status] != null ? SEVERITY_BASE[n.status] : SEVERITY_BASE.unknown;
  const meta = n.meta || {};
  const total = Number(meta.ap_total) || 0;
  const down = Number(meta.ap_down) || 0;
  const downFrac = total > 0 ? down / total : 0;
  const alarms = Number(meta.alarm_count) || 0;
  const alarmBoost = Math.min(0.2, alarms * 0.05);
  const w = base + downFrac * 0.25 + alarmBoost;
  return Math.max(0, Math.min(1, w));
}

function nodeGlowStyle(n) {
  // Inline style string for a node <g>: exposes the severity-driven glow
  // strength as the CSS var --glow (0..1), consumed by .topo-node.glow.
  const w = healthWeight(n);
  return `--glow:${w.toFixed(3)}`;
}

function ribbonCounts(nodes) {
  // Live fleet tally for the status ribbon. Alarms summed across all nodes.
  const c = { online: 0, flagged: 0, offline: 0, alarms: 0, total: nodes.length };
  nodes.forEach(n => {
    if (n.status === "online") c.online += 1;
    else if (n.status === "flagged") c.flagged += 1;
    else if (n.status === "offline") c.offline += 1;
    c.alarms += (n.meta && Number(n.meta.alarm_count)) || 0;
  });
  return c;
}

function updateStatusRibbon(root, nodes) {
  const el = root.querySelector("[data-topo-ribbon]");
  if (!el) return;
  const c = ribbonCounts(nodes);
  el.innerHTML =
    `<span class="rib-item rib-online"><b>${c.online}</b> online</span>` +
    `<span class="rib-item rib-flagged"><b>${c.flagged}</b> flagged</span>` +
    `<span class="rib-item rib-offline"><b>${c.offline}</b> offline</span>` +
    `<span class="rib-item rib-alarms"><b>${c.alarms}</b> alarms</span>` +
    `<span class="rib-item rib-total"><b>${c.total}</b> nodes</span>`;
}

function layoutGraph(nodes, edges, saved, pinned) {
  saved = saved || {}; pinned = pinned || new Set();
  const pos = {};
  const fixed = id => saved[id] || (pinned.has(id) && topoState.positions[id]);

  pos["controller"] = fixed("controller") ? { ...(saved["controller"] || topoState.positions["controller"]) } : { x: 0, y: 0 };

  const tier1 = nodes.filter(n => n.type === "zone" || n.type === "group" || n.type === "stack");
  const R1 = Math.max(340, (tier1.length * 70) / (2 * Math.PI));
  tier1.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, tier1.length);
    const f = fixed(n.id);
    pos[n.id] = f ? { ...f, angle: a } : { x: Math.cos(a) * R1, y: Math.sin(a) * R1, angle: a };
  });

  const childrenOf = {};
  edges.forEach(e => { (childrenOf[e.source] = childrenOf[e.source] || []).push(e.target); });
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));

  const fan = (parentId, kidTypes, R2) => {
    const base = (pos[parentId] && pos[parentId].angle) || 0;
    const kids = (childrenOf[parentId] || []).filter(id => byId[id] && kidTypes.includes(byId[id].type));
    const spread = Math.max(0.3, Math.min(1.4, kids.length * 0.12));
    kids.forEach((id, i) => {
      const f = fixed(id);
      if (f) { pos[id] = { ...f }; return; }
      const off = kids.length > 1 ? (i / (kids.length - 1) - 0.5) * spread : 0;
      const a = base + off;
      pos[id] = { x: Math.cos(a) * R2, y: Math.sin(a) * R2 };
    });
  };
  nodes.filter(n => n.type === "group" || n.type === "stack").forEach(g => fan(g.id, ["switch"], R1 + 220));
  nodes.filter(n => n.type === "zone").forEach(z => fan(z.id, ["ap", "more"], R1 + 180));

  // One-shot relaxation: push apart any pair closer than minDist. Controller,
  // saved and pinned nodes stay put; everything else shuffles around them.
  const minDist = 56;
  const movable = id => id !== "controller" && !fixed(id);
  const ids = nodes.map(n => n.id).filter(id => pos[id]);
  for (let iter = 0; iter < 30; iter++) {
    let moved = false;
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = pos[ids[i]], b = pos[ids[j]];
        let dx = b.x - a.x, dy = b.y - a.y;
        let d = Math.hypot(dx, dy);
        if (d >= minDist) continue;
        if (d < 1e-3) { dx = 1; dy = 0; d = 1; }
        const push = (minDist - d) / 2;
        const ux = dx / d, uy = dy / d;
        if (movable(ids[i])) { a.x -= ux * push; a.y -= uy * push; moved = true; }
        if (movable(ids[j])) { b.x += ux * push; b.y += uy * push; moved = true; }
      }
    }
    if (!moved) break;
  }
  return pos;
}

const FLOW_COL_X = { 0: 0, 1: 520, 2: 1040 };
const FLOW_ROW_GAP = 84;

function flowColumn(type) {
  if (type === "controller") return 0;
  if (type === "zone" || type === "group" || type === "stack") return 1;
  return 2; // switch | ap | more
}

function layoutLayered(nodes, edges) {
  // Deterministic left→right layered DAG: column by tier, evenly spaced rows
  // within a column (centred vertically). Stable ordering = input order, so
  // identical input yields identical output. All coordinates finite.
  void edges; // edges drive ribbons in renderFlow, not placement
  const cols = { 0: [], 1: [], 2: [] };
  nodes.forEach(n => { cols[flowColumn(n.type)].push(n); });
  const pos = {};
  Object.keys(cols).forEach(k => {
    const list = cols[k];
    const x = FLOW_COL_X[k];
    const h = (list.length - 1) * FLOW_ROW_GAP;
    list.forEach((n, i) => { pos[n.id] = { x, y: i * FLOW_ROW_GAP - h / 2 }; });
  });
  return pos;
}

function refanChildren(parentId, positions, nodes, edges, controllerId) {
  // Re-arrange a dropped parent's children in an arc facing away from the
  // controller at the parent's new position, then push siblings ≥50 apart.
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  const kids = edges.filter(e => e.source === parentId && byId[e.target])
                    .map(e => e.target);
  const p = positions[parentId];
  const c = positions[controllerId || "controller"] || { x: 0, y: 0 };
  if (!p || !kids.length) return kids;
  const away = Math.atan2(p.y - c.y, p.x - c.x);
  const spread = Math.max(0.5, Math.min(2.2, kids.length * 0.18));
  const R = 180;
  kids.forEach((id, i) => {
    const off = kids.length > 1 ? (i / (kids.length - 1) - 0.5) * spread : 0;
    const a = away + off;
    positions[id] = { x: p.x + Math.cos(a) * R, y: p.y + Math.sin(a) * R };
  });
  for (let iter = 0; iter < 20; iter++) {
    let moved = false;
    for (let i = 0; i < kids.length; i++) {
      for (let j = i + 1; j < kids.length; j++) {
        const a = positions[kids[i]], b = positions[kids[j]];
        let dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy);
        if (d >= 50) continue;
        if (d < 1e-3) { dx = 1; dy = 0; d = 1; }
        const push = (50 - d) / 2, ux = dx / d, uy = dy / d;
        a.x -= ux * push; a.y -= uy * push;
        b.x += ux * push; b.y += uy * push;
        moved = true;
      }
    }
    if (!moved) break;
  }
  return kids;
}

function visibleGraph(nodes, edges, collapsed) {
  if (!collapsed || !collapsed.size) return { nodes, edges };
  const hidden = new Set();
  edges.forEach(e => { if (collapsed.has(e.source)) hidden.add(e.target); });
  return {
    nodes: nodes.filter(n => !hidden.has(n.id)),
    edges: edges.filter(e => !hidden.has(e.target) && !hidden.has(e.source)),
  };
}

function filterProblemsOnly(nodes, edges) {
  // Keep only nodes on a path to a problem (status not online/unknown), i.e.
  // every problem node plus all of its ancestors; drop fully-green subtrees
  // and any edge whose endpoints are not both kept.
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  void byId;
  const parentOf = {};
  edges.forEach(e => { parentOf[e.target] = e.source; });
  const keep = new Set();
  const isProblem = n => n && n.status !== "online" && n.status !== "unknown";
  nodes.forEach(n => {
    if (!isProblem(n)) return;
    let cur = n.id;
    while (cur && !keep.has(cur)) { keep.add(cur); cur = parentOf[cur]; }
  });
  return {
    nodes: nodes.filter(n => keep.has(n.id)),
    edges: edges.filter(e => keep.has(e.source) && keep.has(e.target)),
  };
}

function animateToPositions(newPos, duration) {
  // Smoothly tween rendered nodes/edges to a new layout (easeOutCubic).
  const svg = topoState.root && topoState.root.querySelector(".topo-svg");
  if (!svg) { topoState.positions = newPos; rerenderFromState(); return; }
  duration = duration || 350;
  const old = {};
  Object.keys(newPos).forEach(id => {
    old[id] = topoState.positions[id] || newPos[id];
  });
  const nodeEls = {};
  svg.querySelectorAll(".topo-node").forEach(g => { nodeEls[g.getAttribute("data-node")] = g; });
  const edgeEls = Array.from(svg.querySelectorAll("path[data-edge]"));
  const start = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - start) / duration);
    const e = 1 - Math.pow(1 - k, 3);
    Object.keys(newPos).forEach(id => {
      const o = old[id], n = newPos[id];
      topoState.positions[id] = { x: o.x + (n.x - o.x) * e, y: o.y + (n.y - o.y) * e };
      const g = nodeEls[id];
      if (g) g.setAttribute("transform",
        `translate(${topoState.positions[id].x},${topoState.positions[id].y})`);
    });
    edgeEls.forEach(p => {
      const edge = topoState.visEdges[Number(p.getAttribute("data-edge"))];
      if (!edge) return;
      const a = topoState.positions[edge.source], b = topoState.positions[edge.target];
      if (a && b) p.setAttribute("d", edgePath(a, b));
    });
    if (k < 1) requestAnimationFrame(step);
    else topoState.positions = newPos;
  };
  requestAnimationFrame(step);
}

function rerenderFromState() {
  if (!topoState.root) return;
  renderTopology(topoState.root, {
    data: { nodes: topoState.nodes, edges: topoState.edges, legend: topoState.legend },
  });
}

function setView(root, view) {
  topoState.view = view === "flow" ? "flow" : "graph";
  const toggle = root.querySelector("[data-topo-view]");
  if (toggle) toggle.querySelectorAll("button").forEach(b =>
    b.classList.toggle("active", b.getAttribute("data-view") === topoState.view));
  rerenderFromState();
}

function nodeHref(n) {
  if (n.type === "switch") return `/m/switches/${encodeURIComponent(n.id)}`;
  if (n.type === "controller") return "/m/controller";
  return "";
}

function edgePath(a, b) {
  const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
  const dx = b.x - a.x, dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const cx = mx - (dy / len) * len * 0.12, cy = my + (dx / len) * len * 0.12;
  return `M ${a.x} ${a.y} Q ${cx} ${cy} ${b.x} ${b.y}`;
}

function edgeWidth(label, status) {
  // Weight by the label's magnitude hint (live rates or cumulative sizes).
  if (!label) return status === "offline" ? 2.5 : 1.5;
  if (label.includes("Gbps") || label.includes("TB")) return 5;
  if (label.includes("Mbps") || label.includes("GB")) return 3.5;
  return 2;
}

const FLOW_MIN_W = 2;
const FLOW_MAX_W = 28;

function flowWidth(edge, rates) {
  // Map a link's live rate (bps) to a finite ribbon width. No/blank rate →
  // thin floor (the "measuring…" state). Log scale so Kbps..Gbps all read.
  const bps = Number((rates || {})[edge.target]);
  if (!isFinite(bps) || bps <= 0) return FLOW_MIN_W;
  const w = FLOW_MIN_W + Math.log10(1 + bps) * 2.6;
  return Math.max(FLOW_MIN_W, Math.min(FLOW_MAX_W, w));
}

function diffAndToast(prev, nodes) {
  const toasts = [];
  nodes.forEach(n => {
    const p = prev[n.id];
    const alarms = (n.meta && n.meta.alarm_count) || 0;
    if (p) {
      if (p.status !== "offline" && n.status === "offline") {
        toasts.push({ id: n.id, kind: "crit", text: `${n.label} went offline` });
      }
      if (alarms > (p.alarms || 0)) {
        toasts.push({ id: n.id, kind: "warn", text: `${n.label}: ${alarms} active alarm${alarms !== 1 ? "s" : ""}` });
      }
    }
  });
  return toasts;
}

function showToasts(root, toasts) {
  const host = root.querySelector("[data-topo-toasts]");
  if (!host) return;
  toasts.slice(0, 5).forEach(t => {
    const el = document.createElement("div");
    el.className = `topo-toast${t.kind === "warn" ? " warn" : ""}`;
    el.textContent = t.text;
    el.addEventListener("click", () => { centerOn(t.id); el.remove(); });
    host.appendChild(el);
    setTimeout(() => el.remove(), 10000);
  });
}

function centerOn(id) {
  const p = topoState.positions[id];
  if (!p || !topoState.vb) return;
  const vb = topoState.vb;
  vb.minX = p.x - vb.w / 2;
  vb.minY = p.y - vb.h / 2;
  const svg = document.querySelector(".topo-svg");
  if (svg) svg.setAttribute("viewBox", `${vb.minX} ${vb.minY} ${vb.w} ${vb.h}`);
}

function tooltipHtml(n) {
  const meta = n.meta || {};
  const rows = [];
  const add = (k, v) => { if (v !== undefined && v !== null && v !== "") rows.push(`<div class="tt-row"><span>${_esc(k)}</span><span>${_esc(v)}</span></div>`); };
  add("type", n.type); add("status", n.status);
  add("ip", meta.ip); add("model", meta.model); add("firmware", meta.fw);
  add("cluster", meta.cluster_state);
  if (meta.ap_total !== undefined) add("APs", `${meta.ap_total} (${meta.ap_down || 0} down)`);
  if (meta.rssi_avg) add("signal", `${meta.rssi_avg} dB (avg client)`);
  if (topoState.rates[n.id] != null) add("live rate", fmtRate(topoState.rates[n.id]));
  if (meta.traffic_bytes) add("total traffic", humanTopoBytes(meta.traffic_bytes));
  if (meta.alarm_count) add("alarms", meta.alarm_count);
  if (n.type === "zone") rows.push(`<div class="tt-row"><span>click</span><span>expand/collapse APs</span></div>`);
  return `<div class="tt-title">${_esc(n.label || n.id)}</div>${rows.join("")}`;
}

function humanTopoBytes(n) {
  let v = Number(n);
  if (!isFinite(v) || v <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function renderTopology(root, payload) {
  const canvas = root.querySelector("[data-topo-canvas]");
  if (!canvas) return;
  const data = payload.data || payload;
  const nodes = data.nodes || [], edges = data.edges || [];
  if (!nodes.length) { canvas.innerHTML = `<p class="empty">No topology data.</p>`; return; }

  showToasts(root, diffAndToast(topoState.prev, nodes));
  topoState.prev = Object.fromEntries(nodes.map(n =>
    [n.id, { status: n.status, alarms: (n.meta && n.meta.alarm_count) || 0 }]));
  topoState.nodes = nodes; topoState.edges = edges;
  topoState.legend = data.legend; topoState.root = root;
  updateStatusRibbon(root, nodes);

  // Collapse filter: full graph stays in state (toast diffing above), only
  // visible nodes are laid out and drawn.
  updateRates(nodes);
  let vis = visibleGraph(nodes, edges, topoState.collapsed);
  if (topoState.problemsOnly) vis = filterProblemsOnly(vis.nodes, vis.edges);
  if (!vis.nodes.length) { canvas.innerHTML = `<p class="empty">No problems — all healthy.</p>`; updateStatusRibbon(root, nodes); return; }
  topoState.visEdges = vis.edges;
  if (topoState.view === "flow") {
    const flowRates = (data.flow && Object.keys(data.flow).length) ? data.flow : topoState.rates;
    canvas.innerHTML = renderFlow({ nodes: vis.nodes, edges: vis.edges }, flowRates);
    _wireTopo(root, canvas.querySelector("svg"));
    _renderTopoLegend(root, data.legend);
    return;
  }
  topoState.positions = layoutGraph(vis.nodes, vis.edges, topoState.saved, topoState.pinned);
  const pos = topoState.positions;

  const xs = vis.nodes.map(n => (pos[n.id] || {}).x || 0);
  const ys = vis.nodes.map(n => (pos[n.id] || {}).y || 0);
  const minX = Math.min(...xs) - 160, minY = Math.min(...ys) - 100;
  const w = (Math.max(...xs) - minX) + 280, h = (Math.max(...ys) - minY) + 200;
  topoState.box = { minX, minY, w, h };
  if (!topoState.vb) topoState.vb = { ...topoState.box };

  const byIdAll = Object.fromEntries(nodes.map(n => [n.id, n]));
  const edgeSvg = vis.edges.map((e, i) => {
    const a = pos[e.source], b = pos[e.target];
    if (!a || !b) return "";
    const col = TOPO_COLORS[e.status] || TOPO_COLORS.unknown;
    // Switch links label with the LIVE rate (delta between polls), not the
    // cumulative byte total the controller reports.
    let labelText = e.label;
    if ((byIdAll[e.target] || {}).type === "switch") {
      const bps = topoState.rates[e.target];
      // Only positive rates are worth ink on the map; idle/unmeasured links
      // stay unlabeled (hover shows the detail).
      labelText = bps > 0 ? fmtRate(bps) : "";
    }
    const wpx = edgeWidth(labelText, e.status);
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    const lbl = labelText ? `<text class="edge-label" x="${mx}" y="${my}">${_esc(labelText)}</text>` : "";
    return `<path data-edge="${i}" data-src="${_esc(e.source)}" data-dst="${_esc(e.target)}" ` +
           `d="${edgePath(a, b)}" fill="none" stroke="${col}" stroke-width="${wpx}" stroke-opacity=".75"/>${lbl}`;
  }).join("");

  const nodeSvg = vis.nodes.map((n, i) => {
    const p = pos[n.id]; if (!p) return "";
    const col = TOPO_COLORS[n.status] || TOPO_COLORS.unknown;
    const g = TOPO_GLYPH[n.type] || "•";
    const r = nodeRadius(n) + Math.round(healthWeight(n) * 10);
    const alarms = (n.meta && n.meta.alarm_count) || 0;
    const pulse = (n.status === "offline" || alarms > 0 ? " pulse" : "") +
                  (topoState.collapsed.has(n.id) ? " collapsed" : "");
    const labelY = (i % 2 === 0) ? r + 16 : -(r + 8);
    const badge = alarms > 0
      ? `<circle class="topo-badge" cx="${r - 4}" cy="${-(r - 4)}" r="9"/>` +
        `<text class="topo-badge-text" x="${r - 4}" y="${-(r - 8)}" text-anchor="middle">${alarms > 9 ? "9+" : alarms}</text>`
      : "";
    return `<g class="topo-node glow${pulse}" data-node="${_esc(n.id)}" style="${nodeGlowStyle(n)}" transform="translate(${p.x},${p.y})">` +
           `<circle r="${r}" fill="#0d1b2a" stroke="${col}" stroke-width="3"/>` +
           `<text class="glyph" text-anchor="middle" dy="6" font-size="${Math.max(12, r - 6)}">${g}</text>` +
           badge +
           `<text class="topo-label" text-anchor="middle" y="${labelY}">${_esc(n.label || n.id)}</text></g>`;
  }).join("");

  canvas.innerHTML =
    `<svg class="topo-svg" viewBox="${topoState.vb.minX} ${topoState.vb.minY} ${topoState.vb.w} ${topoState.vb.h}" ` +
    `preserveAspectRatio="xMidYMid meet"><g data-topo-scene>${edgeSvg}${nodeSvg}</g></svg>`;
  _wireTopo(root, canvas.querySelector("svg"));
  _renderTopoLegend(root, data.legend);
}

function renderFlow(data, rates) {
  // Concept D: deterministic left→right layered ribbon diagram. Returns an SVG
  // string (DOM-free for tests). Band thickness = live rate (flowWidth);
  // colour = edge status; labels HTML-escaped. Reuses the edgePath Bézier.
  const nodes = (data && data.nodes) || [];
  const edges = (data && data.edges) || [];
  rates = rates || {};
  if (!nodes.length) return `<svg class="topo-svg"></svg>`;
  const pos = layoutLayered(nodes, edges);
  const xs = nodes.map(n => pos[n.id].x), ys = nodes.map(n => pos[n.id].y);
  const minX = Math.min(...xs) - 120, minY = Math.min(...ys) - 120;
  const w = (Math.max(...xs) - minX) + 240, h = (Math.max(...ys) - minY) + 240;

  const ribbons = edges.map(e => {
    const a = pos[e.source], b = pos[e.target];
    if (!a || !b) return "";
    const col = TOPO_COLORS[e.status] || TOPO_COLORS.unknown;
    const sw = flowWidth(e, rates);
    return `<path class="topo-flow-ribbon" d="${edgePath(a, b)}" ` +
           `stroke="${col}" stroke-width="${sw}" stroke-opacity=".55"/>`;
  }).join("");

  const bars = nodes.map(n => {
    const p = pos[n.id];
    const col = TOPO_COLORS[n.status] || TOPO_COLORS.unknown;
    const bw = 150, bh = 30;
    return `<g class="topo-flow-bar topo-node" data-node="${_esc(n.id)}" ` +
           `transform="translate(${p.x - bw / 2},${p.y - bh / 2})">` +
           `<rect width="${bw}" height="${bh}" rx="4" fill="#0d1b2a" stroke="${col}" stroke-width="2"/>` +
           `<text class="topo-label" x="${bw / 2}" y="${bh / 2 + 4}" text-anchor="middle">${_esc(n.label || n.id)}</text></g>`;
  }).join("");

  const headers = [["controller", 0], ["zones / groups", 520], ["switches / APs", 1040]]
    .map(([t, x]) => `<text class="topo-flow-col" x="${x}" y="${minY + 28}" text-anchor="middle">${_esc(t)}</text>`)
    .join("");

  return `<svg class="topo-svg" viewBox="${minX} ${minY} ${w} ${h}" ` +
         `preserveAspectRatio="xMidYMid meet"><g data-topo-scene>` +
         `${ribbons}${bars}${headers}</g></svg>`;
}

function _renderTopoLegend(root, legend) {
  const el = root.querySelector("[data-topo-legend]");
  if (!el) return;
  const status = (legend && legend.status) || TOPO_COLORS;
  el.innerHTML = Object.entries(status).map(([k, c]) =>
    `<span class="topo-key"><i style="background:${c}"></i>${_esc(k)}</span>`).join("");
}

function _clientToWorld(svg, cx, cy) {
  const vb = topoState.vb;
  const rect = svg.getBoundingClientRect();
  return {
    x: vb.minX + ((cx - rect.left) / rect.width) * vb.w,
    y: vb.minY + ((cy - rect.top) / rect.height) * vb.h,
  };
}

function _updateNodeAndEdges(svg, id) {
  const p = topoState.positions[id];
  const g = svg.querySelector(`.topo-node[data-node="${CSS.escape(id)}"]`);
  if (g && p) g.setAttribute("transform", `translate(${p.x},${p.y})`);
  // data-edge indices follow the rendered (collapse-filtered) edge order.
  topoState.visEdges.forEach((e, i) => {
    if (e.source !== id && e.target !== id) return;
    const a = topoState.positions[e.source], b = topoState.positions[e.target];
    const path = svg.querySelector(`[data-edge="${i}"]`);
    if (path && a && b) path.setAttribute("d", edgePath(a, b));
  });
}

function _wireTopo(root, svg) {
  if (!svg) return;
  const vbApply = () => svg.setAttribute("viewBox",
    `${topoState.vb.minX} ${topoState.vb.minY} ${topoState.vb.w} ${topoState.vb.h}`);
  const zoom = f => {
    const vb = topoState.vb;
    const cx = vb.minX + vb.w / 2, cy = vb.minY + vb.h / 2;
    vb.w *= f; vb.h *= f; vb.minX = cx - vb.w / 2; vb.minY = cy - vb.h / 2; vbApply();
  };
  svg.addEventListener("wheel", e => { e.preventDefault(); zoom(e.deltaY > 0 ? 1.1 : 0.9); }, { passive: false });

  // Background pan vs node drag vs node click — one pointer state machine.
  // Group/zone drags carry their children (subtree drag) and re-fan on drop.
  let drag = null; // {id|null, x, y, moved, children:[{id,dx,dy}]}
  const isParentType = t => t === "group" || t === "stack" || t === "zone";
  svg.addEventListener("pointerdown", e => {
    const nodeEl = e.target.closest(".topo-node");
    const id = nodeEl ? nodeEl.getAttribute("data-node") : null;
    let children = [];
    if (id) {
      const n = topoState.nodes.find(x => x.id === id);
      const p = topoState.positions[id];
      if (n && p && isParentType(n.type)) {
        children = topoState.visEdges
          .filter(ed => ed.source === id && topoState.positions[ed.target])
          .map(ed => ({ id: ed.target,
                        dx: topoState.positions[ed.target].x - p.x,
                        dy: topoState.positions[ed.target].y - p.y }));
      }
    }
    drag = { id, x: e.clientX, y: e.clientY, moved: false, children };
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", e => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 5) return;
    drag.moved = true;
    if (drag.id) {
      const world = _clientToWorld(svg, e.clientX, e.clientY);
      topoState.positions[drag.id] = { x: world.x, y: world.y };
      topoState.pinned.add(drag.id);
      _updateNodeAndEdges(svg, drag.id);
      // Children ride along with their original offsets.
      drag.children.forEach(ch => {
        topoState.positions[ch.id] = { x: world.x + ch.dx, y: world.y + ch.dy };
        _updateNodeAndEdges(svg, ch.id);
      });
    } else {
      const vb = topoState.vb;
      const rect = svg.getBoundingClientRect();
      vb.minX -= dx * (vb.w / rect.width);
      vb.minY -= dy * (vb.h / rect.height);
      vbApply();
    }
    drag.x = e.clientX; drag.y = e.clientY;
  });
  const finish = e => {
    if (!drag) return;
    const { id, moved, children } = drag;
    drag = null;
    if (moved && id) {
      if (children.length) {
        // Re-fan the subtree at the new spot and pin it so polls keep it.
        const kids = refanChildren(id, topoState.positions, topoState.nodes,
                                   topoState.visEdges, "controller");
        kids.forEach(k => topoState.pinned.add(k));
        rerenderFromState();
      }
      return;
    }
    if (!id) return;
    // Click (no drag): switch/controller navigate, zone expands via server,
    // group/stack collapses locally.
    const n = topoState.nodes.find(x => x.id === id);
    if (!n) return;
    if (n.type === "zone") {
      if (topoState.expanded.has(id)) topoState.expanded.delete(id);
      else topoState.expanded.add(id);
      loadTopology(root);
      return;
    }
    if (n.type === "group" || n.type === "stack") {
      if (topoState.collapsed.has(id)) topoState.collapsed.delete(id);
      else topoState.collapsed.add(id);
      rerenderFromState();
      return;
    }
    const href = nodeHref(n);
    if (href) location.href = href;
  };
  svg.addEventListener("pointerup", finish);
  svg.addEventListener("pointercancel", () => { drag = null; });

  // Hover tooltip.
  const tip = root.querySelector("[data-topo-tooltip]");
  if (tip) {
    svg.addEventListener("pointerover", e => {
      const nodeEl = e.target.closest(".topo-node");
      if (nodeEl) {
        const n = topoState.nodes.find(x => x.id === nodeEl.getAttribute("data-node"));
        if (!n) return;
        tip.innerHTML = tooltipHtml(n);
        tip.hidden = false;
        return;
      }
      const edgeEl = e.target.closest("path[data-edge]");
      if (edgeEl) {
        const edge = topoState.visEdges[Number(edgeEl.getAttribute("data-edge"))];
        if (!edge) return;
        const byId = Object.fromEntries(topoState.nodes.map(n => [n.id, n]));
        const sl = (byId[edge.source] || {}).label || edge.source;
        const tl = (byId[edge.target] || {}).label || edge.target;
        const bps = topoState.rates[edge.target];
        const rateText = bps > 0 ? fmtRate(bps)
          : (bps === 0 ? "idle" : "measuring… (awaiting counter update)");
        tip.innerHTML = `<div class="tt-title">${_esc(sl)} ⇄ ${_esc(tl)}</div>` +
                        `<div class="tt-row"><span>live rate</span><span>${_esc(rateText)}</span></div>` +
                        `<div class="tt-row"><span>total traffic</span><span>${_esc(edge.label || "—")}</span></div>` +
                        `<div class="tt-row"><span>status</span><span>${_esc(edge.status || "unknown")}</span></div>`;
        tip.hidden = false;
        return;
      }
      tip.hidden = true;
    });
    svg.addEventListener("pointermove", e => {
      if (!tip.hidden) { tip.style.left = `${e.clientX + 14}px`; tip.style.top = `${e.clientY + 14}px`; }
    });
    svg.addEventListener("pointerleave", () => { tip.hidden = true; });
  }

  const zi = root.querySelector("[data-topo-zoom-in]");
  const zo = root.querySelector("[data-topo-zoom-out]");
  const fit = root.querySelector("[data-topo-fit]");
  if (zi) zi.onclick = () => zoom(0.9);
  if (zo) zo.onclick = () => zoom(1.1);
  if (fit) fit.onclick = () => { topoState.vb = { ...topoState.box }; vbApply(); };
}

function applySearch(root, query) {
  const q = String(query || "").trim().toLowerCase();
  const svg = root.querySelector(".topo-svg");
  if (!svg) return;
  let first = null;
  svg.querySelectorAll(".topo-node").forEach(g => {
    const id = g.getAttribute("data-node");
    const n = topoState.nodes.find(x => x.id === id);
    const hay = `${(n && n.label) || ""} ${id}`.toLowerCase();
    const hit = q && hay.includes(q);
    g.classList.toggle("highlight", hit);
    g.classList.toggle("dimmed", Boolean(q) && !hit);
    if (hit && !first) first = id;
  });
  if (first) centerOn(first);
}

function wireToolbar(root) {
  const search = root.querySelector("[data-topo-search]");
  if (search) search.addEventListener("input", () => applySearch(root, search.value));

  const save = root.querySelector("[data-topo-save]");
  if (save) save.addEventListener("click", () => {
    fetch("/api/topology/layout", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": _csrf() },
      body: JSON.stringify({ positions: topoState.positions }),
    }).then(r => { save.textContent = r.ok ? "✓" : "✗"; setTimeout(() => { save.textContent = "💾"; }, 1500); });
  });

  const freshLayout = () => {
    const vis = visibleGraph(topoState.nodes, topoState.edges, topoState.collapsed);
    return layoutGraph(vis.nodes, vis.edges, {}, new Set());
  };

  const reset = root.querySelector("[data-topo-reset]");
  if (reset) reset.addEventListener("click", () => {
    // Instant: relayout locally and animate; server delete runs in background
    // (no controller refetch — the next poll refreshes data anyway).
    topoState.saved = {}; topoState.pinned.clear();
    animateToPositions(freshLayout());
    fetch("/api/topology/layout", {
      method: "DELETE", credentials: "same-origin",
      headers: { "X-CSRF-Token": _csrf() },
    }).catch(() => {});
  });

  const arrange = root.querySelector("[data-topo-arrange]");
  if (arrange) arrange.addEventListener("click", () => {
    // Full clean auto-layout: drop session pins and in-memory saved anchors so
    // it always actually rearranges; 💾 re-persists if you like the result.
    topoState.pinned.clear();
    topoState.saved = {};
    animateToPositions(freshLayout());
  });

  const problems = root.querySelector("[data-topo-problems]");
  if (problems) problems.addEventListener("click", () => {
    topoState.problemsOnly = !topoState.problemsOnly;
    problems.setAttribute("aria-pressed", String(topoState.problemsOnly));
    rerenderFromState();
  });

  const viewToggle = root.querySelector("[data-topo-view]");
  if (viewToggle) viewToggle.querySelectorAll("button").forEach(b =>
    b.addEventListener("click", () => setView(root, b.getAttribute("data-view"))));

  const exportBtn = root.querySelector("[data-topo-export]");
  if (exportBtn) exportBtn.addEventListener("click", () => {
    try {
      const svg = root.querySelector(".topo-svg");
      const clone = svg.cloneNode(true);
      clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      const vb = svg.getAttribute("viewBox").split(" ").map(Number);
      clone.setAttribute("width", vb[2]); clone.setAttribute("height", vb[3]);
      const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
      style.textContent = ".topo-label{fill:#c7d3e0;font:12px Arial}" +
        ".edge-label{fill:#7c8aa0;font:10px Arial}" +
        ".topo-badge-text{fill:#fff;font:700 11px Arial}.topo-badge{fill:#e63946}";
      const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      bg.setAttribute("x", vb[0]); bg.setAttribute("y", vb[1]);
      bg.setAttribute("width", vb[2]); bg.setAttribute("height", vb[3]);
      bg.setAttribute("fill", "#0a1422");
      clone.insertBefore(bg, clone.firstChild);
      clone.insertBefore(style, clone.firstChild);
      const blob = new Blob([new XMLSerializer().serializeToString(clone)],
                            { type: "image/svg+xml" });
      const a = document.createElement("a");
      const ts = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
      a.href = URL.createObjectURL(blob);
      a.download = `topology-${ts}.svg`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch {
      exportBtn.textContent = "✗";
      setTimeout(() => { exportBtn.textContent = "⬇"; }, 1500);
    }
  });
}

function loadTopology(root) {
  const expand = Array.from(topoState.expanded).join(",");
  const url = `/api/modules/topology${expand ? `?expand=${encodeURIComponent(expand)}` : ""}`;
  return fetch(url, { credentials: "same-origin" })
    .then(r => {
      if (r.status === 401) { location.href = "/"; return null; }
      return r.ok ? r.json() : null;
    })
    .then(p => { if (p) renderTopology(root, p); })
    .catch(() => {});
}

if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("[data-topology]");
  if (!root) return;
  wireToolbar(root);
  fetch("/api/topology/layout", { credentials: "same-origin" })
    .then(r => r.ok ? r.json() : null)
    .then(p => { if (p && p.positions) topoState.saved = p.positions; })
    .catch(() => {})
    .finally(() => loadTopology(root));
  setInterval(() => { if (!document.hidden) loadTopology(root); }, 60000);
});

// Node-only export for unit tests (no-op in the browser). Keep this list in
// sync with the pure functions exercised by tests/integration/test_topology_node.py.
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    fmtRate, nodeRadius, layoutGraph, visibleGraph, edgePath, healthWeight, nodeGlowStyle, ribbonCounts, filterProblemsOnly, layoutLayered, flowWidth, renderFlow, setView,
  };
}
