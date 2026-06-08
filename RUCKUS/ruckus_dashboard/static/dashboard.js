"use strict";

const moduleState = {};
let activePoller = null;

// Per-slug spec metadata (columns/filters/title) fetched once from /api/modules.
const moduleSpecs = {};
// Per-slug client-side filter state: { key: value }.
const activeFilters = {};
// Cache of the last items fetched per slug, so filter changes re-render locally.
const lastItems = {};

async function loadModuleSpecs() {
  if (Object.keys(moduleSpecs).length) return moduleSpecs;
  try {
    const r = await fetch("/api/modules", { credentials: "same-origin" });
    if (!r.ok) return moduleSpecs;
    const body = await r.json();
    (body.modules || []).forEach(m => { moduleSpecs[m.slug] = m; });
  } catch { /* fall back to raw rendering */ }
  return moduleSpecs;
}

function humanBytes(n) {
  let v = Number(n);
  if (!isFinite(v) || v <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function humanUptime(seconds) {
  let s = Number(seconds);
  if (!isFinite(s) || s <= 0) return "—";
  const d = Math.floor(s / 86400); s -= d * 86400;
  const h = Math.floor(s / 3600); s -= h * 3600;
  const m = Math.floor(s / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatCell(value, kind) {
  if (value === null || value === undefined || value === "") return "—";
  if (kind === "status") {
    const v = String(value).toLowerCase();
    return `<span class="status-pill status-${v}">${String(value)}</span>`;
  }
  if (kind === "bytes") return humanBytes(value);
  if (kind === "uptime") return humanUptime(value);
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function startModulePoller(slug, pollSeconds, entityId) {
  stopModulePoller();
  const tick = () => {
    if (document.hidden) return;
    fetchModule(slug, entityId).catch(err => {
      console.error("module fetch failed", slug, err);
      const st = moduleState[slug] || (moduleState[slug] = {});
      st.errorCount = (st.errorCount || 0) + 1;
      showErrorBanner(`Fetch failed: ${err.message}`);
    });
  };
  tick();
  const timer = setInterval(tick, Math.max(5, pollSeconds) * 1000);
  activePoller = { slug, timer };
}

function stopModulePoller() {
  if (activePoller) {
    clearInterval(activePoller.timer);
    activePoller = null;
  }
}

async function fetchModule(slug, entityId) {
  const url = entityId
    ? `/api/modules/${encodeURIComponent(slug)}/${encodeURIComponent(entityId)}`
    : `/api/modules/${encodeURIComponent(slug)}`;
  const res = await fetch(url, { credentials: "same-origin" });
  if (res.status === 401) {
    location.href = "/";
    return;
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const payload = await res.json();
  renderModule(slug, payload);
  return payload;
}

function renderModule(slug, payload) {
  const root = document.querySelector(`.module[data-slug="${slug}"]`);
  if (!root) return;

  const fresh = root.querySelector("[data-freshness]");
  if (fresh) fresh.textContent = payload.generated_at || "—";
  const stat = root.querySelector("[data-status]");
  if (stat) stat.textContent = payload.status || "—";

  const strip = root.querySelector("[data-kpi-strip]");
  if (strip && payload.summary) {
    strip.innerHTML = Object.entries(payload.summary)
      .map(([k, v]) => `<div class="kpi-card neutral"><span class="kpi-label">${k}</span>` +
                       `<span class="kpi-value" aria-live="polite">${v}</span></div>`)
      .join("");
  }

  if (payload.data && payload.data.disabled) {
    root.querySelector("[data-data-area]").innerHTML =
      `<div class="error-banner">Module disabled — controller missing required ops: ` +
      `${(payload.data.missing_capabilities || []).map(c => c.join(" ")).join(", ")}</div>`;
    return;
  }

  const items = (payload.data && payload.data.items) || [];
  lastItems[slug] = items;
  const spec = moduleSpecs[slug] || {};
  renderFilters(root, slug, spec, items);
  renderColumns(root, slug, spec, items);

  const eb = root.querySelector("[data-error-banner]");
  if (eb) {
    if ((payload.controller_errors || []).length) {
      eb.hidden = false;
      eb.textContent = payload.controller_errors.map(e =>
        `${e.connection}: ${e.endpoint} — ${e.message} (${e.status})`).join(" · ");
    } else {
      eb.hidden = true;
    }
  }
}

function _applyFilters(slug, items) {
  const f = activeFilters[slug] || {};
  return items.filter(row => {
    for (const [key, val] of Object.entries(f)) {
      if (val === "" || val == null) continue;
      if (key === "__search") {
        const hay = Object.values(row).map(v => String(v ?? "")).join(" ").toLowerCase();
        if (!hay.includes(String(val).toLowerCase())) return false;
      } else if (String(row[key] ?? "") !== String(val)) {
        return false;
      }
    }
    return true;
  });
}

function renderColumns(root, slug, spec, items) {
  const area = root.querySelector("[data-data-area]");
  if (!area) return;
  const rows = _applyFilters(slug, items);
  if (rows.length === 0) {
    area.innerHTML = `<p class="empty">No results.</p>`;
    return;
  }
  const cols = (spec.columns && spec.columns.length)
    ? spec.columns
    : Object.keys(rows[0]).map(k => ({ label: k, key: k, kind: "text" }));

  const head = cols.map(c => `<th>${c.label}</th>`).join("");
  const body = rows.slice(0, 200).map(row => {
    const id = row.id != null ? encodeURIComponent(row.id) : "";
    const href = id ? `/m/${encodeURIComponent(slug)}/${id}` : "";
    const cells = cols.map(c => `<td>${formatCell(row[c.key], c.kind)}</td>`).join("");
    return `<tr${href ? ` data-href="${href}"` : ""}>${cells}</tr>`;
  }).join("");
  area.innerHTML = `<table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;

  // Whole-row click → drill page.
  area.querySelectorAll("tr[data-href]").forEach(tr => {
    tr.addEventListener("click", () => { location.href = tr.dataset.href; });
  });
}

function renderFilters(root, slug, spec, items) {
  const host = root.querySelector("[data-filters]");
  if (!host) return;
  const filters = spec.filters || [];
  if (!filters.length) { host.innerHTML = ""; return; }
  if (host.dataset.built === slug) return;  // build controls once per module page

  const parts = filters.map(f => {
    if (f.kind === "search") {
      return `<input class="filter-control" type="search" placeholder="${f.label}…" ` +
             `data-filter-key="__search">`;
    }
    const values = Array.from(new Set(items.map(i => i[f.key]).filter(v => v != null && v !== "")))
      .sort().map(v => `<option value="${String(v)}">${String(v)}</option>`).join("");
    return `<label class="filter-control"><span>${f.label}</span>` +
           `<select data-filter-key="${f.key}"><option value="">All</option>${values}</select></label>`;
  });
  host.innerHTML = parts.join("");
  host.dataset.built = slug;

  host.querySelectorAll("[data-filter-key]").forEach(ctrl => {
    const handler = () => {
      activeFilters[slug] = activeFilters[slug] || {};
      activeFilters[slug][ctrl.dataset.filterKey] = ctrl.value;
      renderColumns(root, slug, spec, lastItems[slug] || []);
    };
    ctrl.addEventListener("change", handler);
    ctrl.addEventListener("input", handler);
  });
}

function renderTile(slug, value) {
  const el = document.querySelector(`[data-tile-value="${slug}"]`);
  if (el) el.textContent = value;
}

function showErrorBanner(msg) {
  const eb = document.querySelector("[data-error-banner]");
  if (eb) { eb.hidden = false; eb.textContent = msg; }
}

function startWarmupStream() {
  const strip = document.querySelector("[data-warmup-strip]");
  if (!strip) return;
  strip.hidden = false;

  const tiles = Array.from(document.querySelectorAll(".tile[data-slug]"));
  const total = tiles.length;
  let done = 0;
  const bar = document.querySelector("[data-warmup-fill]");
  const text = document.querySelector("[data-warmup-text]");

  const updateTile = (payload) => {
    const tile = document.querySelector(`.tile[data-slug="${payload.slug}"]`);
    if (!tile) return;
    // sets data-tile-status attribute via camelCase dataset API
    tile.dataset.tileStatus = payload.status;
    const val = tile.querySelector(`[data-tile-value="${payload.slug}"]`);
    if (!val) return;
    if (payload.status === "done") {
      const s = payload.summary || {};
      val.textContent = s.total ?? s.count ?? Object.values(s)[0] ?? "0";
    } else if (payload.status === "failed" || payload.status === "timed_out") {
      val.textContent = "!";
      val.title = payload.error_message || "";
    } else if (payload.status === "disabled") {
      val.textContent = "—";
      val.title = "controller missing required ops";
    } else if (payload.status === "skipped") {
      val.textContent = "·";
    }
    done += 1;
    if (bar) bar.style.width = `${Math.round(100 * done / total)}%`;
    if (text) text.textContent = `Discovering RUCKUS controller… ${done}/${total}`;
  };

  const finish = () => { strip.hidden = true; };

  try {
    const es = new EventSource("/api/warmup");
    es.addEventListener("module-ready", (e) => {
      try { updateTile(JSON.parse(e.data)); } catch {}
    });
    es.addEventListener("complete", () => { es.close(); finish(); });
    es.onerror = () => {
      es.close();
      const poll = () => {
        fetch("/api/warmup/status", { credentials: "same-origin" })
          .then(r => r.ok ? r.json() : null)
          .then(p => {
            if (!p) return;
            Object.values(p.states || {}).forEach(updateTile);
            if (p.complete) finish();
            else setTimeout(poll, 2000);
          }).catch(() => setTimeout(poll, 2000));
      };
      poll();
    };
  } catch {
    const poll = () => {
      fetch("/api/warmup/status", { credentials: "same-origin" })
        .then(r => r.ok ? r.json() : null)
        .then(p => {
          if (!p) return;
          Object.values(p.states || {}).forEach(updateTile);
          if (p.complete) finish();
          else setTimeout(poll, 2000);
        }).catch(() => setTimeout(poll, 2000));
    };
    poll();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector(".module");
  if (root) {
    const slug = root.dataset.slug;
    const poll = parseInt(root.dataset.poll, 10) || 30;
    const entity = root.dataset.entity || null;
    // Load column/filter metadata first so the very first render is friendly.
    loadModuleSpecs().finally(() => startModulePoller(slug, poll, entity));
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && activePoller) {
      fetchModule(activePoller.slug).catch(() => {});
    }
  });
  const dso = document.getElementById("dso-toggle");
  if (dso) dso.addEventListener("click", () => document.body.classList.toggle("dso-mode"));

  // Overview page: warmup-driven tile loading
  if (document.querySelector("[data-warmup-strip]")) {
    startWarmupStream();
  }
});
