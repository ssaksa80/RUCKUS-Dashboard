# SP5 — UI Glow / Motion Polish for the DSO Wall Display

**Status:** Design spec (no implementation). Author: senior architect review.
**Date:** 2026-06-30.
**Scope:** A motion + glow layer for the RUCKUS DSO Dashboard, tuned for an always-on
network-operations wall display. Neon/glow accents keyed to health state, animated
KPI/number transitions, tile entrance + update animations, and a live "pulse" on each
data refresh. No backend or data-flow changes.

All paths are absolute under the repo root
`C:\Users\sshoaib\OneDrive - Mohamed & Obaid Almulla LLC\Documents\RUCKUS-Dashboard`
(hereafter `<root>`). The dashboard package lives at
`<root>\RUCKUS\ruckus_dashboard\`.

---

## 1. Problem & current behavior (grounded in the code)

### 1.1 What exists today

The UI is a hand-authored, zero-dependency, server-rendered Flask app. There is **no
build step and no JS package manager**: the entire static surface is three files —
`<root>\RUCKUS\ruckus_dashboard\static\styles.css`,
`<root>\RUCKUS\ruckus_dashboard\static\dashboard.js`, and
`assets\ruckus-logo.png` (confirmed: no `package.json` anywhere under `RUCKUS\`).

**Shell & theme.** `templates\base.html` is the app shell: sidebar nav, a topbar with a
DSO wall-mode toggle (`base.html:53`, `#dso-toggle`), an `{% include
"partials/health_bar.html" %}` (`base.html:60`), the page `{% block content %}`, and a
single `<script src=".../dashboard.js">` (`base.html:64`). The theme is a token block in
`styles.css:1-8`:

```
--bg #080b0f  --surface #111820  --surface-soft #17212b  --accent #22a6b3
--ok #38c172  --watch #f6c85f  --critical #ff5f57  --neutral #8391a2  --focus #5bd6e5
```

These are flat fills. There are **no glow, shadow, or "neon" tokens**, and no
`text-shadow`/`box-shadow`/`filter` rules anywhere except one drop-shadow on a topology
highlight (`styles.css:188`).

**Health states are encoded but visually flat.** Health is conveyed by color only:
`.kpi-card.ok/.watch/.critical` recolor the value text (`styles.css:47-49`); status pills
recolor background/text (`styles.css:54-58`); the persistent health bar adds a `.danger`
class to a chip when alarms/rogues `> 0` (`dashboard.js:592-593`, styled
`styles.css:142-143`). None of these states animate or glow.

**Data flow that motion must hook into (this is the crux).** The DOM is rebuilt by
`innerHTML` assignment on every poll, so any animation that lives *inside* the rewritten
subtree is destroyed and recreated each tick:

- **Overview tiles**: `startWarmupStream()` opens an `EventSource("/api/warmup")` and on
  each `module-ready` event calls `updateTile()`, which sets `tile.dataset.tileStatus`
  and writes `val.textContent` (`dashboard.js:642-665`). A progress bar width is set
  inline (`dashboard.js:663`). On SSE failure it falls back to polling
  `/api/warmup/status` every 2 s (`dashboard.js:675-701`).
- **Persistent health bar** (every page, shell-level): `renderHealthBar()` does one
  fetch of `/api/warmup/status` then subscribes to the same SSE stream; each event runs
  `applyHealthState()` which writes `v.textContent` and toggles `.danger`
  (`dashboard.js:584-619`).
- **Module pages**: `startModulePoller(slug, pollSeconds)` ticks on an interval
  (`Math.max(5, pollSeconds) * 1000`, `dashboard.js:93`), skipping when `document.hidden`
  (`dashboard.js:84`). Each tick `fetchModule()` → `renderModule()` **replaces** the KPI
  strip via `strip.innerHTML = …` (`dashboard.js:138-145`) and the data area via
  `area.innerHTML = …` (`renderColumns` `dashboard.js:356`, `renderGrid`
  `dashboard.js:328`). KPI values already carry `aria-live="polite"` (`dashboard.js:143`,
  and `kpi_card.html:3`).
- **Visibility**: the poller early-returns while hidden (`dashboard.js:84`) and force-
  refreshes on `visibilitychange` when shown (`dashboard.js:713-717`).

**DSO wall mode.** Toggling `#dso-toggle` adds `body.dso-mode`, which hides sidebar +
topbar + health bar and enlarges KPI values to 48px (`styles.css:59-65`, `:156`). A
floating "Exit wall" button + Escape key prevent lock-in (`dashboard.js:718-738`). This
is the always-on display surface motion is being designed for.

