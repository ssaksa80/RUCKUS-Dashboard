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
    startModulePoller(slug, poll, entity);
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
