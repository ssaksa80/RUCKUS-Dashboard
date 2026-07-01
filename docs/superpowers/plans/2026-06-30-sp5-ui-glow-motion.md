# SP5 — UI Glow / Motion Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CSP-clean, leak-safe glow + motion layer (state-keyed neon glow, KPI count-up, tile entrance, live refresh pulse) to the always-on DSO wall display, while bringing the existing unconditional `topo-pulse`/`toast-in` animations into `prefers-reduced-motion` compliance.

**Architecture:** Hybrid (spec Approach C). All ambient/state motion is declarative CSS in `static/styles.css` keyed off attributes/classes the JS already emits (`.kpi-card.{ok,watch,critical}`, `.status-{complete,partial,error}`, `.health-chip.danger`, `.tile[data-tile-status]`). One new same-origin file `static/motion.js` (no dependency, ~110 lines) provides `animateCount`/`pulse`/`motionReduced` — a single self-cancelling `requestAnimationFrame` per node, no `setInterval`, fail-open. Triggers are folded into the existing render functions in `dashboard.js`. One `<script>` tag loads `motion.js` before `dashboard.js` in `templates/base.html`. **No Python/route changes; the CSP stays exactly `script-src 'self'`** and a new regression test locks that in.

**Tech Stack:** Vanilla CSS3 (`@keyframes`, `@property`, `box-shadow`/`text-shadow`/`filter`, `prefers-reduced-motion`), vanilla ES (no build step, no package manager), Flask static serving. Tests: `pytest` (static-file symbol assertions + CSS substring assertions, the existing idiom in `tests/integration/test_dashboard_js.py` and `test_topology_js.py`; CSP via response-header assertion), `ruff` on CI.

**Repo root:** `C:\Users\sshoaib\OneDrive - Mohamed & Obaid Almulla LLC\Documents\RUCKUS-Dashboard`
**Package root (paths below are relative to repo root):** `RUCKUS/ruckus_dashboard/`
**Run tests from:** the repo root, with the venv that has `pip install -e RUCKUS[test]` + `ruff`.

**Scope guards (do NOT do here):** no GSAP, no `static/vendor/`, no CDN (spec §3 rejects Approach B). No new routes, no new payload fields, no new polling/timers (the only timers remain the existing poller + SSE). No markup change to any partial **except** the single `<script>` line in `base.html`. Open Questions in spec §5 are resolved by the decisions baked into this plan (see "Decisions locked" below) — do not re-litigate them mid-implementation.

