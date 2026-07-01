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

function humanRate(bps) {
  let v = Number(bps);
  if (bps === null || bps === undefined || !isFinite(v)) return "measuring…";
  if (v <= 0) return "0 bps";
  const units = ["bps", "Kbps", "Mbps", "Gbps", "Tbps"];
  let i = 0;
  while (v >= 1000 && i < units.length - 1) { v /= 1000; i += 1; }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
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

function formatKpiValue(v) {
  // KPI values are scalars; a dict (e.g. by_method) renders as "GET 379 · POST 362".
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return String(v.length);
  if (typeof v === "object") {
    const parts = Object.entries(v).map(([k, n]) => `${k} ${n}`);
    return parts.length ? parts.join(" · ") : "—";
  }
  return String(v);
}

function formatCell(value, kind) {
  // Output is injected via innerHTML — every controller-sourced string (SSIDs,
  // AP/switch names, alarm text) must be HTML-escaped or a hostile name is XSS.
  if (value === null || value === undefined || value === "") return "—";
  if (kind === "status") {
    const cls = String(value).toLowerCase().replace(/[^a-z0-9_-]/g, "");
    return `<span class="status-pill status-${cls}">${_escape(value)}</span>`;
  }
  if (kind === "bytes") return humanBytes(value);
  if (kind === "rate") return humanRate(value);
  if (kind === "uptime") return humanUptime(value);
  if (Array.isArray(value)) return value.length ? _escape(value.join(", ")) : "—";
  if (typeof value === "object") return _escape(JSON.stringify(value));
  return _escape(value);
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

  const entity = root.dataset.entity;
  if (entity) { renderDrill(root, slug, entity, payload); return; }

  const fresh = root.querySelector("[data-freshness]");
  if (fresh) fresh.textContent = payload.generated_at || "—";
  const stat = root.querySelector("[data-status]");
  if (stat) stat.textContent = payload.status || "—";

  const strip = root.querySelector("[data-kpi-strip]");
  if (strip && payload.summary) {
    // formatKpiValue is also used with textContent elsewhere, so it returns raw
    // text; escape here where the result goes through innerHTML (summary values
    // like top_switch carry controller-sourced names).
    const filterMap = KPI_FILTER_MAP[slug] || {};
    const labels = KPI_LABELS[slug] || {};
    strip.innerHTML = Object.entries(payload.summary)
      .map(([k, v]) => {
        const label = labels[k] || k.replace(/_/g, " ");
        const clickable = filterMap[k] ? ` clickable" data-kpi-key="${_escape(k)}` : "";
        return `<div class="kpi-card neutral${clickable}"><span class="kpi-label">${_escape(label)}</span>` +
               `<span class="kpi-value" aria-live="polite">${_escape(formatKpiValue(v))}</span></div>`;
      })
      .join("");
    strip.querySelectorAll("[data-kpi-key]").forEach(card => {
      card.addEventListener("click", () => {
        applyKpiFilter(root, slug, card.dataset.kpiKey);
      });
    });
  }

  if (payload.data && payload.data.disabled) {
    root.querySelector("[data-data-area]").innerHTML =
      `<div class="error-banner">Module disabled — controller missing required ops: ` +
      `${_escape((payload.data.missing_capabilities || []).map(c => c.join(" ")).join(", "))}</div>`;
    return;
  }

  const items = (payload.data && payload.data.items) || [];
  lastItems[slug] = items;
  const spec = moduleSpecs[slug] || {};
  renderFilters(root, slug, spec, items);
  wireViewToggle(root, slug, spec);
  renderData(root, slug, spec, items);

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
      if (Array.isArray(val) && val.length === 0) continue;
      if (key === "__search") {
        const hay = Object.values(row).map(v => String(v ?? "")).join(" ").toLowerCase();
        if (!hay.includes(String(val).toLowerCase())) return false;
      } else if (key.startsWith("search:")) {
        const col = key.slice(7);
        if (!String(row[col] ?? "").toLowerCase().includes(String(val).toLowerCase())) return false;
      } else if (key.startsWith("range:")) {
        const col = key.slice(6);
        const n = Number(row[col]);
        const lo = val.min === "" || val.min == null ? null : Number(val.min);
        const hi = val.max === "" || val.max == null ? null : Number(val.max);
        if (lo == null && hi == null) continue;
        if (!isFinite(n)) return false;
        if (lo != null && n < lo) return false;
        if (hi != null && n > hi) return false;
      } else if (Array.isArray(val)) {
        // multi-select: row passes if its value is one of the selected.
        if (!val.map(String).includes(String(row[key] ?? ""))) return false;
      } else if (String(row[key] ?? "") !== String(val)) {
        return false;  // single-select exact match (KPI/poor-AP path)
      }
    }
    return true;
  });
}

