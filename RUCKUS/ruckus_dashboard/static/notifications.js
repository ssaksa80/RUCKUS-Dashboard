"use strict";

function _nfCsrf() {
  const m = document.querySelector('meta[name="csrf-token"]');
  return m ? m.content : "";
}

function _nfGetPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

function _nfSetPath(obj, path, value) {
  const keys = path.split(".");
  let o = obj;
  keys.slice(0, -1).forEach(k => { o = (o[k] = o[k] || {}); });
  o[keys[keys.length - 1]] = value;
}

function nfReadForm(root) {
  const cfg = {};
  root.querySelectorAll("[data-nf]").forEach(el => {
    const path = el.getAttribute("data-nf");
    let v;
    if (el.type === "checkbox") v = el.checked;
    else if (el.type === "number") v = Number(el.value || 0);
    else v = el.value;
    if (path.endsWith("recipients")) {
      v = String(v).split(",").map(s => s.trim()).filter(Boolean);
    }
    _nfSetPath(cfg, path, v);
  });
  return cfg;
}

function nfFillForm(root, cfg) {
  root.querySelectorAll("[data-nf]").forEach(el => {
    const v = _nfGetPath(cfg, el.getAttribute("data-nf"));
    if (v === undefined || v === null) return;
    if (el.type === "checkbox") el.checked = Boolean(v);
    else if (Array.isArray(v)) el.value = v.join(", ");
    else el.value = v;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("[data-notifications]");
  if (!root) return;

  fetch("/api/notifications/config", { credentials: "same-origin" })
    .then(r => r.ok ? r.json() : null)
    .then(cfg => { if (cfg) nfFillForm(root, cfg); })
    .catch(() => {});

  const saveStatus = root.querySelector("[data-save-status]");
  const save = root.querySelector("[data-notif-save]");
  if (save) save.addEventListener("click", () => {
    saveStatus.textContent = "Saving…";
    fetch("/api/notifications/config", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": _nfCsrf() },
      body: JSON.stringify(nfReadForm(root)),
    }).then(r => r.ok ? r.json() : Promise.reject())
      .then(cfg => { nfFillForm(root, cfg); saveStatus.textContent = "Saved ✓"; })
      .catch(() => { saveStatus.textContent = "Save failed ✗"; })
      .finally(() => setTimeout(() => { saveStatus.textContent = ""; }, 4000));
  });

  const testStatus = root.querySelector("[data-test-status]");
  const test = root.querySelector("[data-notif-test]");
  if (test) test.addEventListener("click", () => {
    testStatus.textContent = "Sending…";
    fetch("/api/notifications/test", {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRF-Token": _nfCsrf() },
    }).then(r => r.json().then(b => ({ ok: r.ok, b })))
      .then(({ ok, b }) => {
        testStatus.textContent = ok ? `Sent ✓ → ${(b.recipients || []).join(", ")}`
                                    : `Failed: ${b.error || "unknown"}`;
      })
      .catch(() => { testStatus.textContent = "Failed ✗"; });
  });
});

// ── Security-mode form behavior + per-channel test buttons ───────────────
document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("[data-notifications]");
  if (!root) return;

  const security = root.querySelector('[data-nf="smtp.security"]');
  const port = root.querySelector('[data-nf="smtp.port"]');
  const user = root.querySelector('[data-nf="smtp.username"]');
  const pass = root.querySelector('[data-nf="smtp.password"]');
  const DEFAULT_PORTS = { starttls: 587, ssl: 465, none: 25 };

  const applySecurity = (changePort) => {
    if (!security) return;
    const mode = security.value || "starttls";
    // Only auto-switch the port when it still holds a default value.
    if (changePort && port &&
        [25, 465, 587, 0].includes(Number(port.value || 0))) {
      port.value = DEFAULT_PORTS[mode] || 587;
    }
    // No TLS -> credentials would travel in cleartext; gray them out.
    const lock = mode === "none";
    [user, pass].forEach(el => {
      if (!el) return;
      el.disabled = lock;
      el.closest("label").classList.toggle("nf-disabled", lock);
    });
  };
  if (security) {
    security.addEventListener("change", () => applySecurity(true));
    // Initial state once the saved config has been loaded.
    setTimeout(() => applySecurity(false), 600);
  }

  const wireTest = (btnSel, statusSel, kind) => {
    const btn = root.querySelector(btnSel);
    const status = root.querySelector(statusSel);
    if (!btn || !status) return;
    btn.addEventListener("click", () => {
      status.textContent = "Sending…";
      fetch(kind === "report-full" ? "/api/reports/test" : "/api/notifications/test", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": _nfCsrf() },
        body: JSON.stringify({ kind }),
      }).then(r => r.json().then(b => ({ ok: r.ok, b })))
        .then(({ ok, b }) => {
          status.textContent = ok ? `Sent ✓ → ${(b.recipients || []).join(", ")}`
                                  : `Failed: ${b.error || "unknown"}`;
        })
        .catch(() => { status.textContent = "Failed ✗"; });
    });
  };
  wireTest("[data-notif-test-alert]", "[data-alert-test-status]", "alerts");
  wireTest("[data-notif-email-report]", "[data-report-test-status]", "report-full");
});