**Decisions locked (resolving spec §5 Open Questions):**
1. **KPI card health coloring (Q1):** YES — map state→class in `renderModule` for `alarms`/`rogues`/`clients` (Task 5). Other slugs stay `neutral`. This is the high-impact choice the spec recommends.
2. **Count-up vs flash (Q2):** count-up for finite numerics; formatted/dict/non-numeric values get a CSS `value-changed` flash. No magnitude cutoff (a single `duration` cap keeps "slot-machine" feel bounded; spec's ~1000 threshold is YAGNI — the 320ms cap already prevents long counts).
3. **Glow color/intensity (Q3):** reuse existing `--ok/--watch/--critical` hues for the halo rgba tokens; critical **breathes** (slow pulse) at desk subtlety and **intensifies** (larger radius) under `body.dso-mode`. No new magenta neon.
4. **Refresh pulse prominence (Q4):** subtle — a one-shot ring on the module root via a transient class, ~600ms, self-cleaning on `animationend`. Not a full-screen sweep.
5. **Reduced-motion scope (Q5):** YES — bring existing `topo-pulse` (`styles.css:186`) and `toast-in` (`styles.css:201`) under the new global guard (the spec calls this a latent a11y bug the work fixes).
6. **GSAP escape hatch (Q6):** defer (YAGNI). No `vendor/` scaffolding now.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `RUCKUS/ruckus_dashboard/static/styles.css` | `:root` glow/timing tokens; `prefers-reduced-motion` global kill-switch (incl. legacy `topo-pulse`/`toast-in`); state-glow rules; entrance/refresh/value-changed/sheen keyframes; `body.dso-mode` intensify | 1, 2, 3, 4 |
| `RUCKUS/ruckus_dashboard/static/motion.js` | **new** — `animateCount`, `pulse`, `motionReduced` (single self-cancelling rAF/node, fail-open, hidden/reduced snap-to-final) | 5 |
| `RUCKUS/ruckus_dashboard/static/dashboard.js` | wire triggers: KPI state-class + count-up + refresh pulse in `renderModule`; count-up in `applyHealthState`; count-up + entrance pulse in `updateTile`; `motion.js` calls guarded fail-open | 6, 7, 8 |
| `RUCKUS/ruckus_dashboard/templates/base.html` | one `<script src=".../motion.js">` immediately **before** the `dashboard.js` tag (`base.html:64`) | 9 |
| `RUCKUS/ruckus_dashboard/app.py` | **unchanged** — CSP stays `script-src 'self'` (asserted, not edited) | 10 |
| `tests/integration/test_motion_ui.py` | **new** — CSS token/keyframe/guard assertions; `motion.js` served + symbols + leak-safety; `base.html` loads `motion.js`; CSP-regression header guard; dashboard.js wiring symbols | 1–10 |

> **Why one new test file:** the repo's idiom is one integration test module per feature surface (`test_dashboard_js.py`, `test_topology_js.py`, `test_static_assets.py`). SP5 spans CSS + a new JS file + a template line + a CSP guarantee, so a dedicated `test_motion_ui.py` keeps these cohesive and is where every task adds its failing test first. Each task below appends its tests to this one file.

> **Testing idiom (read before Task 1).** This project has **no JS runtime**; JS/CSS are verified two ways, both already used in-repo:
> - **CSS:** `pathlib.Path("RUCKUS/ruckus_dashboard/static/styles.css").read_text(encoding="utf-8")` then `assert "<substring>" in css` (see `test_topology_js.py::test_topology_css_has_pulse_and_toast`). Tests run from the repo root, so this relative path resolves.
> - **JS/static serving + headers:** `create_app({"SECRET_KEY": "t"})` → `c.get("/static/<file>")` → assert status/`data.decode()` symbols and `r.headers[...]` (see `test_dashboard_js.py`, `test_app_factory.py::test_security_headers_present`).
>
> New `.css`/`.js` files under `static/` are served automatically by Flask's static route — **no app.py registration needed** for `motion.js`.

---

### Task 1: Glow/timing token layer + global `prefers-reduced-motion` kill-switch

Adds the design tokens (spec §4.2) to `:root` and the one global reduced-motion block (spec §4.6) that flattens all motion **including the legacy `topo-pulse`/`toast-in`** (spec §3 bug fix, Q5). Color/glow tokens are additive; existing tokens at `styles.css:1-8` are untouched.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/styles.css` (extend `:root`, ends `:8`; append a new trailing "Motion layer" section after the current last line `:268`)
- Test: `tests/integration/test_motion_ui.py` (new)

**Steps:**

- [ ] **Write the failing test.** Create `tests/integration/test_motion_ui.py` with:

```python
import pathlib

CSS = pathlib.Path("RUCKUS/ruckus_dashboard/static/styles.css")


def _css():
    return CSS.read_text(encoding="utf-8")


def test_motion_tokens_present():
    css = _css()
    for token in [
        "--glow-ok", "--glow-watch", "--glow-critical", "--glow-accent",
        "--motion-fast", "--motion-base", "--motion-slow",
        "--ease-out", "--pulse-critical-period",
    ]:
        assert token in css, f"missing token {token}"


def test_reduced_motion_global_killswitch():
    css = _css()
    assert "@media (prefers-reduced-motion: reduce)" in css
    # The guard must flatten motion to none.
    assert "animation: none" in css
    assert "transition: none" in css


def test_reduced_motion_covers_legacy_topo_and_toast():
    """Spec §3 / Q5: the pre-existing infinite topo-pulse and toast-in must be
    brought under the reduced-motion guard (latent a11y bug fixed here)."""
    css = _css()
    guard = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    assert ".topo-node.pulse > circle" in guard
    assert ".topo-toast" in guard
```

- [ ] **Run it (expect FAIL).** `python -m pytest tests/integration/test_motion_ui.py -q` → FAILS: tokens not in CSS (`missing token --glow-ok`), and the `@media (prefers-reduced-motion: reduce)` block does not exist yet.

- [ ] **Implement — extend `:root`.** In `RUCKUS/ruckus_dashboard/static/styles.css`, change the `:root` close (currently `styles.css:7-8`):

```css
  --focus: #5bd6e5;
  --sidebar-w: 220px;
```

to:

```css
  --focus: #5bd6e5;
  --sidebar-w: 220px;
  /* SP5 motion layer — glow halos (rgba of the existing state hues) */
  --glow-ok: rgba(56, 193, 114, 0.55);
  --glow-watch: rgba(246, 200, 95, 0.6);
  --glow-critical: rgba(255, 95, 87, 0.7);
  --glow-accent: rgba(91, 214, 229, 0.6);
  /* timing + easing */
  --motion-fast: 180ms;
  --motion-base: 320ms;
  --motion-slow: 1.6s;
  --ease-out: cubic-bezier(0.22, 0.61, 0.36, 1);
  --pulse-critical-period: 1.4s; /* matches the existing topo-pulse cadence */
```

- [ ] **Implement — append the global guard at end of file.** Append after the current last line (`styles.css:268`, the `.nf-disabled` rule):

```css

/* ════════════════════════════════════════════════════════════════════════
   SP5 — Motion & glow layer
   GPU-friendly only (opacity/transform/filter/box-shadow). No setInterval.
   ════════════════════════════════════════════════════════════════════════ */

/* Global reduced-motion kill-switch. Color states (information) remain;
   ALL motion is flattened, including the pre-existing topo-pulse + toast-in
   that previously ignored the OS setting (spec §3 bug fix). */
@media (prefers-reduced-motion: reduce) {
  .kpi-card.critical .kpi-value,
  .status-error,
  .health-chip.danger,
  .topo-node.pulse > circle,
  .topo-toast,
  .tile,
  .module-refreshed::after,
  .value-changed,
  .warmup-fill::after {
    animation: none !important;
    transition: none !important;
  }
}
```

- [ ] **Run tests (expect PASS).** `python -m pytest tests/integration/test_motion_ui.py -q` → 3 passed.

- [ ] **Commit.** `git add RUCKUS/ruckus_dashboard/static/styles.css tests/integration/test_motion_ui.py && git commit -m "feat(ui): SP5 glow/timing tokens + prefers-reduced-motion kill-switch"`

---

### Task 2: State-glow rules (KPI / status pill / health chip / topology)

Adds the ambient health-state glow keyed to classes the JS/templates already set (spec §4.3 item 1): `.kpi-card.critical` breathes, `.watch` steady halo, `.ok` faint rim; status pills and `.health-chip.danger` glow; re-token `topo-pulse` color to `--glow-critical` (spec §4.3 item 5).

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/styles.css` (append to the SP5 section from Task 1)
- Test: `tests/integration/test_motion_ui.py`

**Steps:**

- [ ] **Write the failing test.** Append to `tests/integration/test_motion_ui.py`:

```python
def test_state_glow_rules_present():
    css = _css()
    for rule in [
        ".kpi-card.critical .kpi-value", ".kpi-card.watch .kpi-value",
        ".kpi-card.ok .kpi-value",
        ".status-error", ".status-partial", ".status-complete",
        ".health-chip.danger",
    ]:
        assert rule in css, f"missing glow rule {rule}"
    # Glow uses the tokens + box/text-shadow.
    assert "var(--glow-critical)" in css
    assert "var(--glow-watch)" in css
    assert "var(--glow-ok)" in css


def test_critical_breathing_keyframe():
    css = _css()
    assert "@keyframes glow-critical-breathe" in css
    assert "var(--pulse-critical-period)" in css


def test_topo_pulse_retokened_to_glow_critical():
    """Spec §4.3.5: topo-pulse keeps its cadence but uses the shared token."""
    css = _css()
    assert "@keyframes topo-pulse" in css  # still defined
    # the highlight drop-shadow / pulse now references the critical glow token
    assert "drop-shadow(0 0 8px var(--glow-critical))" in css
```

- [ ] **Run it (expect FAIL).** `python -m pytest tests/integration/test_motion_ui.py -q` → FAILS: `missing glow rule .kpi-card.critical .kpi-value` (the existing rule at `styles.css:49` only sets `color`, not the glow shadow line this test newly demands via `var(--glow-critical)`), and `@keyframes glow-critical-breathe` absent.

- [ ] **Implement — append state-glow rules** to the SP5 section in `styles.css`:

```css

/* ── State glow (ambient, keyed to classes JS/templates already set) ──── */
@keyframes glow-critical-breathe {
  0%,
  100% { box-shadow: 0 0 0 1px var(--glow-critical); }
  50% { box-shadow: 0 0 14px 2px var(--glow-critical); }
}

/* KPI value glow by health. .ok = faint static rim, .watch = steady halo,
   .critical = breathing halo. JS maps state→class in renderModule (Task 6). */
.kpi-card.ok .kpi-value { text-shadow: 0 0 6px var(--glow-ok); }
.kpi-card.watch .kpi-value { text-shadow: 0 0 9px var(--glow-watch); }
.kpi-card.critical .kpi-value {
  text-shadow: 0 0 11px var(--glow-critical);
  animation: glow-critical-breathe var(--pulse-critical-period) ease-in-out infinite;
}

/* Status pills + persistent health chip danger state. */
.status-complete { box-shadow: 0 0 6px var(--glow-ok); }
.status-partial { box-shadow: 0 0 8px var(--glow-watch); }
.status-error {
  box-shadow: 0 0 10px var(--glow-critical);
  animation: glow-critical-breathe var(--pulse-critical-period) ease-in-out infinite;
}
.health-chip.danger {
  box-shadow: 0 0 9px var(--glow-critical);
  animation: glow-critical-breathe var(--pulse-critical-period) ease-in-out infinite;
}

/* Re-token the existing topology highlight/pulse to the shared critical glow
   (spec §4.3.5). topo-pulse keyframe stays as-is at styles.css:181-185. */
.topo-node.highlight > circle { filter: drop-shadow(0 0 8px var(--glow-critical)); }
```

- [ ] **Run tests (expect PASS).** `python -m pytest tests/integration/test_motion_ui.py -q` → all passed.

- [ ] **Run the existing topology CSS test (regression).** `python -m pytest tests/integration/test_topology_js.py::test_topology_css_has_pulse_and_toast -q` → still passes (`@keyframes topo-pulse`, `.topo-toast`, etc. all still present; we only added a sibling rule).

- [ ] **Commit.** `git add RUCKUS/ruckus_dashboard/static/styles.css tests/integration/test_motion_ui.py && git commit -m "feat(ui): SP5 state-glow rules + critical breathing keyframe"`

---

### Task 3: Entrance, refresh-pulse, value-changed + warmup sheen keyframes

Adds the one-shot/transient motion keyframes and trigger-class rules the JS will toggle (spec §4.3 items 2–4): staggered tile entrance (pure CSS `:nth-child`), `.module-refreshed` ring, `.value-changed` flash, and a moving sheen on `.warmup-fill` while `< 100%`.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/styles.css` (append to SP5 section)
- Test: `tests/integration/test_motion_ui.py`

**Steps:**

- [ ] **Write the failing test.** Append to `tests/integration/test_motion_ui.py`:

```python
def test_entrance_and_pulse_keyframes_present():
    css = _css()
    for kf in [
        "@keyframes tile-enter", "@keyframes refresh-ring",
        "@keyframes value-flash", "@keyframes warmup-sheen",
    ]:
        assert kf in css, f"missing keyframe {kf}"


def test_trigger_classes_present():
    css = _css()
    # one-shot pulse fired by motion.js pulse(root, "refreshed")
    assert ".module-refreshed::after" in css
    # value flash for non-numeric/formatted KPI changes
    assert ".value-changed" in css
    # staggered tile entrance keyed to nth-child (no JS list)
    assert ".tile-grid .tile" in css
    assert "nth-child" in css
    # warmup sheen only while filling
    assert '.warmup-fill:not([style*="width: 100%"])::after' in css \
        or ".warmup-fill::after" in css


def test_dso_mode_intensifies_glow():
    """Q3: wall mode intensifies (larger halo); desk mode subtle."""
    css = _css()
    assert "body.dso-mode .kpi-card.critical .kpi-value" in css
    assert "body.dso-mode .health-chip.danger" in css
```

- [ ] **Run it (expect FAIL).** `python -m pytest tests/integration/test_motion_ui.py -q` → FAILS: `missing keyframe @keyframes tile-enter`, `.module-refreshed::after` absent, `body.dso-mode .kpi-card.critical` absent.

- [ ] **Implement — append entrance/pulse/sheen + dso-mode intensify** to the SP5 section in `styles.css`:

```css

/* ── Tile entrance (pure CSS stagger; no JS list needed) ──────────────── */
@keyframes tile-enter {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to { opacity: 1; transform: none; }
}
.tile-grid .tile {
  animation: tile-enter var(--motion-base) var(--ease-out) both;
}
.tile-grid .tile:nth-child(1) { animation-delay: 0ms; }
.tile-grid .tile:nth-child(2) { animation-delay: 40ms; }
.tile-grid .tile:nth-child(3) { animation-delay: 80ms; }
.tile-grid .tile:nth-child(4) { animation-delay: 120ms; }
.tile-grid .tile:nth-child(5) { animation-delay: 160ms; }
.tile-grid .tile:nth-child(6) { animation-delay: 200ms; }
.tile-grid .tile:nth-child(n + 7) { animation-delay: 240ms; }

/* ── Live refresh pulse: one-shot ring on the module root per poll ─────── */
@keyframes refresh-ring {
  0% { opacity: 0.55; transform: scale(0.995); }
  100% { opacity: 0; transform: scale(1.01); }
}
.module { position: relative; }
.module-refreshed::after {
  content: "";
  position: absolute;
  inset: 0;
  border: 2px solid var(--glow-accent);
  border-radius: 8px;
  pointer-events: none;
  animation: refresh-ring 600ms var(--ease-out) forwards;
}

/* ── Value-changed flash (non-numeric / formatted KPI updates) ─────────── */
@keyframes value-flash {
  0% { color: var(--focus); text-shadow: 0 0 10px var(--glow-accent); }
  100% { color: inherit; text-shadow: none; }
}
.value-changed { animation: value-flash var(--motion-base) var(--ease-out); }

/* ── Warmup sheen while the bar is still filling ──────────────────────── */
@keyframes warmup-sheen {
  from { transform: translateX(-120%); }
  to { transform: translateX(220%); }
}
.warmup-fill { position: relative; overflow: hidden; }
.warmup-fill::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg, transparent, rgba(238, 244, 248, 0.35), transparent);
  animation: warmup-sheen 1.2s linear infinite;
}
.warmup-fill[style*="width: 100%"]::after { animation: none; content: none; }

