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

  const entity = root.dataset.entity;
  if (entity) { renderDrill(root, slug, entity, payload); return; }

  const fresh = root.querySelector("[data-freshness]");
  if (fresh) fresh.textContent = payload.generated_at || "—";
  const stat = root.querySelector("[data-status]");
  if (stat) stat.textContent = payload.status || "—";

  const strip = root.querySelector("[data-kpi-strip]");
  if (strip && payload.summary) {
    strip.innerHTML = Object.entries(payload.summary)
      .map(([k, v]) => {
        const label = k.replace(/_/g, " ");
        return `<div class="kpi-card neutral"><span class="kpi-label">${label}</span>` +
               `<span class="kpi-value" aria-live="polite">${formatKpiValue(v)}</span></div>`;
      })
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

  // Rows are only clickable when the module actually has a drill-in page;
  // otherwise navigating produces a 404 (e.g. controller has no drill_fetcher).
  const drillable = !!spec.has_drill;
  const head = cols.map(c => `<th>${c.label}</th>`).join("");
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

function _escape(v) {
  return String(v ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
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
    return `<div class="kv-row"><span class="kv-key">${_escape(k)}</span>` +
           `<span class="kv-val">${_escape(val)}</span></div>`;
  }).join("");
  container.innerHTML = `<div class="kv-list">${rows}</div>`;
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
  // Pick the section: prefer a key matching the tab slug, else items, else whole data.
  let section = data;
  if (data && typeof data === "object" && !Array.isArray(data)) {
    if (Array.isArray(data[tabSlug]) || (data[tabSlug] && typeof data[tabSlug] === "object")) {
      section = data[tabSlug];
    } else if (Array.isArray(data.items)) {
      section = data.items;
    } else if (tabSlug === "summary" && data.identity) {
      section = data.identity;
    }
  }
  if (Array.isArray(section)) {
    renderGenericTable(body, section);
  } else if (section && typeof section === "object") {
    renderKeyVals(body, section);
  } else {
    body.innerHTML = `<p class="empty">No data.</p>`;
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
    const heroRows = Object.entries(identity).map(([k, v]) => {
      let val = v;
      if (v && typeof v === "object") val = JSON.stringify(v);
      return `<div class="kv-row"><span class="kv-key">${_escape(k)}</span>` +
             `<span class="kv-val">${_escape(val)}</span></div>`;
    }).join("");
    const tabBar = tabs.map((t, i) =>
      `<button class="drill-tab${i === 0 ? " active" : ""}" ` +
      `data-drill-tab="${_escape(t.slug)}">${_escape(t.title)}</button>`).join("");
    area.innerHTML =
      `<div class="drill-hero"><h2>${_escape(title)}</h2>` +
      `<div class="kv-list">${heroRows}</div></div>` +
      `<div class="drill-tabbar">${tabBar}</div>` +
      `<div class="drill-body" data-drill-body><p class="loading">Loading…</p></div>`;
    root.dataset.drillBuilt = entity;

    const body = area.querySelector("[data-drill-body]");
    const loadTab = (tabSlug) => {
      const url = `/api/modules/${encodeURIComponent(slug)}/` +
                  `${encodeURIComponent(entity)}/${encodeURIComponent(tabSlug)}`;
      fetch(url, { credentials: "same-origin" })
        .then(r => r.ok ? r.json() : null)
        .then(p => {
          if (!p) { body.innerHTML = `<p class="empty">No data.</p>`; return; }
          _renderDrillSection(body, slug, tabSlug, p);
        })
        .catch(() => { body.innerHTML = `<p class="empty">No data.</p>`; });
    };
    area.querySelectorAll("[data-drill-tab]").forEach(btn => {
      btn.addEventListener("click", () => {
        area.querySelectorAll("[data-drill-tab]").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        loadTab(btn.dataset.drillTab);
      });
    });
    // Default active tab: first. Render its section from the current payload
    // when possible (the drill_fetcher payload already contains every section).
    _renderDrillSection(body, slug, tabs[0].slug, payload);
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