**Existing animation + the accessibility gap.** Two `@keyframes` already exist and run
**unconditionally**: `topo-pulse` (`styles.css:181-186`, infinite pulse on alerting
topology nodes) and `toast-in` (`styles.css:201`). There is exactly one CSS `transition`
(`.warmup-fill { transition: width .3s }`, `styles.css:108`). Critically, a project-wide
search finds **zero `prefers-reduced-motion` blocks** — the current infinite topology
pulse already ignores the OS reduce-motion setting.

**CSP — the hard constraint.** The live app factory sets, in `app.py:79-85`:

```
script-src 'self';
style-src  'self' 'unsafe-inline';
img-src    'self' data:;
connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
```

`script-src 'self'` means **no inline `<script>`, no `eval`, and no third-party CDN
script** — any JS must ship as a same-origin file under `static\`. (Note: the *legacy*
monolith `networker_dashboard.py:11523` used the looser `script-src 'self'
'unsafe-inline'`, but the packaged app deliberately tightened it; this spec targets the
packaged app.) `style-src` permits inline style **attributes**, which is why the inline
`fill.style.width` and warmup widths work; that allowance is what CSS-driven motion can
lean on.

### 1.2 The problem

The dashboard is functional but visually static and not tuned for an always-on wall:

1. **No state legibility at distance.** On a wall TV viewed from across a NOC, a flat
   red number is easy to miss. Critical/watch states need a glow + motion signature that
   reads peripherally.
2. **No change cue.** Because the KPI strip and data area are wiped and rewritten every
   poll (`dashboard.js:138`, `:356`), values change with no transition — an operator
   cannot tell *what* just updated or *that* a refresh happened at all.
3. **Tiles appear abruptly.** Warmup fills tiles one SSE event at a time
   (`dashboard.js:649-661`) with a hard text swap and no entrance.
4. **Accessibility + always-on risk.** Any motion added naively will (a) ignore
   `prefers-reduced-motion` (as `topo-pulse` already does) and (b) risk unbounded
   timers/elements over a multi-day uptime — a real memory-leak surface given the
   destroy/recreate render loop.

---

## 2. Approaches considered

### Approach A — CSS-only (keyframes + transitions + CSS custom-property tweening)

Add a glow/motion token layer and animations entirely in `styles.css`, driven by the
`data-*` attributes and state classes the JS **already** sets (`data-tile-status`,
`.kpi-card.ok/.watch/.critical`, `.health-chip.danger`, `.status-pill`). Number
"count-up" is approximated with CSS `@property <integer>` transitions, or skipped in
favor of a flash/glow pulse on change. A tiny same-origin JS helper (added to the
existing `dashboard.js`) toggles a transient class for "just refreshed" pulses.

- **Pros**
  - **Zero CSP friction** — no new script source; everything is `style-src`-legal
    (`app.py:79-85`). No new files strictly required for the glow layer.
  - **GPU-composited** `transform`/`opacity`/`filter`/`box-shadow` animations; the
    browser pauses CSS animations on `document.hidden`, complementing the existing
    poller gate (`dashboard.js:84`).
  - **No memory leak by construction** — declarative keyframes hold no JS timers or
    retained nodes; ideal for multi-day uptime.
  - `prefers-reduced-motion` is a one-block global kill-switch.
  - Smallest diff, smallest risk, no dependency to vendor/audit/update.
- **Cons**
  - True number tweening (e.g. 41 → 57 counting up) is awkward. `@property`-based
    integer transitions work in current Chromium/WebKit but are clumsy for formatted
    values (`humanBytes`, `GET 379 · POST 362` — `dashboard.js:24,58-62`) and have weaker
    cross-browser support.
  - Choreographed/sequenced timelines (stagger a tile grid, then pulse KPIs) are
    verbose and fragile in pure CSS.
  - Re-triggering a keyframe on each poll requires a JS class-toggle reflow dance because
    the nodes are recreated anyway.

### Approach B — GSAP (GreenSock) timelines

Vendor GSAP as a local file (`static\vendor\gsap.min.js`) — **never** a CDN, to stay
within `script-src 'self'`. Animate KPI count-ups, tile entrance staggers, and glow
pulses via JS timelines triggered from the render functions.

- **Pros**
  - Best-in-class number tweening (counts up formatted values), staggered grids,
    sequenced timelines, and fine easing — the "premium" motion ask.
  - One API for entrance + update + exit; pause/resume hooks.
- **Cons**
  - **CSP/operational cost**: must self-host and **version-pin + audit** a ~70 KB
    minified third-party script under `static\vendor\` (no `package.json`/build exists to
    manage it — `app.py` serves `static\` directly). Supply-chain + update burden the
    project currently has zero of.
  - **Memory-leak risk is real here**: the render loop rebuilds the KPI strip and data
    area via `innerHTML` every poll (`dashboard.js:138`, `:356`). Every GSAP tween/
    timeline targeting those nodes must be explicitly `kill()`ed or it retains detached
    DOM and accumulates over a multi-day wall session. This is exactly the always-on
    leak the brief warns against, and it becomes the maintainer's responsibility.
  - GSAP does **not** auto-pause on tab hidden or honor `prefers-reduced-motion`; both
    must be wired manually (global timeline pause on `visibilitychange`, and a reduced-
    motion guard) — re-implementing what CSS gives free.
  - Heaviest diff and the only approach that adds a runtime dependency.

### Approach C — Hybrid: CSS for state/ambient motion + a tiny vanilla JS tween util for numbers (recommended)

Do all **ambient and state-driven** motion in CSS (glow tokens, entrance, refresh pulse,
critical/watch pulse, progress bar) keyed off the attributes/classes the JS already
emits. Add **one small same-origin module** (`static\motion.js`, ~120–180 lines, no
dependency) that does only the things CSS does poorly: a `rAF` number count-up that
respects formatting, and a single class-toggle to fire the "refresh pulse." All triggers
are folded into the existing render functions in `dashboard.js`.

- **Pros**
  - **CSP-clean**: `motion.js` is same-origin (`script-src 'self'` OK), loaded by adding
    one `<script>` line to `base.html`. No vendor, no audit, no CDN.
  - Gets the high-value number tween without GSAP's weight or supply chain.
  - Inherits CSS's free wins: GPU compositing, auto-pause on hidden, one-line
    `prefers-reduced-motion` kill-switch covering the ambient layer.
  - **Leak-safe**: the count-up util is self-cancelling (one `requestAnimationFrame`
    handle per element, cancelled before re-arming and on hidden), and it animates the
    KPI **value node in place** rather than spawning retained objects.
- **Cons**
  - A small amount of bespoke JS to own and test (mitigated: it is tiny, pure, and unit-
    testable).
  - Not as turnkey as GSAP for future complex choreography (acceptable: the dashboard's
    needs are modest and well-bounded).

---

## 3. Recommendation

**Adopt Approach C (Hybrid).** It delivers the wall-display polish — neon state glow,
count-up KPIs, tile entrances, live refresh pulse — while preserving the two properties
that matter most for this product: **CSP integrity** (`script-src 'self'`, no vendored
third-party script) and **always-on safety** (no leak, auto-pause when hidden, full
`prefers-reduced-motion` support). GSAP's advantages (complex sequenced timelines) are
not justified by the current scope and would impose a supply-chain + manual lifecycle
burden on a codebase that today has **zero** JS dependencies and no build step.

The work also **fixes a pre-existing bug**: the current `topo-pulse` animation
(`styles.css:186`) runs infinitely with no reduced-motion guard; the new global
`prefers-reduced-motion` block will bring it into compliance.

---

## 4. Design of the recommended approach

### 4.1 Components & where they live

| # | Component | File | Nature |
|---|-----------|------|--------|
| 1 | Glow/motion **token layer** + `prefers-reduced-motion` kill-switch | `static\styles.css` (extend `:root`, new section at end) | CSS |
| 2 | **State glow + pulse** rules (KPI, status pill, health chip, tile, topology) | `static\styles.css` | CSS |
| 3 | **Entrance / refresh-pulse** keyframes + trigger classes | `static\styles.css` | CSS |
| 4 | **Number count-up** util + reduced-motion/visibility helpers | `static\motion.js` (NEW, same-origin) | JS |
| 5 | **Trigger wiring** (call util + toggle pulse class from render loop) | `static\dashboard.js` (edit existing fns) | JS |
| 6 | One `<script>` tag for `motion.js` | `templates\base.html` | HTML |

No new routes, no Python changes, no template markup changes **except** the single
script tag. The CSP in `app.py:79-85` is **unchanged** and explicitly remains
`script-src 'self'` (this is a feature of the design, called out so reviewers confirm it).

### 4.2 Token & theme changes (`styles.css:1-8` extension)

Add glow + timing tokens to `:root` (additive; existing tokens untouched). Illustrative
names/values:

```
--glow-ok, --glow-watch, --glow-critical, --glow-accent   /* rgba halos per state */
--motion-fast: 180ms; --motion-base: 320ms; --motion-slow: 1.6s;
--ease-out: cubic-bezier(.22,.61,.36,1);
--pulse-critical-period: 1.4s;            /* matches existing topo-pulse cadence */
```

A `data-theme="wall"` is **not** required — `body.dso-mode` (already toggled,
`dashboard.js:721`) is the hook to **intensify** glow on the wall (e.g. larger halo
radius, slightly higher opacity) while keeping desk mode subtle.

### 4.3 What animates, precisely

1. **Health-state glow (ambient, CSS).**
   - `.kpi-card.critical` / `.status-error` / `.health-chip.danger` → `box-shadow`/
     `text-shadow` halo in `--glow-critical` with a slow breathing pulse
     (`--pulse-critical-period`). `.watch`/`.status-partial` → steady (non-pulsing)
     `--glow-watch` halo. `.ok`/`.status-complete` → faint static `--glow-ok` rim.
   - Hooks already set by JS/templates: `dashboard.js:142` (`kpi-card neutral`,
     extended), `:592-593` (`.danger`), `styles.css:56-58` (status pills),
     `kpi_card.html:1`.
   - **Decision needed (see Open Questions):** today KPI cards are emitted as
     `kpi-card neutral` from JS (`dashboard.js:142`) and never get `ok/watch/critical`
     — only the server-rendered `kpi_card.html` partial supports `kind`. To glow KPI
     cards by health, JS must map state→class (small change in `renderModule`).

2. **KPI number transition (count-up, JS util + CSS).**
   - On each poll, `renderModule` (`dashboard.js:131-145`) currently writes the value via
     `innerHTML`. New behavior: detect a changed numeric value and animate
     old→new with `animateCount()` from `motion.js`; non-numeric/formatted values
     (dicts, `humanBytes`, `humanRate` — `dashboard.js:24-62`) **skip the tween** and get
     a brief CSS "value-changed" flash instead. `aria-live="polite"` is already present
     (`dashboard.js:143`), so screen readers announce the final value once.
   - Same util powers the **health bar** values (`applyHealthState`, `dashboard.js:589`)
     and **overview tiles** (`updateTile`, `dashboard.js:649-661`).

3. **Tile entrance + warmup (CSS).**
   - `.tile` gets a staggered fade/scale-in on first paint via `animation-delay` keyed
     to `:nth-child` (pure CSS — no JS list needed). On `data-tile-status` transitioning
     to `done/failed/disabled` (`dashboard.js:646`), a CSS transition swaps the skeleton-
     muted look (`styles.css:111-113`) to the resolved color with a short glow ping.
   - `.warmup-fill` already transitions width (`styles.css:108`); add a subtle moving
     sheen while `< 100%`, removed at complete (`finish()`, `dashboard.js:667`).

4. **Live refresh pulse (JS one-liner trigger + CSS).**
   - On every successful `fetchModule`/poll tick, toggle a transient class (e.g.
     `module-refreshed`) on the module root or freshness strip; CSS plays a one-shot
     ~600 ms ring/sweep so operators see "data just refreshed." Re-arm pattern: remove
     class → force reflow → add class, or use `animationend` to self-clean. Hook point:
     end of `renderModule` (`dashboard.js:177`) and `updateTile` (`dashboard.js:665`).

5. **Topology pulse (CSS, compliance fix).**
   - Keep `topo-pulse` (`styles.css:186`) but bring it under the new
     `prefers-reduced-motion` block and re-token its color to `--glow-critical` for
     consistency.

### 4.4 `motion.js` — interface (tiny, dependency-free)

Illustrative signatures only (no implementation):

```js
// animate a numeric text node from its current value to `to`, formatted by `fmt`.
// self-cancels any in-flight rAF on the same node; no-ops under reduced motion or hidden.
animateCount(el, to, { fmt = String, duration = 320 } = {})