/* ── DSO wall-mode glow intensify (Q3): larger halo, steadier read ─────── */
body.dso-mode .kpi-card.critical .kpi-value {
  text-shadow: 0 0 22px var(--glow-critical);
}
body.dso-mode .kpi-card.watch .kpi-value {
  text-shadow: 0 0 18px var(--glow-watch);
}
body.dso-mode .health-chip.danger { box-shadow: 0 0 16px var(--glow-critical); }
```

- [ ] **Run tests (expect PASS).** `python -m pytest tests/integration/test_motion_ui.py -q` → all passed.

- [ ] **Commit.** `git add RUCKUS/ruckus_dashboard/static/styles.css tests/integration/test_motion_ui.py && git commit -m "feat(ui): SP5 entrance/refresh/value-flash/sheen keyframes + dso-mode intensify"`

---

### Task 4: Lock the warmup-fill transition still works under the guard

The existing `.warmup-fill { transition: width 0.3s }` (`styles.css:108`) must survive; the reduced-motion guard intentionally only kills the **sheen** (`::after`), not the width transition (width is a state read, low motion). This task adds a focused regression so a future guard edit can't silently disable the bar.

**Files:**
- Modify: none (assertion-only task; CSS already correct from Tasks 1 + 3)
- Test: `tests/integration/test_motion_ui.py`

**Steps:**

- [ ] **Write the failing test.** Append to `tests/integration/test_motion_ui.py`:

```python
def test_warmup_width_transition_preserved():
    """The warmup bar width transition (styles.css:108) must remain; only the
    decorative sheen is gated. Guards against a future over-broad kill-switch."""
    css = _css()
    assert "transition: width 0.3s" in css
    guard = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    # the guard targets the sheen pseudo-element, never the base .warmup-fill width
    assert ".warmup-fill::after" in guard
    assert ".warmup-fill {" not in guard