// Per-slug selected view ("table" | "grid" | …). Default: first supported.
const activeViews = {};

// KPI cards that act as one-click filters: clicking BAND 5 shows only the
// 5 GHz clients, POOR SIGNAL shows only poor-quality clients, etc.
// Clicking the same card again clears that filter.
const KPI_FILTER_MAP = {
  clients: {
    band_2_4: { band: "2.4 GHz" },
    band_5: { band: "5 GHz" },
    band_6: { band: "6 GHz" },
    poor_signal: { quality: "poor" },
    total: {},                       // clears all filters
  },
  alarms: {
    critical: { severity: "critical" },
    major: { severity: "major" },
    minor: { severity: "minor" },
    warning: { severity: "warning" },
    total: {},
  },
};

// Friendly KPI card labels where the auto "key → spaces" reads poorly.
const KPI_LABELS = {
  clients: {
    band_2_4: "Band 2.4 GHz",
    band_5: "Band 5 GHz",
    band_6: "Band 6 GHz",
    top_bandwidth_user: "Top Bandwidth User",
  },
};

function applyKpiFilter(root, slug, kpiKey) {
  const mapping = (KPI_FILTER_MAP[slug] || {})[kpiKey];
  if (mapping === undefined) return;
  const filters = activeFilters[slug] = activeFilters[slug] || {};
  const entries = Object.entries(mapping);
  if (!entries.length) {
    // "total" card: clear everything.
    Object.keys(filters).forEach(k => { filters[k] = ""; });
  } else {
    entries.forEach(([key, value]) => {
      filters[key] = filters[key] === value ? "" : value;  // toggle
    });
  }
  // Reflect into the visible filter controls so the UI stays consistent.
  root.querySelectorAll("[data-filter-key]").forEach(ctrl => {
    const key = ctrl.dataset.filterKey;
    if (key in filters && ctrl.tagName === "SELECT") ctrl.value = filters[key] || "";
  });
  renderData(root, slug, moduleSpecs[slug] || {}, lastItems[slug] || []);
}

function renderData(root, slug, spec, items) {
  const view = activeViews[slug] ||
    ((spec.supports_views && spec.supports_views[0]) || "table");
  if (view === "grid") renderGrid(root, slug, spec, items);
  else renderColumns(root, slug, spec, items);  // table + fallback for other views
  _maybePoorApBreakdown(root, slug, items);
}

