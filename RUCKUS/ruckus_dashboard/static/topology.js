"use strict";

const TOPO_COLORS = { online: "#2ecc71", flagged: "#f1c40f", offline: "#e74c3c", unknown: "#7c8aa0" };
const TOPO_GLYPH = { controller: "🛰️", zone: "📶", group: "🗄️", stack: "🗄️", switch: "🔀", ap: "📡", more: "⋯" };
const NODE_R = { controller: 30, group: 24, stack: 24, switch: 18, ap: 10, more: 12 };

const topoState = {
  nodes: [], edges: [],
  positions: {},          // {id: {x, y}} — current layout
  saved: {},              // server-persisted positions
  pinned: new Set(),      // dragged this session — never relaid
  expanded: new Set(),    // zone ids fanned out
  prev: {},               // {id: {status, alarms}} from previous poll
  vb: null, box: null,    // viewBox state
};

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
  // Traffic-weighted: parse nothing — server provides bytes on switch meta;
  // edges only carry the human label, so weight by label magnitude hint.
  if (!label) return status === "offline" ? 2.5 : 1.5;
  if (label.includes("TB")) return 5;
  if (label.includes("GB")) return 3.5;
  return 2;
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
  if (meta.traffic_bytes) add("traffic", humanTopoBytes(meta.traffic_bytes));
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
  topoState.positions = layoutGraph(nodes, edges, topoState.saved, topoState.pinned);
  const pos = topoState.positions;

  const xs = nodes.map(n => (pos[n.id] || {}).x || 0);
  const ys = nodes.map(n => (pos[n.id] || {}).y || 0);
  const minX = Math.min(...xs) - 160, minY = Math.min(...ys) - 100;
  const w = (Math.max(...xs) - minX) + 280, h = (Math.max(...ys) - minY) + 200;
  topoState.box = { minX, minY, w, h };
  if (!topoState.vb) topoState.vb = { ...topoState.box };

  const edgeSvg = edges.map((e, i) => {
    const a = pos[e.source], b = pos[e.target];
    if (!a || !b) return "";
    const col = TOPO_COLORS[e.status] || TOPO_COLORS.unknown;
    const wpx = edgeWidth(e.label, e.status);
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    const lbl = e.label ? `<text class="edge-label" x="${mx}" y="${my}">${_esc(e.label)}</text>` : "";
    return `<path data-edge="${i}" data-src="${_esc(e.source)}" data-dst="${_esc(e.target)}" ` +
           `d="${edgePath(a, b)}" fill="none" stroke="${col}" stroke-width="${wpx}" stroke-opacity=".75"/>${lbl}`;
  }).join("");

  const nodeSvg = nodes.map((n, i) => {
    const p = pos[n.id]; if (!p) return "";
    const col = TOPO_COLORS[n.status] || TOPO_COLORS.unknown;
    const g = TOPO_GLYPH[n.type] || "•";
    const r = nodeRadius(n);
    const alarms = (n.meta && n.meta.alarm_count) || 0;
    const pulse = n.status === "offline" || alarms > 0 ? " pulse" : "";
    const labelY = (i % 2 === 0) ? r + 16 : -(r + 8);
    const badge = alarms > 0
      ? `<circle class="topo-badge" cx="${r - 4}" cy="${-(r - 4)}" r="9"/>` +
        `<text class="topo-badge-text" x="${r - 4}" y="${-(r - 8)}" text-anchor="middle">${alarms > 9 ? "9+" : alarms}</text>`
      : "";
    return `<g class="topo-node${pulse}" data-node="${_esc(n.id)}" transform="translate(${p.x},${p.y})">` +
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
  topoState.edges.forEach((e, i) => {
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
  let drag = null; // {id|null, startX, startY, moved}
  svg.addEventListener("pointerdown", e => {
    const nodeEl = e.target.closest(".topo-node");
    drag = { id: nodeEl ? nodeEl.getAttribute("data-node") : null,
             x: e.clientX, y: e.clientY, moved: false };
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
    const { id, moved } = drag;
    drag = null;
    if (moved || !id) return;
    // Click (no drag): switch/controller navigate, zone expands/collapses.
    const n = topoState.nodes.find(x => x.id === id);
    if (!n) return;
    if (n.type === "zone") {
      if (topoState.expanded.has(id)) topoState.expanded.delete(id);
      else topoState.expanded.add(id);
      loadTopology(root);
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
      if (!nodeEl) { tip.hidden = true; return; }
      const n = topoState.nodes.find(x => x.id === nodeEl.getAttribute("data-node"));
      if (!n) return;
      tip.innerHTML = tooltipHtml(n);
      tip.hidden = false;
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

  const reset = root.querySelector("[data-topo-reset]");
  if (reset) reset.addEventListener("click", () => {
    fetch("/api/topology/layout", {
      method: "DELETE", credentials: "same-origin",
      headers: { "X-CSRF-Token": _csrf() },
    }).then(() => {
      topoState.saved = {}; topoState.pinned.clear(); topoState.vb = null;
      loadTopology(root);
    });
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

document.addEventListener("DOMContentLoaded", () => {
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