```

- [ ] **Run it (expect PASS immediately — characterization).** `python -m pytest tests/integration/test_motion_ui.py::test_warmup_width_transition_preserved -q` → PASSES. (This is a guard/characterization test: the behavior is already correct from Tasks 1+3. If it FAILS, a prior task broke the contract — fix the CSS, do not weaken the test.)

> Rationale for a passing-on-write test here: per repo idiom these CSS contracts are locked with substring assertions; this one pins an *absence* (the guard must not list base `.warmup-fill`) that no other task asserts. It is cheap insurance for the one rule the spec explicitly says stays animated.

- [ ] **Commit.** `git add tests/integration/test_motion_ui.py && git commit -m "test(ui): SP5 lock warmup-fill width transition survives reduced-motion guard"`

---

### Task 5: New `static/motion.js` — `animateCount`, `pulse`, `motionReduced`

The only new JS file (spec §4.4). Dependency-free, same-origin (CSP-clean). One self-cancelling `requestAnimationFrame` handle stored on the node; snaps to final under reduced-motion or `document.hidden`; fail-open.

**Files:**
- Create: `RUCKUS/ruckus_dashboard/static/motion.js`
- Test: `tests/integration/test_motion_ui.py`

**Steps:**

- [ ] **Write the failing test.** Append to `tests/integration/test_motion_ui.py`:

```python
from ruckus_dashboard.app import create_app