// fire a one-shot CSS pulse by toggling `cls` with reflow re-arm + animationend cleanup.
pulse(el, cls = "refreshed")

// true when (prefers-reduced-motion: reduce) matches; used as a global guard.
motionReduced()
```

Behavior rules baked in:
- **Reduced motion:** if `motionReduced()`, `animateCount` sets the final value
  immediately and `pulse` is a no-op. (Belt-and-suspenders with the CSS block.)
- **Hidden tab:** `animateCount` snaps to final if `document.hidden` (mirrors the
  poller gate, `dashboard.js:84`); ambient CSS animations pause automatically.
- **Leak safety:** at most one `requestAnimationFrame` handle per element, stored on the
  node and `cancelAnimationFrame`'d before re-arming; no global growing arrays, no
  `setInterval`. Nothing retains detached nodes across the `innerHTML` rewrites.

### 4.5 Data flow (unchanged transport, new presentation hooks)

```
SSE /api/warmup  ──► updateTile()      ─┐
poll /warmup/status ─► applyHealthState() ─┼─► [motion.js animateCount + CSS state class] ─► glow/count-up
interval poll  ──► renderModule()  ─────┘                         │
                                                                   └─► pulse(root,"refreshed") ─► CSS one-shot
```

The animation layer is **read-only** over existing payloads (`payload.summary`,
`payload.status`, warmup `state.summary/status`). No new fields, endpoints, or polling.

### 4.6 Accessibility, performance, CSP

- **`prefers-reduced-motion: reduce`** → one global block at the top of the new CSS
  section disables/*flattens* every keyframe and transition (sets `animation: none;
  transition: none;` for the motion classes, including the legacy `topo-pulse` and
  `toast-in`). Glow *color* states remain (color is information, not motion).
- **Always-on / no leak:** only GPU-friendly properties animate (`opacity`,
  `transform`, `filter`, `box-shadow`); CSS animations auto-pause when the tab/display is
  backgrounded; `motion.js` holds a single cancellable rAF per node. No `setInterval` is
  introduced (the only timers remain the existing poller and SSE).
- **CSP:** `motion.js` is served from `static\` (same-origin) and referenced by a
  `<script src>` in `base.html` — fully compatible with `script-src 'self'`
  (`app.py:81`). No inline scripts, no `eval`, no CDN. Inline *style attributes* already
  permitted by `style-src 'unsafe-inline'` (`app.py:82`) are not newly relied upon beyond
  what exists.

### 4.7 Error handling & degradation

- `motion.js` must **fail open**: if it throws or is blocked, values still update (the
  existing `textContent`/`innerHTML` writes remain the source of truth; the tween is an
  enhancement layered on the same final value). Wrap util calls so a throw never breaks
  `renderModule`.
- If `matchMedia` is unavailable, treat as motion-allowed but keep the CSS guard.
- Skeleton/`measuring…`/`—` placeholders (`dashboard.js:35,45`, `tile_skeleton.html`)
  are non-numeric and naturally skip count-up.

### 4.8 Files / functions that change

- **`static\styles.css`** — extend `:root` (after line 8) with glow/timing tokens; add a
  new trailing section: `@media (prefers-reduced-motion: reduce)` kill-switch; state-glow
  rules for `.kpi-card.{ok,watch,critical}` (`:47-49`), `.status-{complete,partial,error}`
  (`:56-58`), `.health-chip.danger` (`:142-143`), `.tile[data-tile-status]` (`:111-113`);
  `@keyframes` for tile entrance, refresh pulse, critical breathing, warmup sheen;
  re-token `topo-pulse` (`:181-188`) and `toast-in` (`:201`) under the guard;
  `body.dso-mode` glow-intensify overrides (near `:59-65`).
- **`static\motion.js`** — NEW. `animateCount`, `pulse`, `motionReduced` (Section 4.4).
- **`static\dashboard.js`** — wire triggers in: `renderModule` (KPI value tween +
  state-class mapping + `pulse`, around `:138-145`/`:177`); `applyHealthState`
  (count-up health values, `:589`); `updateTile` (count-up + entrance state, `:649-665`).
  No structural/logic changes — only the value-writing lines gain a tween/pulse call,
  guarded to fail open.
- **`templates\base.html`** — add one `<script src="{{ url_for('static',
  filename='motion.js') }}">` immediately **before** the existing `dashboard.js` tag
  (`base.html:64`) so the util is defined before use.
