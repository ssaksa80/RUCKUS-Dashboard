"use strict";

const TOPO_COLORS = { online: "#2ecc71", flagged: "#f1c40f", offline: "#e74c3c", unknown: "#7c8aa0" };
const TOPO_GLYPH = { controller: "🛰️", zone: "📶", group: "🗄️", stack: "🗄️", switch: "🔀" };

function layoutGraph(nodes, edges) {
  const pos = {};
  pos["controller"] = { x: 0, y: 0, angle: 0 };
  const tier1 = nodes.filter(n => n.type === "zone" || n.type === "group");
  const R1 = 340;
  tier1.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, tier1.length);
    pos[n.id] = { x: Math.cos(a) * R1, y: Math.sin(a) * R1, angle: a };
  });
  const childrenOf = {};
  edges.forEach(e => { (childrenOf[e.source] = childrenOf[e.source] || []).push(e.target); });
  nodes.filter(n => n.type === "group").forEach(g => {
    const base = (pos[g.id] && pos[g.id].angle) || 0;
    const kids = (childrenOf[g.id] || []).filter(id => nodes.find(n => n.id === id && n.type === "switch"));
    const R2 = 560, spread = Math.min(1.2, 0.25 * kids.length);
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

function _esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function renderTopology(root, payload) {
  const canvas = root.querySelector("[data-topo-canvas]");
  if (!canvas) return;
  const data = payload.data || payload;
  const nodes = data.nodes || [], edges = data.edges || [];
  if (!nodes.length) { canvas.innerHTML = `<p class="empty">No topology data.</p>`; return; }
  const pos = layoutGraph(nodes, edges);
  const xs = nodes.map(n => (pos[n.id] || {}).x || 0);
  const ys = nodes.map(n => (pos[n.id] || {}).y || 0);
  const minX = Math.min(...xs) - 140, minY = Math.min(...ys) - 90;
  const w = (Math.max(...xs) - minX) + 240, h = (Math.max(...ys) - minY) + 180;

  const lines = edges.map(e => {
    const a = pos[e.source], b = pos[e.target];
    if (!a || !b) return "";
    const col = TOPO_COLORS[e.status] || TOPO_COLORS.unknown;
    const lbl = e.label
      ? `<text class="edge-label" x="${(a.x + b.x) / 2}" y="${(a.y + b.y) / 2}">${_esc(e.label)}</text>`
      : "";
    return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${col}" stroke-width="2"/>${lbl}`;
  }).join("");

  const glyphs = nodes.map(n => {
    const p = pos[n.id]; if (!p) return "";
    const col = TOPO_COLORS[n.status] || TOPO_COLORS.unknown;
    const g = TOPO_GLYPH[n.type] || "•";
    const r = n.type === "controller" ? 28 : 22;
    return `<g class="topo-node" data-href="${_esc(nodeHref(n))}" transform="translate(${p.x},${p.y})">` +
           `<circle r="${r}" fill="#0d1b2a" stroke="${col}" stroke-width="3"/>` +
           `<text class="glyph" text-anchor="middle" dy="6">${g}</text>` +
           `<text class="topo-label" text-anchor="middle" y="${r + 16}">${_esc(n.label || n.id)}</text></g>`;
  }).join("");

  canvas.innerHTML =
    `<svg class="topo-svg" viewBox="${minX} ${minY} ${w} ${h}" preserveAspectRatio="xMidYMid meet">` +
    `<g data-topo-scene>${lines}${glyphs}</g></svg>`;
  _wireTopo(root, canvas.querySelector("svg"), { minX, minY, w, h });
  _renderTopoLegend(root, data.legend);
}

function _renderTopoLegend(root, legend) {
  const el = root.querySelector("[data-topo-legend]");
  if (!el) return;
  const status = (legend && legend.status) || TOPO_COLORS;
  el.innerHTML = Object.entries(status).map(([k, c]) =>
    `<span class="topo-key"><i style="background:${c}"></i>${_esc(k)}</span>`).join("");
}

function _wireTopo(root, svg, box) {
  if (!svg) return;
  let vb = { ...box };
  const apply = () => svg.setAttribute("viewBox", `${vb.minX} ${vb.minY} ${vb.w} ${vb.h}`);
  const zoom = f => {
    const cx = vb.minX + vb.w / 2, cy = vb.minY + vb.h / 2;
    vb.w *= f; vb.h *= f; vb.minX = cx - vb.w / 2; vb.minY = cy - vb.h / 2; apply();
  };
  svg.addEventListener("wheel", e => { e.preventDefault(); zoom(e.deltaY > 0 ? 1.1 : 0.9); }, { passive: false });
  let drag = null;
  svg.addEventListener("pointerdown", e => { drag = { x: e.clientX, y: e.clientY }; });
  svg.addEventListener("pointermove", e => {
    if (!drag) return;
    const sx = vb.w / (svg.clientWidth || 1), sy = vb.h / (svg.clientHeight || 1);
    vb.minX -= (e.clientX - drag.x) * sx; vb.minY -= (e.clientY - drag.y) * sy;
    drag = { x: e.clientX, y: e.clientY }; apply();
  });
  const stop = () => { drag = null; };
  svg.addEventListener("pointerup", stop);
  svg.addEventListener("pointerleave", stop);
  const zi = root.querySelector("[data-topo-zoom-in]");
  const zo = root.querySelector("[data-topo-zoom-out]");
  const fit = root.querySelector("[data-topo-fit]");
  if (zi) zi.onclick = () => zoom(0.9);
  if (zo) zo.onclick = () => zoom(1.1);
  if (fit) fit.onclick = () => { vb = { ...box }; apply(); };
  svg.querySelectorAll(".topo-node[data-href]").forEach(g => {
    const href = g.getAttribute("data-href");
    if (href) g.addEventListener("click", () => { location.href = href; });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("[data-topology]");
  if (!root) return;
  const load = () => fetch("/api/modules/topology", { credentials: "same-origin" })
    .then(r => {
      if (r.status === 401) { location.href = "/"; return null; }
      return r.ok ? r.json() : null;
    })
    .then(p => { if (p) renderTopology(root, p); })
    .catch(() => {});
  load();
  setInterval(() => { if (!document.hidden) load(); }, 60000);
});
