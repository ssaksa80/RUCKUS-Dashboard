"use strict";

const moduleState = {};
let activePoller = null;

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
  const area = root.querySelector("[data-data-area]");
  if (!area) return;
  if (items.length === 0) {
    area.innerHTML = `<p class="empty">No results.</p>`;
    return;
  }
  const cols = Object.keys(items[0]);
  area.innerHTML =
    `<table class="data-table"><thead><tr>${cols.map(c => `<th>${c}</th>`).join("")}</tr></thead>` +
    `<tbody>${items.slice(0, 100).map(row =>
      `<tr>${cols.map(c => `<td>${row[c] ?? ""}</td>`).join("")}</tr>`).join("")}</tbody></table>`;

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

function renderTile(slug, value) {
  const el = document.querySelector(`[data-tile-value="${slug}"]`);
  if (el) el.textContent = value;
}

function showErrorBanner(msg) {
  const eb = document.querySelector("[data-error-banner]");
  if (eb) { eb.hidden = false; eb.textContent = msg; }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector(".module");
  if (root) {
    const slug = root.dataset.slug;
    const poll = parseInt(root.dataset.poll, 10) || 30;
    const entity = root.dataset.entity || null;
    startModulePoller(slug, poll, entity);
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && activePoller) {
      fetchModule(activePoller.slug).catch(() => {});
    }
  });
  const dso = document.getElementById("dso-toggle");
  if (dso) dso.addEventListener("click", () => document.body.classList.toggle("dso-mode"));

  document.querySelectorAll(".tile[data-slug]").forEach(el => {
    const slug = el.dataset.slug;
    fetch(`/api/modules/${slug}`, { credentials: "same-origin" })
      .then(r => r.ok ? r.json() : null)
      .then(p => {
        if (!p) return;
        const val = (p.summary && (p.summary.count ?? Object.values(p.summary)[0])) ?? "—";
        renderTile(slug, val);
      }).catch(() => {});
  });
});