def test_motion_js_served_with_js_content_type():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        r = c.get("/static/motion.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["Content-Type"].lower()


def test_motion_js_public_api_symbols():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/motion.js").data.decode()
        for sym in ["function animateCount", "function pulse",
                    "function motionReduced", "window.RuckusMotion"]:
            assert sym in body, f"missing {sym}"


def test_motion_js_is_leak_safe_and_reduced_motion_aware():
    """Single cancellable rAF per node; snaps under hidden/reduced; no setInterval."""
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/motion.js").data.decode()
        assert "requestAnimationFrame" in body
        assert "cancelAnimationFrame" in body
        assert "document.hidden" in body
        assert "prefers-reduced-motion" in body
        assert "matchMedia" in body
        # leak rule: no interval timers introduced by the motion layer
        assert "setInterval" not in body
```

- [ ] **Run it (expect FAIL).** `python -m pytest tests/integration/test_motion_ui.py -k motion_js -q` → FAILS: `GET /static/motion.js` returns 404 (file does not exist).

- [ ] **Implement.** Create `RUCKUS/ruckus_dashboard/static/motion.js`:

```javascript
"use strict";

// SP5 motion utilities — dependency-free, same-origin (CSP script-src 'self').
// Leak-safe: at most one requestAnimationFrame handle per node, stored on the
// node and cancelled before re-arming and on hidden. No setInterval. Fail-open:
// callers wrap these so a throw never breaks rendering — the final value is
// always written even when the tween is skipped.

(function (global) {
  // True when the OS asks for reduced motion. matchMedia may be absent in odd
  // embeddings — treat absence as "motion allowed" (the CSS guard still applies).
  function motionReduced() {
    try {
      return !!(global.matchMedia &&
        global.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (_e) {
      return false;
    }
  }

  // Animate a numeric text node from its current numeric value to `to`,
  // formatting each frame via `fmt`. Snaps to final under reduced motion or a
  // hidden tab. No-ops gracefully on a non-element / non-finite target.
  function animateCount(el, to, opts) {
    opts = opts || {};
    var fmt = typeof opts.fmt === "function" ? opts.fmt : String;
    var duration = typeof opts.duration === "number" ? opts.duration : 320;
    if (!el || typeof el !== "object") return;

    var target = Number(to);
    var snap = function () { el.textContent = isFinite(target) ? fmt(target) : String(to); };

    // Cancel any in-flight tween on this node before re-arming (leak guard).
    if (el._rkRaf) { global.cancelAnimationFrame(el._rkRaf); el._rkRaf = 0; }

    if (!isFinite(target) || motionReduced() ||
        (global.document && global.document.hidden)) {
      snap();
      return;
    }

    var from = parseFloat(String(el.textContent).replace(/[^0-9.\-]/g, ""));
    if (!isFinite(from)) from = 0;
    if (from === target) { snap(); return; }

    var start = 0;
    var step = function (ts) {
      if (!start) start = ts;
      var p = Math.min(1, (ts - start) / duration);
      // ease-out cubic to match --ease-out
      var e = 1 - Math.pow(1 - p, 3);
      var cur = from + (target - from) * e;
      el.textContent = fmt(p >= 1 ? target : Math.round(cur));
      if (p < 1) {
        el._rkRaf = global.requestAnimationFrame(step);
      } else {
        el._rkRaf = 0;
      }
    };
    el._rkRaf = global.requestAnimationFrame(step);
  }

  // Fire a one-shot CSS pulse by toggling `<base>-ed` class with a reflow
  // re-arm and animationend self-clean. No-op under reduced motion.
  function pulse(el, cls) {
    cls = cls || "refreshed";
    var full = "module-" + cls; // e.g. "module-refreshed"
    if (!el || typeof el !== "object" || motionReduced()) return;
    el.classList.remove(full);
    // force reflow so re-adding the class restarts the animation
    void el.offsetWidth;
    el.classList.add(full);
    var clear = function () { el.classList.remove(full); el.removeEventListener("animationend", clear); };
    el.addEventListener("animationend", clear);
  }

  global.RuckusMotion = { animateCount: animateCount, pulse: pulse, motionReduced: motionReduced };
})(typeof window !== "undefined" ? window : this);
```

- [ ] **Run tests (expect PASS).** `python -m pytest tests/integration/test_motion_ui.py -k motion_js -q` → all passed.

- [ ] **Commit.** `git add RUCKUS/ruckus_dashboard/static/motion.js tests/integration/test_motion_ui.py && git commit -m "feat(ui): SP5 add same-origin motion.js (animateCount/pulse/motionReduced)"`

---

### Task 6: Wire `renderModule` — KPI state-class + count-up + refresh pulse

Folds triggers into `renderModule` (spec §4.3 items 1, 2, 4 + §4.8). KPI cards gain a health class (Q1), numeric values count up, formatted/non-numeric flash, and the module root pulses once per render. All `RuckusMotion` calls are guarded fail-open (spec §4.7). The `aria-live="polite"` already on the value node (`dashboard.js:143`) is preserved so screen readers announce the final value once.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/dashboard.js` (`renderModule` KPI strip `:131-151`; end of `renderModule` `:177`)
- Test: `tests/integration/test_motion_ui.py`

**Steps:**

- [ ] **Write the failing test.** Append to `tests/integration/test_motion_ui.py`:

```python
def test_dashboard_js_wires_kpi_state_class_and_count_up():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        # state→class mapper for KPI cards (Q1)
        assert "function kpiHealthClass" in body
        # count-up + flash applied via the guarded helper
        assert "_motion(" in body or "RuckusMotion" in body
        assert "animateCount" in body
        assert "value-changed" in body
        # refresh pulse fired once per render on the module root
        assert 'pulse(root, "refreshed")' in body or 'RuckusMotion.pulse(root' in body


def test_dashboard_js_motion_is_fail_open():
    """Spec §4.7: a throw in the motion layer must never break renderModule."""
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        assert "function _motion" in body  # try/catch wrapper around RuckusMotion calls
        assert "try {" in body
```

- [ ] **Run it (expect FAIL).** `python -m pytest tests/integration/test_motion_ui.py -k "kpi_state_class or fail_open" -q` → FAILS: `function kpiHealthClass` and `function _motion` not present in dashboard.js.

- [ ] **Implement — add the helpers** near the top of `RUCKUS/ruckus_dashboard/static/dashboard.js`, immediately after the `lastItems` declaration (currently `dashboard.js:10`):

```javascript
// Cache of the last items fetched per slug, so filter changes re-render locally.
const lastItems = {};

// ── SP5 motion glue ──────────────────────────────────────────────────────
// Fail-open wrapper: a throw or a missing RuckusMotion must never break a
// render (the textContent/innerHTML writes remain the source of truth).
function _motion(fn) {
  try {
    if (window.RuckusMotion) fn(window.RuckusMotion);
  } catch (_e) { /* enhancement only — ignore */ }
}

// Map a KPI key+value to a health class for glow. Only a few slugs carry a
// meaningful threshold; everything else stays "neutral" (no behavior change).
function kpiHealthClass(slug, key, value) {
  const n = Number(value);
  if (!isFinite(n)) return "neutral";
  if (slug === "alarms") {
    if (key === "critical" && n > 0) return "critical";
    if ((key === "major" || key === "minor" || key === "warning") && n > 0) return "watch";
  }
  if (slug === "rogues" && key === "total" && n > 0) return "critical";
  if (slug === "clients" && key === "poor_signal" && n > 0) return "watch";
  return "neutral";
}
```

- [ ] **Implement — KPI strip render** in `renderModule`. Replace the current strip block (`dashboard.js:138-150`):

```javascript
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
```

with (adds health class, a stable `data-kpi-id` for value lookup, then count-up/flash post-render):

```javascript
    strip.innerHTML = Object.entries(payload.summary)
      .map(([k, v]) => {
        const label = labels[k] || k.replace(/_/g, " ");
        const clickable = filterMap[k] ? ` clickable" data-kpi-key="${_escape(k)}` : "";
        const health = kpiHealthClass(slug, k, v);
        return `<div class="kpi-card ${health}${clickable}" data-kpi-id="${_escape(k)}">` +
               `<span class="kpi-label">${_escape(label)}</span>` +
               `<span class="kpi-value" aria-live="polite">${_escape(formatKpiValue(v))}</span></div>`;
      })
      .join("");
    strip.querySelectorAll("[data-kpi-key]").forEach(card => {
      card.addEventListener("click", () => {
        applyKpiFilter(root, slug, card.dataset.kpiKey);
      });
    });
    // Count up finite numerics; flash formatted/non-numeric changes.
    Object.entries(payload.summary).forEach(([k, v]) => {
      const card = strip.querySelector(`[data-kpi-id="${CSS.escape(k)}"]`);
      const valEl = card && card.querySelector(".kpi-value");
      if (!valEl) return;
      const n = Number(v);
      if (typeof v !== "object" && v !== null && isFinite(n) && String(v).trim() !== "") {
        _motion(m => m.animateCount(valEl, n, { fmt: String, duration: 320 }));
      } else {
        valEl.classList.remove("value-changed");
        void valEl.offsetWidth;
        valEl.classList.add("value-changed");
      }
    });
```

- [ ] **Implement — refresh pulse** at the end of `renderModule`. The function currently ends at `dashboard.js:176-177`:

```javascript
    } else {
      eb.hidden = true;
    }
  }
}
```

Change to fire the one-shot pulse on the module root just before the closing brace:

```javascript
    } else {
      eb.hidden = true;
    }
  }
  _motion(m => m.pulse(root, "refreshed"));
}
```

- [ ] **Run tests (expect PASS).** `python -m pytest tests/integration/test_motion_ui.py -k "kpi_state_class or fail_open" -q` → passed.

- [ ] **Run the existing dashboard.js suite (regression).** `python -m pytest tests/integration/test_dashboard_js.py -q` → all pass (the symbols `_escape(formatKpiValue(v))`, `KPI_FILTER_MAP`, `data-kpi-key`, etc. asserted there are all still present; we extended, not removed).

- [ ] **Commit.** `git add RUCKUS/ruckus_dashboard/static/dashboard.js tests/integration/test_motion_ui.py && git commit -m "feat(ui): SP5 wire renderModule KPI glow class + count-up + refresh pulse"`

---

### Task 7: Wire `applyHealthState` — count-up the persistent health-bar values

The shell-level health bar (`applyHealthState`, `dashboard.js:584-600`) writes `v.textContent` per SSE event; route the numeric "done" path through `animateCount` (spec §4.3.2, §4.8). The `.danger` class toggle (which the glow CSS keys off) is unchanged.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/dashboard.js` (`applyHealthState` `:588-590`)
- Test: `tests/integration/test_motion_ui.py`

**Steps:**

- [ ] **Write the failing test.** Append to `tests/integration/test_motion_ui.py`:

```python
def test_dashboard_js_health_bar_counts_up():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        # the health-value count-up must be inside applyHealthState
        fn = body.split("function applyHealthState", 1)[1].split("function renderHealthBar", 1)[0]
        assert "animateCount" in fn, "applyHealthState must count up the chip value"
```

- [ ] **Run it (expect FAIL).** `python -m pytest tests/integration/test_motion_ui.py::test_dashboard_js_health_bar_counts_up -q` → FAILS: `applyHealthState must count up the chip value` (no `animateCount` between `applyHealthState` and `renderHealthBar`).

- [ ] **Implement.** In `applyHealthState`, the "done" branch currently (`dashboard.js:588-590`):

```javascript
  if (status === "done") {
    const n = pickSummaryNumber(summary);
    v.textContent = n === undefined ? "0" : formatKpiValue(n);
```

Change to count up when the picked value is finite, falling back to the existing text write otherwise:

```javascript
  if (status === "done") {
    const n = pickSummaryNumber(summary);
    const num = Number(n);
    if (n !== undefined && typeof n !== "object" && isFinite(num)) {
      _motion(m => m.animateCount(v, num, { fmt: String, duration: 320 }));
    } else {
      v.textContent = n === undefined ? "0" : formatKpiValue(n);
    }
```

(The `if (chip) { … }` block that follows is unchanged; the closing brace of the `if (status === "done")` block stays.)

- [ ] **Run tests (expect PASS).** `python -m pytest tests/integration/test_motion_ui.py::test_dashboard_js_health_bar_counts_up -q` → passed.

- [ ] **Run the health-bar regression.** `python -m pytest tests/integration/test_dashboard_js.py::test_dashboard_js_contains_health_bar -q` → passes (`renderHealthBar`, `applyHealthState`, `pickSummaryNumber`, `data-health-value` all still present).

- [ ] **Commit.** `git add RUCKUS/ruckus_dashboard/static/dashboard.js tests/integration/test_motion_ui.py && git commit -m "feat(ui): SP5 count-up persistent health-bar values in applyHealthState"`

---

### Task 8: Wire `updateTile` — count-up + entrance pulse on overview tiles

Overview tiles fill one SSE event at a time via `updateTile` (`dashboard.js:642-665`). Route the numeric "done" path through `animateCount` and fire a one-shot pulse on the tile when it resolves (spec §4.3.2–4.3.3, §4.8). `tile.dataset.tileStatus` (which the CSS color rules key off) is unchanged.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/dashboard.js` (`updateTile` `:649-665`)
- Test: `tests/integration/test_motion_ui.py`

**Steps:**

- [ ] **Write the failing test.** Append to `tests/integration/test_motion_ui.py`:

```python
def test_dashboard_js_tile_counts_up_and_pulses():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        body = c.get("/static/dashboard.js").data.decode()
        # the count-up + pulse must live inside updateTile (the SSE tile updater)
        fn = body.split("const updateTile", 1)[1].split("const finish", 1)[0]
        assert "animateCount" in fn, "updateTile must count up the resolved value"
        assert "pulse(tile" in fn or "m.pulse(tile" in fn, "tile must pulse on resolve"
```

- [ ] **Run it (expect FAIL).** `python -m pytest tests/integration/test_motion_ui.py::test_dashboard_js_tile_counts_up_and_pulses -q` → FAILS: no `animateCount`/`pulse(tile` between `const updateTile` and `const finish`.

- [ ] **Implement — count-up the done value.** In `updateTile`, the "done" branch (`dashboard.js:649-652`):

```javascript
    if (payload.status === "done") {
      const s = payload.summary || {};
      const pick = s.total ?? s.count ?? s.switches ?? Object.values(s).find(x => typeof x === "number");
      val.textContent = pick === undefined ? "0" : formatKpiValue(pick);
```

Change to count up when finite:

```javascript
    if (payload.status === "done") {
      const s = payload.summary || {};
      const pick = s.total ?? s.count ?? s.switches ?? Object.values(s).find(x => typeof x === "number");
      const num = Number(pick);
      if (pick !== undefined && typeof pick !== "object" && isFinite(num)) {
        _motion(m => m.animateCount(val, num, { fmt: String, duration: 320 }));
      } else {
        val.textContent = pick === undefined ? "0" : formatKpiValue(pick);
      }
```

- [ ] **Implement — pulse the tile on resolve.** `updateTile` ends with the progress accounting (`dashboard.js:662-665`):

```javascript
    done += 1;
    if (bar) bar.style.width = `${Math.round(100 * done / total)}%`;
    if (text) text.textContent = `Discovering RUCKUS controller… ${done}/${total}`;
  };
```

Change to fire the entrance pulse on the just-updated tile:

```javascript
    done += 1;
    if (bar) bar.style.width = `${Math.round(100 * done / total)}%`;
    if (text) text.textContent = `Discovering RUCKUS controller… ${done}/${total}`;
    _motion(m => m.pulse(tile, "refreshed"));
  };
```

- [ ] **Run tests (expect PASS).** `python -m pytest tests/integration/test_motion_ui.py::test_dashboard_js_tile_counts_up_and_pulses -q` → passed.

- [ ] **Run the warmup regression.** `python -m pytest tests/integration/test_dashboard_js.py::test_dashboard_js_contains_warmup_integration -q` → passes (`startWarmupStream`, `updateTile`, `EventSource`, `data-tile-status`, etc. all still present).

- [ ] **Commit.** `git add RUCKUS/ruckus_dashboard/static/dashboard.js tests/integration/test_motion_ui.py && git commit -m "feat(ui): SP5 count-up + entrance pulse on overview tiles in updateTile"`

---

### Task 9: Load `motion.js` before `dashboard.js` in `base.html`

The single markup change (spec §4.1 item 6, §4.8). `motion.js` must be defined before `dashboard.js` uses `window.RuckusMotion`, so the new tag goes immediately **before** the existing `dashboard.js` tag (`base.html:64`).

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/templates/base.html` (`:64`)
- Test: `tests/integration/test_motion_ui.py`

**Steps:**

- [ ] **Write the failing test.** Append to `tests/integration/test_motion_ui.py`:

```python
def test_base_html_loads_motion_before_dashboard():
    html = pathlib.Path(
        "RUCKUS/ruckus_dashboard/templates/base.html").read_text(encoding="utf-8")
    assert "filename='motion.js'" in html, "base.html must load motion.js"
    # ordering: motion.js must appear before dashboard.js so RuckusMotion is defined
    assert html.index("motion.js") < html.index("dashboard.js"), \
        "motion.js must be loaded before dashboard.js"
```

- [ ] **Run it (expect FAIL).** `python -m pytest tests/integration/test_motion_ui.py::test_base_html_loads_motion_before_dashboard -q` → FAILS: `base.html must load motion.js`.

- [ ] **Implement.** In `RUCKUS/ruckus_dashboard/templates/base.html`, the script line (`:64`):

```html
<script src="{{ url_for('static', filename='dashboard.js') }}"></script>
```

Change to (motion first):

```html
<script src="{{ url_for('static', filename='motion.js') }}"></script>
<script src="{{ url_for('static', filename='dashboard.js') }}"></script>
```

- [ ] **Run tests (expect PASS).** `python -m pytest tests/integration/test_motion_ui.py::test_base_html_loads_motion_before_dashboard -q` → passed.

- [ ] **Commit.** `git add RUCKUS/ruckus_dashboard/templates/base.html tests/integration/test_motion_ui.py && git commit -m "feat(ui): SP5 load motion.js before dashboard.js in base.html"`

---

### Task 10: CSP-regression guard — `script-src 'self'` stays exactly as-is

The core safety property of the whole feature (spec §3, §4.1, §4.6): no inline script, no CDN, CSP unchanged. Today **no test asserts the CSP header at all** (verified: `grep -c Content-Security-Policy tests/integration/test_routes_new_ui.py` → 0). This task adds the regression so a future contributor cannot loosen `script-src` to `'unsafe-inline'` (the looser policy the legacy monolith used) without a red build.

**Files:**
- Modify: none (`app.py` CSP at `:79-85` is correct and stays — assertion only)
- Test: `tests/integration/test_motion_ui.py`

**Steps:**

- [ ] **Write the failing test.** Append to `tests/integration/test_motion_ui.py`:

```python
def test_csp_script_src_is_strictly_self():
    """SP5 invariant: motion ships as same-origin files only. script-src must
    stay exactly 'self' — no 'unsafe-inline', no CDN host — so inline/3rd-party
    scripts can never be introduced silently."""
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        csp = c.get("/healthz").headers["Content-Security-Policy"]
        assert "script-src 'self'" in csp
        # the script directive must NOT permit inline or remote
        script_dir = [p.strip() for p in csp.split(";") if p.strip().startswith("script-src")][0]
        assert "unsafe-inline" not in script_dir
        assert "http://" not in script_dir and "https://" not in script_dir
        # the rest of the policy is intact (defense-in-depth unchanged)
        assert "default-src 'self'" in csp
        assert "object-src" not in csp or "object-src 'none'" in csp


def test_motion_js_is_same_origin_only_no_inline_script_in_templates():
    """No inline <script>…</script> body anywhere (only src= tags allowed)."""
    import re
    root = pathlib.Path("RUCKUS/ruckus_dashboard/templates")
    for tpl in root.rglob("*.html"):
        text = tpl.read_text(encoding="utf-8")
        for m in re.finditer(r"<script\b([^>]*)>", text):
            attrs = m.group(1)
            assert "src=" in attrs, f"inline <script> body in {tpl.name} violates CSP"
```

- [ ] **Run it (expect PASS — characterization/regression).** `python -m pytest tests/integration/test_motion_ui.py -k "csp or same_origin" -q` → PASSES immediately. This locks current correct behavior. If `test_csp_script_src_is_strictly_self` FAILS, someone has already loosened the CSP — restore `app.py:81` to `script-src 'self'`; do not weaken the test. If the inline-script test FAILS, a template added an inline `<script>` body — move that JS into a same-origin file under `static/`.

> This is the spec's mandated "CSP-regression integration test" (spec §4.9 first bullet). It passes on creation because the production CSP is already correct; its value is preventing future regressions.

- [ ] **Commit.** `git add tests/integration/test_motion_ui.py && git commit -m "test(security): SP5 lock CSP script-src 'self' + ban inline template scripts"`

---

### Task 11: Full-suite green + ruff + the spec's content checks

Final verification that the 301-test suite plus the new SP5 tests all pass and ruff is clean (spec §4.9 last bullet). Also adds the spec §4.9 "loading" assertion that `GET /static/motion.js` is 200 with a JS content-type (already covered in Task 5) and confirms nothing in `dashboard.js`/`styles.css` regressed.

**Files:**
- Modify: none
- Test: run the whole suite + ruff

**Steps:**

- [ ] **Run the new feature suite.** `python -m pytest tests/integration/test_motion_ui.py -q` → all green (expect ~20 tests).

- [ ] **Run the two adjacent JS/CSS suites in full (regression).** `python -m pytest tests/integration/test_dashboard_js.py tests/integration/test_topology_js.py tests/integration/test_static_assets.py tests/integration/test_routes_new_ui.py -q` → all green.

- [ ] **Run the entire suite.** `python -m pytest -q` → **301 prior + new SP5 tests, 0 failures.** (If a prior test broke, it will be a `test_dashboard_js.py` symbol assertion — diff your `renderModule`/`applyHealthState`/`updateTile` edits against the originals; you should only have *added* lines.)

- [ ] **Run ruff (CI parity).** `ruff check RUCKUS/ruckus_dashboard tests` → no findings. (Only the new `tests/integration/test_motion_ui.py` is Python; `motion.js`/`styles.css`/`base.html` are not linted by ruff. Keep the test file import-sorted and unused-import-free.)

- [ ] **Commit (if ruff auto-fixed anything; otherwise skip).** `git add -A && git commit -m "chore(ui): SP5 ruff clean + full-suite green"`

---

## Self-Review

### Spec coverage map

| Spec section / requirement | Where implemented | Test |
|---|---|---|
| §4.1 #1 glow/timing **token layer** | Task 1 (`:root` extension) | `test_motion_tokens_present` |
| §4.1 #1 / §4.6 **`prefers-reduced-motion` global kill-switch** | Task 1 (`@media` block) | `test_reduced_motion_global_killswitch` |
| §3 / §4.3.5 / Q5 **legacy `topo-pulse`+`toast-in` under the guard** (bug fix) | Task 1 (guard lists `.topo-node.pulse`, `.topo-toast`) | `test_reduced_motion_covers_legacy_topo_and_toast` |
| §4.1 #2 / §4.3.1 **state glow** (KPI/status/health/topology) | Task 2 | `test_state_glow_rules_present`, `test_topo_pulse_retokened_to_glow_critical` |
| §4.3.1 critical **breathing** pulse | Task 2 (`glow-critical-breathe`) | `test_critical_breathing_keyframe` |
| §4.1 #3 / §4.3.3 **tile entrance** (CSS `:nth-child` stagger) | Task 3 (`tile-enter`) | `test_entrance_and_pulse_keyframes_present`, `test_trigger_classes_present` |
| §4.3.4 **live refresh pulse** (CSS one-shot) | Task 3 (`refresh-ring`, `.module-refreshed::after`) | `test_trigger_classes_present` |
| §4.3.2 **value flash** for formatted/non-numeric | Task 3 (`value-flash`, `.value-changed`) | `test_entrance_and_pulse_keyframes_present` |
| §4.3.3 **warmup sheen** while `<100%` | Task 3 (`warmup-sheen`) | `test_entrance_and_pulse_keyframes_present` |
| §4.2 / Q3 **`body.dso-mode` glow intensify** | Task 3 | `test_dso_mode_intensifies_glow` |
| §4.3.3 preserve `.warmup-fill` **width transition** under guard | Task 4 | `test_warmup_width_transition_preserved` |
| §4.1 #4 / §4.4 **`motion.js`** `animateCount`/`pulse`/`motionReduced` | Task 5 | `test_motion_js_public_api_symbols`, `test_motion_js_is_leak_safe_and_reduced_motion_aware` |
| §4.4 **leak safety** (1 cancellable rAF/node, no `setInterval`), reduced/hidden snap | Task 5 | `test_motion_js_is_leak_safe_and_reduced_motion_aware` |
| §4.9 **`GET /static/motion.js` 200 + JS content-type** | Task 5 | `test_motion_js_served_with_js_content_type` |
| §4.1 #5 / §4.3.1 / Q1 **KPI state→class mapping** in `renderModule` | Task 6 (`kpiHealthClass`) | `test_dashboard_js_wires_kpi_state_class_and_count_up` |
| §4.3.2 / §4.8 **KPI count-up + flash** in `renderModule` | Task 6 | `test_dashboard_js_wires_kpi_state_class_and_count_up` |
| §4.3.4 / §4.8 **refresh pulse** at end of `renderModule` | Task 6 | `test_dashboard_js_wires_kpi_state_class_and_count_up` |
| §4.7 **fail-open** motion wrapper | Task 6 (`_motion`) | `test_dashboard_js_motion_is_fail_open` |
| §4.3.2 / §4.8 **health-bar count-up** in `applyHealthState` | Task 7 | `test_dashboard_js_health_bar_counts_up` |
| §4.3.2–3 / §4.8 **tile count-up + entrance pulse** in `updateTile` | Task 8 | `test_dashboard_js_tile_counts_up_and_pulses` |
| §4.1 #6 / §4.8 **one `<script>` tag, motion before dashboard** | Task 9 | `test_base_html_loads_motion_before_dashboard` |
| §3 / §4.1 / §4.6 / §4.9 **CSP stays `script-src 'self'`** (regression) | Task 10 (assertion; `app.py` unchanged) | `test_csp_script_src_is_strictly_self`, `test_motion_js_is_same_origin_only_no_inline_script_in_templates` |
| §4.9 **301-suite + ruff stay green** | Task 11 | full `pytest -q` + `ruff check` |

**Open Questions (spec §5) → all resolved in "Decisions locked" at the top** (Q1 yes/map; Q2 count-up + flash, no magnitude cutoff; Q3 reuse hues, breathe + dso-intensify; Q4 subtle module-root ring; Q5 yes, guard the legacy animations; Q6 defer GSAP). No question is left for the implementer.

### Placeholder scan
No `TBD`, `add error handling`, `similar to Task N`, or `write tests for the above` appears in any step. Every code step contains complete, runnable code: full `motion.js`, full CSS blocks, and exact before→after edits for each `dashboard.js`/`base.html` change.

### Type / name / selector consistency (must match across tasks)
- **Public JS API:** `window.RuckusMotion.{animateCount, pulse, motionReduced}` — defined in Task 5, consumed via `_motion(m => m.animateCount(...))` / `m.pulse(...)` in Tasks 6/7/8. Wrapper name `_motion` is identical in all three.
- **`animateCount(el, to, {fmt, duration})`** — signature defined once (Task 5) and every call site (Tasks 6/7/8) passes `{ fmt: String, duration: 320 }`. `320` matches `--motion-base: 320ms` (Task 1).
- **`pulse(el, cls)` → toggles class `"module-" + cls`** — Task 5 builds `module-refreshed`; CSS rule `.module-refreshed::after` defined in Task 3; reduced-motion guard lists `.module-refreshed::after` in Task 1. All three agree on the literal `module-refreshed`.
- **KPI value flash class** `value-changed` — written by Task 6 (`valEl.classList.add("value-changed")`), styled by `.value-changed` keyframe in Task 3, guarded in Task 1. Consistent.
- **KPI health classes** `ok|watch|critical|neutral` — produced by `kpiHealthClass` (Task 6), consumed by `.kpi-card.{ok,watch,critical} .kpi-value` glow rules (Task 2). The existing color rules at `styles.css:47-49` already use these exact class names, so glow layers on top without conflict.
- **`data-kpi-id`** attribute — added in Task 6 render and immediately queried via `CSS.escape` in the same Task 6 post-render loop. Self-contained to Task 6.
- **CSS tokens** `--glow-{ok,watch,critical,accent}`, `--motion-{fast,base,slow}`, `--ease-out`, `--pulse-critical-period` — declared once (Task 1), referenced by name in Tasks 2/3. No token is used before declaration.
- **Selectors that must stay byte-identical to existing code** (so glow attaches): `.kpi-card.ok/.watch/.critical`, `.status-complete/.status-partial/.status-error`, `.health-chip.danger`, `.tile[data-tile-status]`, `.warmup-fill`, `.topo-node.pulse > circle`, `.topo-node.highlight > circle`, `.tile-grid .tile` — all verified against the current `styles.css`/`dashboard.js` during planning.
- **No Python identifiers introduced** beyond test functions; `app.py`/routes/modules untouched (Task 10 asserts, never edits).

### Risk notes
- **`CSS.escape`** (Task 6) is standard in all evergreen browsers the wall display targets; KPI keys are `[a-z0-9_]` anyway, so even absent it would be safe — but it is the correct, lint-free choice.
- The only **behavior change** is KPI cards gaining `ok/watch/critical` classes on `alarms`/`rogues`/`clients` (Q1). This changes *color/glow only* (the glow rules recolor the value text exactly as the pre-existing `.kpi-card.critical .kpi-value { color }` already did) — no data, layout, or click behavior changes. The clickable-filter wiring (`data-kpi-key`) is preserved verbatim.
- **Leak posture:** `motion.js` introduces zero `setInterval` (asserted in Task 5); the lone rAF handle is cancelled before re-arm and naturally yields when `document.hidden`. The `innerHTML` rewrites in `renderModule` discard old value nodes whose `_rkRaf` was already cancelled on the prior tick, so no detached node retains a live frame callback.

---

## Execution Handoff

Two ways to execute this plan:

- **Subagent-driven (recommended).** Invoke **superpowers:subagent-driven-development**. Dispatch Tasks 1→11 in order to a fresh implementer subagent each, one task per subagent. Tasks 1–4 (CSS) and Task 5 (motion.js) are independent of each other and could be parallelized, but Tasks 6–9 depend on Task 5 (`window.RuckusMotion`) and on the CSS classes from Tasks 1–3, so keep 5→6→7→8→9 sequential. Task 10 and Task 11 are verification gates; run them last and serially. After each task, the orchestrator confirms the task's `pytest` line is green before dispatching the next.

- **Inline (single session).** Invoke **superpowers:executing-plans** and work top-to-bottom in this session, committing after every task with the exact message given. Run `python -m pytest tests/integration/test_motion_ui.py -q` after each task and the full `pytest -q` + `ruff check RUCKUS/ruckus_dashboard tests` at Task 11.

**Definition of done:** all SP5 tests in `tests/integration/test_motion_ui.py` pass; the full suite is green (301 prior tests + new SP5 tests, 0 failures); `ruff check RUCKUS/ruckus_dashboard tests` is clean; `app.py` CSP is byte-for-byte unchanged (`script-src 'self'`); the only template diff is the one `motion.js` `<script>` line in `base.html`.