- **No change** to `app.py` (CSP stays `script-src 'self'`), routes, or any partial
  markup.

### 4.9 Testing

- **CSP/loading (integration, pytest):** extend the existing new-UI route tests
  (`<root>\tests\integration\test_routes_new_ui.py`) to assert (a) `base.html` references
  `motion.js` via `url_for`, (b) the response CSP header is **still** exactly
  `script-src 'self'` (regression guard that no one loosened it), and (c) `GET
  /static/motion.js` returns 200 with a JS content-type.
- **Unit (JS):** if/when a JS test runner is added, unit-test `animateCount` (snaps to
  final under reduced motion and when `document.hidden`; cancels prior rAF; formats via
  `fmt`) and `pulse` (self-cleans on `animationend`). Until then, document a manual
  matrix.
- **Reduced-motion (manual + ideally automated):** with `prefers-reduced-motion: reduce`,
  confirm zero animation/transition on KPI cards, tiles, status pills, **and** topology
  (the bug fix) — values still update, glow colors still present.
- **Always-on leak check (manual):** run the wall view for an extended session with
  DevTools Performance/Memory; assert detached-node count and JS heap are flat across
  many poll cycles (specifically that the KPI-strip `innerHTML` rewrites at
  `dashboard.js:138` leave no retained rAF/listeners).