// When the clients quality filter is "poor", prepend a per-AP breakdown so the
// operator sees which APs carry the poor-signal users; chips narrow to one AP.
function _maybePoorApBreakdown(root, slug, items) {
  if (slug !== "clients") return;
  const filters = activeFilters[slug] || {};
  if (filters.quality !== "poor") return;
  const area = root.querySelector("[data-data-area]");
  if (!area) return;
  const counts = {};
  _applyFilters(slug, items).forEach(c => {
    const ap = c.ap || "—";
    counts[ap] = (counts[ap] || 0) + 1;
  });
  const chips = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 20)
    .map(([ap, n]) =>
      `<button class="poor-ap-chip" data-poor-ap="${_escape(ap)}">` +
      `${_escape(ap)} <strong>${n}</strong></button>`).join("");
  area.insertAdjacentHTML("afterbegin",
    `<div class="poor-ap-banner"><span>APs with poor-signal clients:</span>${chips}</div>`);
  area.querySelectorAll("[data-poor-ap]").forEach(btn => {
    btn.addEventListener("click", () => {
      const filters2 = activeFilters[slug] = activeFilters[slug] || {};
      filters2.ap = filters2.ap === btn.dataset.poorAp ? "" : btn.dataset.poorAp;
      root.querySelectorAll('[data-filter-key="ap"]').forEach(ctrl => {
        if (ctrl.tagName === "SELECT") ctrl.value = filters2.ap || "";
      });
      renderData(root, slug, moduleSpecs[slug] || {}, lastItems[slug] || []);
    });
  });
}