- **Visual/behavioral:** count-up fires only on numeric change; formatted values
  (`humanBytes`/`humanRate`/dict KPIs) flash rather than count; refresh pulse fires once
  per poll; `body.dso-mode` shows intensified glow.
- **Existing suite:** the 301-test suite + ruff must stay green; this change touches no
  Python logic, so risk is confined to the one CSP-assertion addition and the new static
  file route.

---

## 5. Open questions for the user

1. **KPI card health coloring.** JS currently emits all KPI cards as `kpi-card neutral`
   (`dashboard.js:142`), so the `ok/watch/critical` glow has nothing to attach to on
   module pages. Do you want me to add a state→class mapping in `renderModule` (e.g.
   alarms/rogues > 0 → `critical`), or keep glow limited to the health-bar `.danger`
   chip and status pills that are already state-classed? A mapping is the higher-impact
   choice but is a (small) behavioral change.
2. **Count-up vs. flash for big numbers.** For large client counts (thousands), do you
   prefer a true count-up animation, or a faster crossfade/flash to avoid a "slot-
   machine" feel on the wall? Default proposed: count-up under ~1000, flash above.
3. **Glow intensity & color.** Should critical glow use the existing `--critical
   #ff5f57`, or a punchier dedicated neon (e.g. magenta/red-orange) reserved for wall
   mode only? And is a *breathing* (pulsing) critical glow acceptable, or do you want
   critical to glow **steadily** to avoid distraction over a multi-hour shift?
4. **Refresh pulse prominence.** A full-tile ring sweep on every poll (default 30 s,
   `module.html` `data-poll`) can be lively. Prefer a subtle freshness-dot ping near the
   `[data-freshness]` timestamp (`module.html:11`) instead?
5. **Scope of the reduced-motion fix.** Confirm it's desirable to bring the **existing**
   `topo-pulse`/`toast-in` (`styles.css:186,201`) under the new
   `prefers-reduced-motion` guard as part of this work (recommended — it's currently a
   latent accessibility gap), versus leaving them untouched.
6. **GSAP escape hatch.** If future roadmap includes richer choreography (e.g. animated
   topology re-layout, sequenced multi-panel storytelling), should the design pre-reserve
   a self-hosted `static\vendor\` location + an audit/version-pin convention now, or
   defer until concretely needed?