function wireViewToggle(root, slug, spec) {
  const host = root.querySelector("[data-views]");
  if (!host || host.dataset.wired === slug) return;
  host.dataset.wired = slug;
  host.querySelectorAll("[data-view]").forEach(btn => {
    btn.addEventListener("click", () => {
      activeViews[slug] = btn.dataset.view;
      host.querySelectorAll("[data-view]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      renderData(root, slug, moduleSpecs[slug] || {}, lastItems[slug] || []);
    });
  });
}

function renderGrid(root, slug, spec, items) {
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
  const titleCol = cols[0];
  const statusCol = cols.find(c => c.kind === "status");
  const fieldCols = cols.filter(c => c !== titleCol && c !== statusCol).slice(0, 5);
  const drillable = !!spec.has_drill;
  const cards = rows.slice(0, 600).map(row => {
    const id = row.id != null ? encodeURIComponent(row.id) : "";
    const href = (drillable && id) ? `/m/${encodeURIComponent(slug)}/${id}` : "";
    const fields = fieldCols.map(c =>
      `<div class="card-row"><span>${_escape(c.label)}</span>` +
      `<span>${formatCell(row[c.key], c.kind)}</span></div>`).join("");
    return `<div class="item-card"${href ? ` data-href="${href}"` : ""}>` +
           `<div class="card-head"><strong>${formatCell(row[titleCol.key], titleCol.kind)}</strong>` +
           `${statusCol ? formatCell(row[statusCol.key], "status") : ""}</div>` +
           fields + `</div>`;
  }).join("");
  area.innerHTML = `<div class="card-grid">${cards}</div>`;
  area.querySelectorAll(".item-card[data-href]").forEach(card => {
    card.addEventListener("click", () => { location.href = card.dataset.href; });
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

  // Rows are only clickable when the module actually has a drill-in page;
  // otherwise navigating produces a 404 (e.g. controller has no drill_fetcher).
  const drillable = !!spec.has_drill;
  const head = cols.map(c => `<th>${_escape(c.label)}</th>`).join("");
  const body = rows.slice(0, 2000).map(row => {
    const id = row.id != null ? encodeURIComponent(row.id) : "";
    const href = (drillable && id) ? `/m/${encodeURIComponent(slug)}/${id}` : "";
    const cells = cols.map(c => `<td>${formatCell(row[c.key], c.kind)}</td>`).join("");
    return `<tr${href ? ` data-href="${href}"` : ""}>${cells}</tr>`;
  }).join("");
  area.innerHTML = `<table class="data-table${drillable ? " clickable" : ""}">` +
                   `<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;

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
      return `<input class="filter-control" type="search" placeholder="${_escape(f.label)}…" ` +
             `data-filter-key="__search">`;
    }
    // Option values come from controller data (SSIDs, zone names) — escape both
    // the attribute and the display text.
    const values = Array.from(new Set(items.map(i => i[f.key]).filter(v => v != null && v !== "")))
      .sort().map(v => `<option value="${_escape(v)}">${_escape(v)}</option>`).join("");
    return `<label class="filter-control"><span>${_escape(f.label)}</span>` +
           `<select data-filter-key="${_escape(f.key)}"><option value="">All</option>${values}</select></label>`;
  });
  host.innerHTML = parts.join("");
  host.dataset.built = slug;

  host.querySelectorAll("[data-filter-key]").forEach(ctrl => {
    const handler = () => {
      activeFilters[slug] = activeFilters[slug] || {};
      activeFilters[slug][ctrl.dataset.filterKey] = ctrl.value;
      renderData(root, slug, spec, lastItems[slug] || []);
    };
    ctrl.addEventListener("change", handler);
    ctrl.addEventListener("input", handler);
  });
}

function _escape(v) {
  return String(v ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Key/value list for object-shaped sections (identity, health, raw object).
function renderKeyVals(container, obj) {
  if (!obj || typeof obj !== "object" || Array.isArray(obj) || !Object.keys(obj).length) {
    container.innerHTML = `<p class="empty">No data.</p>`;
    return;
  }
  const rows = Object.entries(obj).map(([k, v]) => {
    let val = v;
    if (v && typeof v === "object") val = JSON.stringify(v);
    return `<div class="kv-row"><span class="kv-key">${_escape(_humanKey(k))}</span>` +
           `<span class="kv-val">${_escape(val)}</span></div>`;
  }).join("");
  container.innerHTML = `<div class="kv-list">${rows}</div>`;
}

function _humanKey(k) {
  return String(k).replace(/_/g, " ");
}

function _kvListHtml(obj) {
  const rows = Object.entries(obj || {})
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => {
      let val = v;
      if (v && typeof v === "object") val = JSON.stringify(v);
      return `<div class="kv-row"><span class="kv-key">${_escape(_humanKey(k))}</span>` +
             `<span class="kv-val">${_escape(val)}</span></div>`;
    }).join("");
  return `<div class="kv-list">${rows}</div>`;
}

// Simple table for array-of-objects sections (ports, etc.).
function renderGenericTable(container, rows) {
  if (!Array.isArray(rows) || rows.length === 0) {
    container.innerHTML = `<p class="empty">No data.</p>`;
    return;
  }
  const cols = Array.from(rows.reduce((set, r) => {
    Object.keys(r || {}).forEach(k => set.add(k));
    return set;
  }, new Set()));
  const head = cols.map(c => `<th>${_escape(c)}</th>`).join("");
  const body = rows.slice(0, 500).map(r =>
    `<tr>${cols.map(c => {
      let v = r[c];
      if (v && typeof v === "object") v = JSON.stringify(v);
      return `<td>${_escape(v ?? "—")}</td>`;
    }).join("")}</tr>`).join("");
  container.innerHTML =
    `<table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

// Render one tab's section payload into the drill body.
function _renderDrillSection(body, slug, tabSlug, payload) {
  const data = (payload && payload.data) || {};
  if (tabSlug === "raw") {
    body.innerHTML = `<pre class="drill-raw">${_escape(JSON.stringify(data, null, 2))}</pre>`;
    return;
  }
  if (tabSlug === "summary" && data && typeof data === "object" && !Array.isArray(data)) {
    // Summary stacks every informative section: identity key/values first,
    // then each other non-raw section (catalog/ports/health/…) with a heading.
    const parts = [];
    if (data.identity && typeof data.identity === "object") {
      parts.push(_kvListHtml(data.identity));
    }
    Object.entries(data).forEach(([key, section]) => {
      if (["identity", "raw", "error"].includes(key)) return;
      if (Array.isArray(section) && section.length) {
        const tmp = document.createElement("div");
        renderGenericTable(tmp, section);
        parts.push(`<div class="drill-section-title">${_escape(_humanKey(key))}</div>` + tmp.innerHTML);
      } else if (section && typeof section === "object" && Object.keys(section).length) {
        parts.push(`<div class="drill-section-title">${_escape(_humanKey(key))}</div>` + _kvListHtml(section));
      }
    });
    if (data.error) parts.push(`<div class="error-banner">${_escape(data.error)}</div>`);
    body.innerHTML = parts.length ? parts.join("") : `<p class="empty">No data.</p>`;
    return;
  }
  // Named tab: prefer a key matching the tab slug, else items, else whole data.
  let section = data;
  if (data && typeof data === "object" && !Array.isArray(data)) {
    if (Array.isArray(data[tabSlug]) || (data[tabSlug] && typeof data[tabSlug] === "object")) {
      section = data[tabSlug];
    } else if (Array.isArray(data.items)) {
      section = data.items;
    }
  }
  if (Array.isArray(section)) {
    renderGenericTable(body, section);
  } else if (section && typeof section === "object" && Object.keys(section).length) {
    renderKeyVals(body, section);
  } else {
    body.innerHTML = `<p class="empty">No data for this tab.</p>`;
  }
}

function renderDrill(root, slug, entity, payload) {
  const fresh = root.querySelector("[data-freshness]");
  if (fresh) fresh.textContent = (payload && payload.generated_at) || "—";
  const stat = root.querySelector("[data-status]");
  if (stat) stat.textContent = (payload && payload.status) || "—";

  // In drill mode, hide list-oriented chrome.
  const kpi = root.querySelector("[data-kpi-strip]");
  if (kpi) kpi.hidden = true;
  const filters = root.querySelector("[data-filters]");
  if (filters) filters.hidden = true;
  const views = root.querySelector("[data-views]");
  if (views) views.hidden = true;

  const area = root.querySelector("[data-data-area]");
  if (!area) return;

  const data = (payload && payload.data) || {};
  const identity = (data && data.identity && typeof data.identity === "object")
    ? data.identity : { id: entity };
  const title = identity.name || identity.id || entity;

  const spec = moduleSpecs[slug] || {};
  const tabs = (spec.drill_tabs && spec.drill_tabs.length)
    ? spec.drill_tabs : [{ slug: "summary", title: "Summary" }, { slug: "raw", title: "Raw" }];

  // Build hero + tab bar once.
  if (root.dataset.drillBuilt !== entity) {
    // Hero stays minimal (status + id); the Summary tab carries the full detail.
    const heroBits = [];
    if (identity.status) heroBits.push(formatCell(identity.status, "status"));
    if (identity.id && identity.id !== title) heroBits.push(`<span class="kv-key">${_escape(identity.id)}</span>`);
    const tabBar = tabs.map((t, i) =>
      `<button class="drill-tab${i === 0 ? " active" : ""}" ` +
      `data-drill-tab="${_escape(t.slug)}">${_escape(t.title)}</button>`).join("");
    area.innerHTML =
      `<div class="drill-hero"><h2>${_escape(title)}</h2>${heroBits.join(" ")}</div>` +
      `<div class="drill-tabbar">${tabBar}</div>` +
      `<div class="drill-body" data-drill-body><p class="loading">Loading…</p></div>`;
    root.dataset.drillBuilt = entity;

    const body = area.querySelector("[data-drill-body]");
    // The drill payload already contains every section — render tabs from it
    // instantly; only hit the per-tab endpoint when the section is missing.
    let lastPayload = payload;
    const showTab = (tabSlug) => {
      const data = (lastPayload && lastPayload.data) || {};
      const hasSection = tabSlug === "summary" || tabSlug === "raw" ||
        data[tabSlug] !== undefined;
      if (hasSection) { _renderDrillSection(body, slug, tabSlug, lastPayload); return; }
      body.innerHTML = `<p class="loading">Loading…</p>`;
      const url = `/api/modules/${encodeURIComponent(slug)}/` +
                  `${encodeURIComponent(entity)}/${encodeURIComponent(tabSlug)}`;
      fetch(url, { credentials: "same-origin" })
        .then(r => r.ok ? r.json() : null)
        .then(p => {
          if (!p) { body.innerHTML = `<p class="empty">No data.</p>`; return; }
          lastPayload = p;
          _renderDrillSection(body, slug, tabSlug, p);
        })
        .catch(() => { body.innerHTML = `<p class="empty">No data.</p>`; });
    };
    root._drillUpdatePayload = (p) => { lastPayload = p; };
    area.querySelectorAll("[data-drill-tab]").forEach(btn => {
      btn.addEventListener("click", () => {
        area.querySelectorAll("[data-drill-tab]").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        showTab(btn.dataset.drillTab);
      });
    });
    _renderDrillSection(body, slug, tabs[0].slug, payload);
  } else if (root._drillUpdatePayload) {
    // Poll refresh: keep the cached payload current for instant tab switches.
    root._drillUpdatePayload(payload);
  }
}

function pickSummaryNumber(s) {
  if (!s) return undefined;
  return s.total ?? s.count ?? s.switches ?? Object.values(s).find(x => typeof x === "number");
}

function applyHealthState(slug, status, summary) {
  const v = document.querySelector(`[data-health-value="${slug}"]`);
  const chip = document.querySelector(`[data-health-chip="${slug}"]`);
  if (!v) return;
  if (status === "done") {
    const n = pickSummaryNumber(summary);
    v.textContent = n === undefined ? "0" : formatKpiValue(n);
    if (chip) {
      if ((slug === "alarms" || slug === "rogues") && Number(n) > 0) chip.classList.add("danger");
      else chip.classList.remove("danger");
    }
  } else if (status === "failed" || status === "timed_out") {
    v.textContent = "!";
  } else if (status === "disabled") {
    v.textContent = "—";
  }
}

function renderHealthBar() {
  const bar = document.querySelector("[data-health-bar]");
  if (!bar) return;
  bar.hidden = false;
  const load = () => fetch("/api/warmup/status", { credentials: "same-origin" })
    .then(r => r.ok ? r.json() : null)
    .then(p => { if (p) Object.values(p.states || {}).forEach(st => applyHealthState(st.slug, st.status, st.summary)); })
    .catch(() => {});
  load();
  try {
    const es = new EventSource("/api/warmup");
    es.addEventListener("module-ready", (e) => {
      try { const st = JSON.parse(e.data); applyHealthState(st.slug, st.status, st.summary); } catch {}
    });
    es.addEventListener("complete", () => es.close());
    es.onerror = () => { es.close(); };
  } catch { /* status load already populated the bar */ }
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
      const pick = s.total ?? s.count ?? s.switches ?? Object.values(s).find(x => typeof x === "number");
      val.textContent = pick === undefined ? "0" : formatKpiValue(pick);
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
  // DSO wall mode. Entering hides the topbar (and its toggle), so provide a
  // floating exit button + Escape key so the user is never trapped.
  const dso = document.getElementById("dso-toggle");
  const setWall = (on) => {
    document.body.classList.toggle("dso-mode", on);
    let exit = document.getElementById("dso-exit");
    if (on && !exit) {
      exit = document.createElement("button");
      exit.id = "dso-exit";
      exit.className = "dso-exit";
      exit.textContent = "⤢ Exit wall";
      exit.title = "Exit DSO wall mode (Esc)";
      exit.addEventListener("click", () => setWall(false));
      document.body.appendChild(exit);
    }
    if (exit) exit.hidden = !on;
  };
  if (dso) dso.addEventListener("click", () => setWall(!document.body.classList.contains("dso-mode")));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.classList.contains("dso-mode")) setWall(false);
  });

  // Persistent DSO health bar (shell-level, present on every page).
  renderHealthBar();

  // Overview page: warmup-driven tile loading
  if (document.querySelector("[data-warmup-strip]")) {
    startWarmupStream();
  }
});
