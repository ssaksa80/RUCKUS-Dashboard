# SP4 — Topology Health-Glow Wall + Traffic-Flow View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the existing zero-dependency SVG topology renderer into a NOC "health-glow" dark wall (default `graph` view: severity-weighted node size/glow, status ribbon, problems-only filter, reduced-motion-safe) and add a second deterministic layered traffic-flow `flow` view, toggled in the toolbar, reusing the existing fetch envelope, edge weights, and live client rates.

**Architecture:** The Flask server contract is unchanged for Phases 1–2 — `modules/topology.py` keeps returning `{nodes, edges, legend, items}` and the layout-persistence API (`routes/topology_layout.py`) is untouched. All new behavior lives in the client renderer `static/topology.js`, which gains a `topoState.view` dispatch (`graph` | `flow`) inside `renderTopology`, plus pure helper functions (`healthWeight`, `filterProblemsOnly`, `layoutLayered`, `renderFlow`, `setView`) that are unit-tested in Node. Phase 3 optionally enriches `flow` with SwitchM port throughput behind the existing capability gate; `"flow"` is registered as a valid view in `modules/_base.py` and advertised via `supports_views`.

**Tech Stack:** Python 3.10–3.12 + Flask (server, pytest + `responses` for HTTP mocking); vanilla ES (zero-dependency browser SVG renderer); Node.js (CommonJS) for client-side pure-function unit tests driven from pytest via `subprocess`; ruff for linting; CSS keyframes + `filter: drop-shadow` for glow theme.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `RUCKUS/ruckus_dashboard/modules/_base.py` | Add `"flow"` to `VALID_VIEWS` so `supports_views=("graph","flow")` validates | 1 |
| `RUCKUS/ruckus_dashboard/static/topology.js` | Bootstrap guard + CommonJS export (Node-testability); `healthWeight`; status-ribbon update; `filterProblemsOnly` + problems-only toggle; glow render encoding; `layoutLayered`; `renderFlow`; `setView` view dispatch | 2, 3, 4, 5, 7, 8, 9, 10, 12 |
| `RUCKUS/ruckus_dashboard/templates/topology.html` | Add status-ribbon element, `[data-topo-view]` graph/flow toggle, `Problems only` toggle to the toolbar | 6, 11 |
| `RUCKUS/ruckus_dashboard/static/styles.css` | Glow/gradient node theme + reduced-motion guard; status-ribbon styles; view-toggle + problems-only button styles; flow-column/flow-ribbon styles | 4, 6, 11, 9 |
| `RUCKUS/ruckus_dashboard/modules/topology.py` | Advertise `supports_views=("graph","flow")`; Phase 3: best-effort `_port_flow(ctx)` + optional `flow` key in `fetch()` | 12, 13, 14 |
| `RUCKUS/ruckus_dashboard/routes/topology_layout.py` | **No change** (flow is deterministic, writes no pins) | — |
| `tests/unit/modules/test_base.py` | Assert `"flow"` is an accepted view | 1 |
| `tests/integration/test_topology_js.py` | Symbol-presence tests for new JS functions, template hooks, CSS classes | 2, 6, 7, 8, 9, 11 |
| `tests/integration/test_topology_node.py` | **New** — Node-run behavioral tests for `healthWeight`, `filterProblemsOnly`, `layoutLayered`, `renderFlow` (skip if `node` absent) | 2, 3, 7, 8, 10 |
| `tests/unit/modules/test_topology.py` | Server tests for `supports_views`; Phase 3 `_port_flow` + `fetch()` flow key | 12, 13, 14 |

**Phasing (per spec §5.7):**
- **Phase 1 (A, client-only, no server data change):** Tasks 1–7 — health-glow theme, status ribbon, problems-only filter, Node-test harness.
- **Phase 2 (D, client-only):** Tasks 8–12 — layered flow layout + render, view toggle, `supports_views=("graph","flow")`.
- **Phase 3 (D-rich, optional):** Tasks 13–14 — SwitchM port throughput enrichment behind capability gate.

---

## Phase 1 — Concept A: NOC Health-Glow Wall

### Task 1 — Register `"flow"` as a valid view

The renderer's view toggle and `modules/topology.py` will advertise `supports_views=("graph","flow")`. `ModuleSpec.__post_init__` validates every view against `VALID_VIEWS` (`_base.py:67-69`), and `"flow"` is **not** in that set today (`_base.py:8`). Add it first so later tasks can register the view without tripping validation.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/modules/_base.py` (line 8)
- Test: `tests/unit/modules/test_base.py` (append)

Steps:

- [ ] Add the failing test. Append to `tests/unit/modules/test_base.py`:

```python
def test_module_spec_accepts_flow_view():
    spec = ModuleSpec(
        slug="x", title="X", group="Cross-cutting", icon="?",
        poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=noop_summary,
        requires_platforms=("smartzone",), requires_capabilities=(),
        supports_views=("graph", "flow"),
    )
    assert "flow" in spec.supports_views
```

- [ ] Run it, expect FAIL. Command: `python -m pytest tests/unit/modules/test_base.py::test_module_spec_accepts_flow_view -q`. Expected failure: `ValueError: unknown view 'flow'; allowed: {...}` raised from `__post_init__` because `"flow"` is missing from `VALID_VIEWS`.

- [ ] Minimal implementation. In `RUCKUS/ruckus_dashboard/modules/_base.py`, change line 8 from:

```python
VALID_VIEWS = {"table", "grid", "heatmap", "chart", "tree", "graph"}
```

to:

```python
VALID_VIEWS = {"table", "grid", "heatmap", "chart", "tree", "graph", "flow"}
```

- [ ] Run tests, expect PASS. Command: `python -m pytest tests/unit/modules/test_base.py -q`. Expected: all pass (including the existing `test_module_spec_rejects_invalid_view`, which uses `"invalid-view"`, still raises).

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/modules/_base.py tests/unit/modules/test_base.py
git commit -m "feat(topology): allow 'flow' as a valid module view"
```

---

### Task 2 — Make `topology.js` Node-testable (bootstrap guard + CommonJS export)

The new pure functions must be behaviorally unit-tested (spec §5.5: deterministic layout, monotonic health weight, finite ribbon widths). `topology.js` is a browser script whose bottom bootstrap (`document.addEventListener("DOMContentLoaded", …)`, line 656) runs at load time, so a bare `require()` throws `ReferenceError: document is not defined`. Guard the bootstrap and append a guarded `module.exports` so Node can import the module without a DOM, while the browser path is unchanged.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/topology.js` (line 656; end of file)
- Test: `tests/integration/test_topology_node.py` (**new**), `tests/integration/test_topology_js.py` (append)

Steps:

- [ ] Add the failing Node harness test. Create `tests/integration/test_topology_node.py`:

```python
"""Node-run behavioural tests for the topology renderer's pure functions.

topology.js is a browser script; Task 2 adds a guarded CommonJS export so the
pure layout/encoding helpers can be required and exercised under Node. These
tests skip (not fail) where node is unavailable so the suite stays green on
machines without a JS runtime; CI runners (ubuntu/windows) ship node."""
import json
import pathlib
import shutil
import subprocess

import pytest

JS = pathlib.Path("RUCKUS/ruckus_dashboard/static/topology.js").resolve()
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def _run(snippet: str) -> dict:
    """Execute a JS snippet that requires topology.js and prints JSON to stdout."""
    prog = (
        f"const T = require({json.dumps(str(JS))});\n"
        f"{snippet}\n"
    )
    out = subprocess.run([NODE, "-e", prog], capture_output=True, text=True,
                         timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_topology_js_requires_under_node():
    got = _run('console.log(JSON.stringify(Object.keys(T).sort()));')
    assert "fmtRate" in got
```

- [ ] Run it, expect FAIL. Command: `python -m pytest tests/integration/test_topology_node.py -q`. Expected failure: `AssertionError` on `out.returncode == 0` whose `stderr` contains `ReferenceError: document is not defined` (bare require runs the bootstrap), OR `Cannot find module` semantics — either way non-zero exit before any export exists.

- [ ] Minimal implementation, part 1 — guard the bootstrap. In `RUCKUS/ruckus_dashboard/static/topology.js`, change line 656 from:

```javascript
document.addEventListener("DOMContentLoaded", () => {
```

to:

```javascript
if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", () => {
```

- [ ] Minimal implementation, part 2 — append the guarded export at the very end of `RUCKUS/ruckus_dashboard/static/topology.js` (after the closing `});` of the bootstrap):

```javascript

// Node-only export for unit tests (no-op in the browser). Keep this list in
// sync with the pure functions exercised by tests/integration/test_topology_node.py.
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    fmtRate, nodeRadius, layoutGraph, visibleGraph, edgePath,
  };
}
```

- [ ] Run tests, expect PASS. Command: `python -m pytest tests/integration/test_topology_node.py -q`. Expected: `test_topology_js_requires_under_node` passes (exports include `fmtRate`).

- [ ] Add a symbol-presence guard so the export is never accidentally removed. Append to `tests/integration/test_topology_js.py`:

```python
def test_topology_js_has_node_export():
    js = pathlib.Path("RUCKUS/ruckus_dashboard/static/topology.js").read_text(encoding="utf-8")
    assert 'typeof module !== "undefined"' in js
    assert 'typeof document !== "undefined"' in js
    assert "module.exports" in js
```

- [ ] Run the full topology JS suite, expect PASS. Command: `python -m pytest tests/integration/test_topology_js.py tests/integration/test_topology_node.py -q`.

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/static/topology.js tests/integration/test_topology_node.py tests/integration/test_topology_js.py
git commit -m "test(topology): make topology.js node-requireable for unit tests"
```

---

### Task 3 — `healthWeight(node)` severity scalar

Health-glow sizing/glow is driven by problem severity, not tree depth (spec §1.3, Concept A). Add a pure `healthWeight(n) -> number` in `[0,1]` that is monotonic: `offline ≥ flagged ≥ online ≥ unknown`, and within `offline` increases with the fraction of down APs (`meta.ap_down / meta.ap_total`) and with `meta.alarm_count`. This scalar feeds node radius and glow in Task 4.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/topology.js` (add function near `nodeRadius`, after line 74; extend export list)
- Test: `tests/integration/test_topology_node.py` (append)

Steps:

- [ ] Add the failing test. Append to `tests/integration/test_topology_node.py`:

```python
def test_health_weight_monotonic_in_severity():
    got = _run(
        "const off={status:'offline',meta:{}};"
        "const fl={status:'flagged',meta:{}};"
        "const on={status:'online',meta:{}};"
        "const un={status:'unknown',meta:{}};"
        "console.log(JSON.stringify("
        "[T.healthWeight(off),T.healthWeight(fl),T.healthWeight(on),T.healthWeight(un)]));"
    )
    off, fl, on, un = got
    assert off >= fl >= on >= un
    assert 0.0 <= un and off <= 1.0


def test_health_weight_scales_with_down_aps_and_alarms():
    got = _run(
        "const few={status:'flagged',meta:{ap_total:10,ap_down:1,alarm_count:0}};"
        "const many={status:'flagged',meta:{ap_total:10,ap_down:9,alarm_count:3}};"
        "console.log(JSON.stringify([T.healthWeight(few),T.healthWeight(many)]));"
    )
    few, many = got
    assert many > few


def test_health_weight_never_nan():
    got = _run(
        "const n={status:'offline',meta:{ap_total:0,ap_down:0}};"
        "console.log(JSON.stringify(isFinite(T.healthWeight(n))));"
    )
    assert got is True
```

- [ ] Run it, expect FAIL. Command: `python -m pytest tests/integration/test_topology_node.py -k health_weight -q`. Expected failure: non-zero exit with `stderr` containing `TypeError: T.healthWeight is not a function` (not yet defined / not exported).

- [ ] Minimal implementation. In `RUCKUS/ruckus_dashboard/static/topology.js`, insert immediately after `nodeRadius` (after line 74):

```javascript
const SEVERITY_BASE = { offline: 0.7, flagged: 0.45, online: 0.18, unknown: 0.05 };

function healthWeight(n) {
  // Severity scalar in [0,1] driving health-glow size/glow. Monotonic in
  // status (offline > flagged > online > unknown); within a status, grows
  // with the fraction of down APs and with active alarm count. Never NaN.
  const base = SEVERITY_BASE[n.status] != null ? SEVERITY_BASE[n.status] : SEVERITY_BASE.unknown;
  const meta = n.meta || {};
  const total = Number(meta.ap_total) || 0;
  const down = Number(meta.ap_down) || 0;
  const downFrac = total > 0 ? down / total : 0;
  const alarms = Number(meta.alarm_count) || 0;
  const alarmBoost = Math.min(0.2, alarms * 0.05);
  const w = base + downFrac * 0.25 + alarmBoost;
  return Math.max(0, Math.min(1, w));
}
```

- [ ] Extend the export. In the `module.exports` block at the end of `topology.js`, add `healthWeight` so the line reads:

```javascript
    fmtRate, nodeRadius, layoutGraph, visibleGraph, edgePath, healthWeight,
```

- [ ] Run tests, expect PASS. Command: `python -m pytest tests/integration/test_topology_node.py -k health_weight -q`. Expected: 3 passed.

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/static/topology.js tests/integration/test_topology_node.py
git commit -m "feat(topology): healthWeight severity scalar for health-glow"
```

---

### Task 4 — Apply health-glow encoding in the graph render + glow CSS

Wire `healthWeight` into the `graph` render so node radius and glow intensity track severity, and add the glow theme to CSS. Per spec §5.3 this evolves the existing `renderTopology` node paint (`topology.js:359-377`); the glow is a CSS `drop-shadow` whose strength is set per-node via a CSS custom property `--glow` computed from `healthWeight`. Reduced-motion users must not get pulsing (spec: "reduced-motion-safe").

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/topology.js` (node paint loop, lines 359-377)
- Modify: `RUCKUS/ruckus_dashboard/static/styles.css` (after line 204)
- Test: `tests/integration/test_topology_js.py` (append), `tests/integration/test_topology_node.py` (append)

Steps:

- [ ] Add the failing CSS-symbol test. Append to `tests/integration/test_topology_js.py`:

```python
def test_topology_css_has_glow_and_reduced_motion():
    css = pathlib.Path("RUCKUS/ruckus_dashboard/static/styles.css").read_text(encoding="utf-8")
    for rule in [".topo-node.glow", "--glow", "prefers-reduced-motion"]:
        assert rule in css, f"missing {rule}"
```

- [ ] Add the failing render test (Node, via a minimal DOM-free string check of the produced SVG). Append to `tests/integration/test_topology_node.py`:

```python
def test_render_node_markup_carries_glow_style():
    # nodeGlowStyle(n) returns the inline style string applied to each node <g>.
    got = _run(
        "const off={id:'z1',status:'offline',type:'zone',meta:{ap_total:4,ap_down:4}};"
        "const on={id:'z2',status:'online',type:'zone',meta:{ap_total:4,ap_down:0}};"
        "const so=T.nodeGlowStyle(off), sn=T.nodeGlowStyle(on);"
        "console.log(JSON.stringify({so, sn, hasVar: so.indexOf('--glow')>=0}));"
    )
    assert got["hasVar"] is True
    # offline node must request a stronger glow than the online one
    import re
    fo = float(re.search(r"--glow:\s*([0-9.]+)", got["so"]).group(1))
    fn = float(re.search(r"--glow:\s*([0-9.]+)", got["sn"]).group(1))
    assert fo > fn
```

- [ ] Run them, expect FAIL. Commands:
  - `python -m pytest tests/integration/test_topology_js.py::test_topology_css_has_glow_and_reduced_motion -q` → fails: `missing .topo-node.glow`.
  - `python -m pytest tests/integration/test_topology_node.py::test_render_node_markup_carries_glow_style -q` → fails: `TypeError: T.nodeGlowStyle is not a function`.

- [ ] Minimal implementation, part 1 — add `nodeGlowStyle` near `healthWeight` in `topology.js` (after the `healthWeight` function):

```javascript
function nodeGlowStyle(n) {
  // Inline style string for a node <g>: exposes the severity-driven glow
  // strength as the CSS var --glow (0..1), consumed by .topo-node.glow.
  const w = healthWeight(n);
  return `--glow:${w.toFixed(3)}`;
}
```

- [ ] Minimal implementation, part 2 — use it in the node paint loop. In `topology.js`, the node `<g>` is built at lines 372-376. Change the opening `<g …>` so it (a) always carries the `glow` class, (b) sizes the circle by `healthWeight`, and (c) sets the `--glow` style. Replace lines 363 and 372-374:

  Replace line 363:
```javascript
    const r = nodeRadius(n);
```
  with:
```javascript
    const r = nodeRadius(n) + Math.round(healthWeight(n) * 10);
```

  Replace lines 372-374:
```javascript
    return `<g class="topo-node${pulse}" data-node="${_esc(n.id)}" transform="translate(${p.x},${p.y})">` +
           `<circle r="${r}" fill="#0d1b2a" stroke="${col}" stroke-width="3"/>` +
           `<text class="glyph" text-anchor="middle" dy="6" font-size="${Math.max(12, r - 6)}">${g}</text>` +
```
  with:
```javascript
    return `<g class="topo-node glow${pulse}" data-node="${_esc(n.id)}" style="${nodeGlowStyle(n)}" transform="translate(${p.x},${p.y})">` +
           `<circle r="${r}" fill="#0d1b2a" stroke="${col}" stroke-width="3"/>` +
           `<text class="glyph" text-anchor="middle" dy="6" font-size="${Math.max(12, r - 6)}">${g}</text>` +
```

- [ ] Extend the export. Add `nodeGlowStyle` to the `module.exports` list in `topology.js`:

```javascript
    fmtRate, nodeRadius, layoutGraph, visibleGraph, edgePath, healthWeight, nodeGlowStyle,
```

- [ ] Minimal implementation, part 3 — add the glow theme to CSS. In `RUCKUS/ruckus_dashboard/static/styles.css`, insert after line 204 (`.topo-node.collapsed > circle{stroke-dasharray:6 4}`):

```css

/* ── SP4 health-glow: severity-driven node glow (drop-shadow strength via --glow) ── */
.topo-node.glow > circle{
  filter:drop-shadow(0 0 calc(2px + var(--glow,0) * 22px) rgba(231,76,60,calc(var(--glow,0) * .9)));
}
/* Calm field: near-zero glow = no shadow, so healthy nodes recede. */
.topo-node.glow{transition:filter .4s ease}
@media (prefers-reduced-motion: reduce){
  .topo-node.pulse > circle{animation:none;stroke-opacity:1}
}
```

- [ ] Run tests, expect PASS. Commands:
  - `python -m pytest tests/integration/test_topology_js.py::test_topology_css_has_glow_and_reduced_motion tests/integration/test_topology_node.py::test_render_node_markup_carries_glow_style -q`
  - `python -m pytest tests/integration/test_topology_js.py -q` (existing CSS pulse/badge tests still pass)

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/static/topology.js RUCKUS/ruckus_dashboard/static/styles.css tests/integration/test_topology_js.py tests/integration/test_topology_node.py
git commit -m "feat(topology): severity-driven health glow, reduced-motion safe"
```

---

### Task 5 — Status ribbon update from node counts

Add a persistent status ribbon summarizing live counts (online / flagged / offline / alarms), recomputed client-side from `topoState.nodes` on every render (spec §5.2 step 4; scaled-up `summary()`). Add the pure counting function now; the ribbon DOM element is added in Task 6 and wired here.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/topology.js` (add `ribbonCounts` + `updateStatusRibbon`; call inside `renderTopology` after line 321; extend export)
- Test: `tests/integration/test_topology_node.py` (append)

Steps:

- [ ] Add the failing test. Append to `tests/integration/test_topology_node.py`:

```python
def test_ribbon_counts_tallies_status_and_alarms():
    got = _run(
        "const nodes=["
        "{id:'a',status:'online',meta:{}},"
        "{id:'b',status:'offline',meta:{}},"
        "{id:'c',status:'flagged',meta:{alarm_count:2}},"
        "{id:'d',status:'online',meta:{alarm_count:1}}];"
        "console.log(JSON.stringify(T.ribbonCounts(nodes)));"
    )
    assert got == {"online": 2, "flagged": 1, "offline": 1, "alarms": 3, "total": 4}
```

- [ ] Run it, expect FAIL. Command: `python -m pytest tests/integration/test_topology_node.py -k ribbon_counts -q`. Expected failure: `TypeError: T.ribbonCounts is not a function`.

- [ ] Minimal implementation. In `topology.js`, add after `nodeGlowStyle`:

```javascript
function ribbonCounts(nodes) {
  // Live fleet tally for the status ribbon. Alarms summed across all nodes.
  const c = { online: 0, flagged: 0, offline: 0, alarms: 0, total: nodes.length };
  nodes.forEach(n => {
    if (n.status === "online") c.online += 1;
    else if (n.status === "flagged") c.flagged += 1;
    else if (n.status === "offline") c.offline += 1;
    c.alarms += (n.meta && Number(n.meta.alarm_count)) || 0;
  });
  return c;
}

function updateStatusRibbon(root, nodes) {
  const el = root.querySelector("[data-topo-ribbon]");
  if (!el) return;
  const c = ribbonCounts(nodes);
  el.innerHTML =
    `<span class="rib-item rib-online"><b>${c.online}</b> online</span>` +
    `<span class="rib-item rib-flagged"><b>${c.flagged}</b> flagged</span>` +
    `<span class="rib-item rib-offline"><b>${c.offline}</b> offline</span>` +
    `<span class="rib-item rib-alarms"><b>${c.alarms}</b> alarms</span>` +
    `<span class="rib-item rib-total"><b>${c.total}</b> nodes</span>`;
}
```

- [ ] Wire it into `renderTopology`. In `topology.js`, immediately after line 321 (`topoState.legend = data.legend; topoState.root = root;`) add:

```javascript
  updateStatusRibbon(root, nodes);
```

- [ ] Extend the export. Add `ribbonCounts` to the `module.exports` list:

```javascript
    fmtRate, nodeRadius, layoutGraph, visibleGraph, edgePath, healthWeight, nodeGlowStyle, ribbonCounts,
```

- [ ] Run tests, expect PASS. Command: `python -m pytest tests/integration/test_topology_node.py -k ribbon_counts -q`. Expected: 1 passed.

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/static/topology.js tests/integration/test_topology_node.py
git commit -m "feat(topology): status-ribbon live counts from node statuses"
```

---

### Task 6 — Status ribbon + toolbar markup and styles

Add the status-ribbon element to `topology.html` (so Task 5's `updateStatusRibbon` has a target) and a `Problems only` toggle button (wired in Task 7). Style the ribbon for wall readability.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/templates/topology.html` (toolbar lines 8-19; canvas line 21)
- Modify: `RUCKUS/ruckus_dashboard/static/styles.css` (after the glow block from Task 4)
- Test: `tests/integration/test_topology_js.py` (extend `test_topology_template_has_v2_hooks` is fragile — add a new test instead)

Steps:

- [ ] Add the failing test. Append to `tests/integration/test_topology_js.py`:

```python
def test_topology_template_has_ribbon_and_problems_toggle():
    html = pathlib.Path("RUCKUS/ruckus_dashboard/templates/topology.html").read_text(encoding="utf-8")
    for hook in ["data-topo-ribbon", "data-topo-problems"]:
        assert hook in html, f"missing {hook}"


def test_topology_css_has_ribbon():
    css = pathlib.Path("RUCKUS/ruckus_dashboard/static/styles.css").read_text(encoding="utf-8")
    for rule in [".topo-ribbon", ".rib-offline"]:
        assert rule in css, f"missing {rule}"
```

- [ ] Run them, expect FAIL. Command: `python -m pytest tests/integration/test_topology_js.py -k "ribbon or problems_toggle" -q`. Expected: fails with `missing data-topo-ribbon` then `missing .topo-ribbon`.

- [ ] Minimal implementation, part 1 — add the `Problems only` button to the toolbar. In `RUCKUS/ruckus_dashboard/templates/topology.html`, insert after line 12 (the `data-topo-arrange` button):

```html
      <button data-topo-problems title="Show only problems" aria-pressed="false">⚠ Problems</button>
```

- [ ] Minimal implementation, part 2 — add the status ribbon between the toolbar and canvas. In `topology.html`, insert a new line after line 20 (`</div>` closing `.topo-toolbar`) and before line 21 (`<div class="topo-canvas" …>`):

```html
  <div class="topo-ribbon" data-topo-ribbon></div>
```

- [ ] Minimal implementation, part 3 — style the ribbon. In `RUCKUS/ruckus_dashboard/static/styles.css`, append after the SP4 glow block added in Task 4:

```css

/* ── SP4 status ribbon: glanceable fleet counts above the canvas ── */
.topo-ribbon{display:flex;gap:1.25rem;align-items:center;padding:.4rem .6rem;margin-bottom:.4rem;
  background:#0d1b2a;border:1px solid #1b263b;border-radius:8px;font-size:.95rem;color:#c7d3e0}
.topo-ribbon .rib-item b{font-size:1.35rem;margin-right:.3rem}
.topo-ribbon .rib-online b{color:#2ecc71}
.topo-ribbon .rib-flagged b{color:#f1c40f}
.topo-ribbon .rib-offline b{color:#e74c3c}
.topo-ribbon .rib-alarms b{color:#ff7b54}
body.dso-mode .topo-ribbon{font-size:1.3rem}
body.dso-mode .topo-ribbon .rib-item b{font-size:2rem}
.topo-controls button[aria-pressed="true"]{background:#1f3a5f;border-color:#4cc9f0;color:#fff}
```

- [ ] Run tests, expect PASS. Command: `python -m pytest tests/integration/test_topology_js.py -k "ribbon or problems_toggle" -q`. Expected: 2 passed.

- [ ] Verify the existing template-hooks test still passes (it asserts the original `data-topo-*` hooks, which are untouched). Command: `python -m pytest tests/integration/test_topology_js.py::test_topology_template_has_v2_hooks -q`.

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/templates/topology.html RUCKUS/ruckus_dashboard/static/styles.css tests/integration/test_topology_js.py
git commit -m "feat(topology): status-ribbon + problems-only toolbar markup"
```

---

### Task 7 — `filterProblemsOnly` + problems-only toggle wiring

Implement the green-subtree hiding pure function and wire the `Problems only` button. The function follows the `visibleGraph` pattern (`topology.js:171-179`): keep any node whose status is not `online`/`unknown`, keep ancestors of kept nodes (so a problem AP keeps its zone and the controller visible), and keep their edges; drop fully-green subtrees. The toggle re-renders from state (spec §5.2 step 4 reuses the filter pattern).

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/topology.js` (add `filterProblemsOnly`; add `topoState.problemsOnly` flag at line 7-20; apply in `renderTopology` after `visibleGraph` at line 326; wire button in `wireToolbar` after line 609; extend export)
- Test: `tests/integration/test_topology_node.py` (append), `tests/integration/test_topology_js.py` (append symbol)

Steps:

- [ ] Add the failing behavioral test. Append to `tests/integration/test_topology_node.py`:

```python
def test_filter_problems_only_keeps_problem_paths_drops_green():
    got = _run(
        "const nodes=["
        "{id:'controller',type:'controller',status:'online',meta:{}},"
        "{id:'zBad',type:'zone',status:'flagged',meta:{}},"
        "{id:'apBad',type:'ap',status:'offline',meta:{}},"
        "{id:'zGood',type:'zone',status:'online',meta:{}},"
        "{id:'apGood',type:'ap',status:'online',meta:{}}];"
        "const edges=["
        "{source:'controller',target:'zBad',status:'flagged'},"
        "{source:'zBad',target:'apBad',status:'offline'},"
        "{source:'controller',target:'zGood',status:'online'},"
        "{source:'zGood',target:'apGood',status:'online'}];"
        "const r=T.filterProblemsOnly(nodes,edges);"
        "console.log(JSON.stringify({"
        "ids:r.nodes.map(n=>n.id).sort(),"
        "edges:r.edges.map(e=>e.source+'>'+e.target).sort()}));"
    )
    assert got["ids"] == ["apBad", "controller", "zBad"]
    assert got["edges"] == ["controller>zBad", "zBad>apBad"]


def test_filter_problems_only_empty_when_all_green():
    got = _run(
        "const nodes=[{id:'controller',type:'controller',status:'online',meta:{}},"
        "{id:'z',type:'zone',status:'online',meta:{}}];"
        "const edges=[{source:'controller',target:'z',status:'online'}];"
        "const r=T.filterProblemsOnly(nodes,edges);"
        "console.log(JSON.stringify(r.nodes.map(n=>n.id)));"
    )
    assert got == []
```

- [ ] Run it, expect FAIL. Command: `python -m pytest tests/integration/test_topology_node.py -k filter_problems -q`. Expected failure: `TypeError: T.filterProblemsOnly is not a function`.

- [ ] Minimal implementation, part 1 — the pure function. In `topology.js`, add after `visibleGraph` (after line 179):

```javascript
function filterProblemsOnly(nodes, edges) {
  // Keep only nodes on a path to a problem (status not online/unknown), i.e.
  // every problem node plus all of its ancestors; drop fully-green subtrees
  // and any edge whose endpoints are not both kept.
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  const parentOf = {};
  edges.forEach(e => { parentOf[e.target] = e.source; });
  const keep = new Set();
  const isProblem = n => n && n.status !== "online" && n.status !== "unknown";
  nodes.forEach(n => {
    if (!isProblem(n)) return;
    let cur = n.id;
    while (cur && !keep.has(cur)) { keep.add(cur); cur = parentOf[cur]; }
  });
  return {
    nodes: nodes.filter(n => keep.has(n.id)),
    edges: edges.filter(e => keep.has(e.source) && keep.has(e.target)),
  };
}
```

- [ ] Minimal implementation, part 2 — add the state flag. In `topology.js`, in the `topoState` object (lines 7-20), add a field after `legend: null, root: null,` (line 18):

```javascript
  problemsOnly: false,    // "Problems only" filter active
  view: "graph",          // active view: "graph" (health wall) | "flow"
```

- [ ] Minimal implementation, part 3 — apply in render. In `topology.js`, replace line 326:

```javascript
  const vis = visibleGraph(nodes, edges, topoState.collapsed);
```
  with:
```javascript
  let vis = visibleGraph(nodes, edges, topoState.collapsed);
  if (topoState.problemsOnly) vis = filterProblemsOnly(vis.nodes, vis.edges);
  if (!vis.nodes.length) { canvas.innerHTML = `<p class="empty">No problems — all healthy.</p>`; updateStatusRibbon(root, nodes); return; }
```

- [ ] Minimal implementation, part 4 — wire the button. In `topology.js`, inside `wireToolbar`, add after line 609 (end of the `arrange` handler block, before the `exportBtn` block):

```javascript
  const problems = root.querySelector("[data-topo-problems]");
  if (problems) problems.addEventListener("click", () => {
    topoState.problemsOnly = !topoState.problemsOnly;
    problems.setAttribute("aria-pressed", String(topoState.problemsOnly));
    rerenderFromState();
  });
```

- [ ] Extend the export. Add `filterProblemsOnly` to the `module.exports` list:

```javascript
    fmtRate, nodeRadius, layoutGraph, visibleGraph, edgePath, healthWeight, nodeGlowStyle, ribbonCounts, filterProblemsOnly,
```

- [ ] Add the symbol-presence test. Append to `tests/integration/test_topology_js.py`:

```python
def test_topology_js_has_problems_filter():
    js = pathlib.Path("RUCKUS/ruckus_dashboard/static/topology.js").read_text(encoding="utf-8")
    for sym in ["filterProblemsOnly", "problemsOnly", "data-topo-problems"]:
        assert sym in js, f"missing {sym}"
```

- [ ] Run tests, expect PASS. Command: `python -m pytest tests/integration/test_topology_node.py -k filter_problems tests/integration/test_topology_js.py::test_topology_js_has_problems_filter -q`. Expected: 3 passed.

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/static/topology.js tests/integration/test_topology_node.py tests/integration/test_topology_js.py
git commit -m "feat(topology): problems-only filter hides healthy subtrees"
```

---

## Phase 2 — Concept D: Layered Traffic-Flow View

### Task 8 — `layoutLayered(nodes, edges)` deterministic column layout

The flow view places nodes in left-to-right columns by tier — column 0 controller, column 1 zones/groups, column 2 leaves (switch/ap/more) — at deterministic, finite coordinates with even vertical spacing within each column (spec §5.2 step 5, §5.3). Same input must yield identical output (spec §5.5). Pure function, Node-tested.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/topology.js` (add `layoutLayered` near `layoutGraph`, after line 133; extend export)
- Test: `tests/integration/test_topology_node.py` (append)

Steps:

- [ ] Add the failing test. Append to `tests/integration/test_topology_node.py`:

```python
def test_layout_layered_columns_finite_and_deterministic():
    snippet = (
        "const nodes=["
        "{id:'controller',type:'controller'},"
        "{id:'z1',type:'zone'},{id:'g1',type:'group'},"
        "{id:'s1',type:'switch'},{id:'a1',type:'ap'},{id:'a2',type:'ap'}];"
        "const edges=["
        "{source:'controller',target:'z1'},{source:'controller',target:'g1'},"
        "{source:'g1',target:'s1'},{source:'z1',target:'a1'},{source:'z1',target:'a2'}];"
        "const p1=T.layoutLayered(nodes,edges);"
        "const p2=T.layoutLayered(nodes,edges);"
        "const xs=Object.values(p1).map(p=>p.x);"
        "const allFinite=Object.values(p1).every(p=>isFinite(p.x)&&isFinite(p.y));"
        "console.log(JSON.stringify({"
        "deterministic:JSON.stringify(p1)===JSON.stringify(p2),"
        "allFinite,"
        "ctrlX:p1.controller.x, z1X:p1.z1.x, s1X:p1.s1.x,"
        "colsAscend:(p1.controller.x<p1.z1.x)&&(p1.z1.x<p1.s1.x)}));"
    )
    got = _run(snippet)
    assert got["deterministic"] is True
    assert got["allFinite"] is True
    assert got["colsAscend"] is True


def test_layout_layered_separates_siblings_vertically():
    got = _run(
        "const nodes=[{id:'controller',type:'controller'},"
        "{id:'z1',type:'zone'},{id:'a1',type:'ap'},{id:'a2',type:'ap'}];"
        "const edges=[{source:'controller',target:'z1'},"
        "{source:'z1',target:'a1'},{source:'z1',target:'a2'}];"
        "const p=T.layoutLayered(nodes,edges);"
        "console.log(JSON.stringify(p.a1.y!==p.a2.y));"
    )
    assert got is True
```

- [ ] Run it, expect FAIL. Command: `python -m pytest tests/integration/test_topology_node.py -k layout_layered -q`. Expected failure: `TypeError: T.layoutLayered is not a function`.

- [ ] Minimal implementation. In `topology.js`, add after `layoutGraph` (after line 133):

```javascript
const FLOW_COL_X = { 0: 0, 1: 520, 2: 1040 };
const FLOW_ROW_GAP = 84;

function flowColumn(type) {
  if (type === "controller") return 0;
  if (type === "zone" || type === "group" || type === "stack") return 1;
  return 2; // switch | ap | more
}

function layoutLayered(nodes, edges) {
  // Deterministic left→right layered DAG: column by tier, evenly spaced rows
  // within a column (centred vertically). Stable ordering = input order, so
  // identical input yields identical output. All coordinates finite.
  void edges; // edges drive ribbons in renderFlow, not placement
  const cols = { 0: [], 1: [], 2: [] };
  nodes.forEach(n => { cols[flowColumn(n.type)].push(n); });
  const pos = {};
  Object.keys(cols).forEach(k => {
    const list = cols[k];
    const x = FLOW_COL_X[k];
    const h = (list.length - 1) * FLOW_ROW_GAP;
    list.forEach((n, i) => { pos[n.id] = { x, y: i * FLOW_ROW_GAP - h / 2 }; });
  });
  return pos;
}
```

- [ ] Extend the export. Add `layoutLayered` to the `module.exports` list:

```javascript
    fmtRate, nodeRadius, layoutGraph, visibleGraph, edgePath, healthWeight, nodeGlowStyle, ribbonCounts, filterProblemsOnly, layoutLayered,
```

- [ ] Run tests, expect PASS. Command: `python -m pytest tests/integration/test_topology_node.py -k layout_layered -q`. Expected: 2 passed.

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/static/topology.js tests/integration/test_topology_node.py
git commit -m "feat(topology): deterministic layered column layout for flow view"
```

---

### Task 9 — `flowWidth(edge, rates)` ribbon-thickness scalar + flow CSS

Ribbon thickness encodes throughput (spec Concept D). Add a pure `flowWidth(edge, rates) -> number` that maps a switch edge's live rate (`rates[edge.target]`, bps) to a finite pixel width on a log-ish scale, falling back to a thin uniform width when there is no rate (the "measuring…" case, spec §5.4: never NaN, guard like `fmtRate`). Add flow-ribbon/column CSS.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/topology.js` (add `flowWidth` near `edgeWidth`, after line 243; extend export)
- Modify: `RUCKUS/ruckus_dashboard/static/styles.css` (append after ribbon block)
- Test: `tests/integration/test_topology_node.py` (append), `tests/integration/test_topology_js.py` (append CSS symbol)

Steps:

- [ ] Add the failing tests. Append to `tests/integration/test_topology_node.py`:

```python
def test_flow_width_monotonic_and_finite():
    got = _run(
        "const e={source:'g1',target:'s1',status:'online'};"
        "const lo=T.flowWidth(e,{s1:1e6});"      # 1 Mbps
        "const hi=T.flowWidth(e,{s1:1e9});"      # 1 Gbps
        "const none=T.flowWidth(e,{});"          # no rate
        "console.log(JSON.stringify({lo,hi,none,"
        "finite:[lo,hi,none].every(isFinite),mono:hi>lo,floor:none>0}));"
    )
    assert got["finite"] is True
    assert got["mono"] is True
    assert got["floor"] is True


def test_flow_width_never_nan_on_garbage_rate():
    got = _run(
        "const e={source:'g1',target:'s1'};"
        "console.log(JSON.stringify(isFinite(T.flowWidth(e,{s1:NaN}))));"
    )
    assert got is True
```

  And append to `tests/integration/test_topology_js.py`:

```python
def test_topology_css_has_flow_styles():
    css = pathlib.Path("RUCKUS/ruckus_dashboard/static/styles.css").read_text(encoding="utf-8")
    for rule in [".topo-flow-ribbon", ".topo-flow-col"]:
        assert rule in css, f"missing {rule}"
```

- [ ] Run them, expect FAIL. Commands:
  - `python -m pytest tests/integration/test_topology_node.py -k flow_width -q` → `TypeError: T.flowWidth is not a function`.
  - `python -m pytest tests/integration/test_topology_js.py::test_topology_css_has_flow_styles -q` → `missing .topo-flow-ribbon`.

- [ ] Minimal implementation, part 1 — the pure function. In `topology.js`, add after `edgeWidth` (after line 243):

```javascript
const FLOW_MIN_W = 2;
const FLOW_MAX_W = 28;

function flowWidth(edge, rates) {
  // Map a link's live rate (bps) to a finite ribbon width. No/blank rate →
  // thin floor (the "measuring…" state). Log scale so Kbps..Gbps all read.
  const bps = Number((rates || {})[edge.target]);
  if (!isFinite(bps) || bps <= 0) return FLOW_MIN_W;
  const w = FLOW_MIN_W + Math.log10(1 + bps) * 2.6;
  return Math.max(FLOW_MIN_W, Math.min(FLOW_MAX_W, w));
}
```

- [ ] Extend the export. Add `flowWidth` to the `module.exports` list:

```javascript
    fmtRate, nodeRadius, layoutGraph, visibleGraph, edgePath, healthWeight, nodeGlowStyle, ribbonCounts, filterProblemsOnly, layoutLayered, flowWidth,
```

- [ ] Minimal implementation, part 2 — flow CSS. In `RUCKUS/ruckus_dashboard/static/styles.css`, append after the ribbon block from Task 6:

```css

/* ── SP4 traffic-flow (Sankey-style) view ── */
.topo-flow-ribbon{fill:none;stroke-linecap:round;mix-blend-mode:screen}
.topo-flow-col{fill:#c7d3e0;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;opacity:.6}
.topo-flow-bar > rect{rx:4}
```

- [ ] Run tests, expect PASS. Commands:
  - `python -m pytest tests/integration/test_topology_node.py -k flow_width -q` → 2 passed.
  - `python -m pytest tests/integration/test_topology_js.py::test_topology_css_has_flow_styles -q` → passed.

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/static/topology.js RUCKUS/ruckus_dashboard/static/styles.css tests/integration/test_topology_node.py tests/integration/test_topology_js.py
git commit -m "feat(topology): flow ribbon width scalar + flow view styles"
```

---

### Task 10 — `renderFlow(root, data)` layered Sankey paint

Paint the flow view: place nodes with `layoutLayered`, draw each edge as a Bézier ribbon (reuse `edgePath`, `topology.js:229-235`) with `flowWidth` stroke and status color, draw node bars, and render column headers. Per spec §5.4 it reuses the empty-graph guard and never emits non-finite widths. `renderFlow` returns the SVG string so it is Node-testable without a DOM; the caller (Task 12) injects it into the canvas.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/topology.js` (add `renderFlow` after `renderTopology`, after line 384; extend export)
- Test: `tests/integration/test_topology_node.py` (append)

Steps:

- [ ] Add the failing test. Append to `tests/integration/test_topology_node.py`:

```python
def test_render_flow_emits_svg_with_finite_ribbon_widths():
    snippet = (
        "const data={nodes:["
        "{id:'controller',type:'controller',status:'online',label:'Ctrl',meta:{}},"
        "{id:'g1',type:'group',status:'online',label:'Core',meta:{}},"
        "{id:'s1',type:'switch',status:'online',label:'SW-1',meta:{}}],"
        "edges:["
        "{source:'controller',target:'g1',status:'online',label:''},"
        "{source:'g1',target:'s1',status:'online',label:'2 MB'}]};"
        "const svg=T.renderFlow(data,{s1:5e6});"
        "const widths=[...svg.matchAll(/stroke-width=\"([0-9.]+)\"/g)].map(m=>parseFloat(m[1]));"
        "console.log(JSON.stringify({"
        "isSvg:svg.indexOf('<svg')===0,"
        "hasRibbon:svg.indexOf('topo-flow-ribbon')>=0,"
        "allFinite:widths.every(isFinite)&&widths.length>0,"
        "escaped:svg.indexOf('Ctrl')>=0}));"
    )
    got = _run(snippet)
    assert got["isSvg"] is True
    assert got["hasRibbon"] is True
    assert got["allFinite"] is True
    assert got["escaped"] is True


def test_render_flow_escapes_node_labels():
    got = _run(
        "const data={nodes:[{id:'x',type:'switch',status:'online',"
        "label:'<script>',meta:{}}],edges:[]};"
        "const svg=T.renderFlow(data,{});"
        "console.log(JSON.stringify({"
        "noRaw:svg.indexOf('<script>')<0, hasEsc:svg.indexOf('&lt;script&gt;')>=0}));"
    )
    assert got["noRaw"] is True
    assert got["hasEsc"] is True
```

- [ ] Run it, expect FAIL. Command: `python -m pytest tests/integration/test_topology_node.py -k render_flow -q`. Expected failure: `TypeError: T.renderFlow is not a function`.

- [ ] Minimal implementation. In `topology.js`, add after `renderTopology` (after line 384):

```javascript
function renderFlow(data, rates) {
  // Concept D: deterministic left→right layered ribbon diagram. Returns an SVG
  // string (DOM-free for tests). Band thickness = live rate (flowWidth);
  // colour = edge status; labels HTML-escaped. Reuses the edgePath Bézier.
  const nodes = (data && data.nodes) || [];
  const edges = (data && data.edges) || [];
  rates = rates || {};
  if (!nodes.length) return `<svg class="topo-svg"></svg>`;
  const pos = layoutLayered(nodes, edges);
  const xs = nodes.map(n => pos[n.id].x), ys = nodes.map(n => pos[n.id].y);
  const minX = Math.min(...xs) - 120, minY = Math.min(...ys) - 120;
  const w = (Math.max(...xs) - minX) + 240, h = (Math.max(...ys) - minY) + 240;

  const ribbons = edges.map(e => {
    const a = pos[e.source], b = pos[e.target];
    if (!a || !b) return "";
    const col = TOPO_COLORS[e.status] || TOPO_COLORS.unknown;
    const sw = flowWidth(e, rates);
    return `<path class="topo-flow-ribbon" d="${edgePath(a, b)}" ` +
           `stroke="${col}" stroke-width="${sw}" stroke-opacity=".55"/>`;
  }).join("");

  const bars = nodes.map(n => {
    const p = pos[n.id];
    const col = TOPO_COLORS[n.status] || TOPO_COLORS.unknown;
    const bw = 150, bh = 30;
    return `<g class="topo-flow-bar topo-node" data-node="${_esc(n.id)}" ` +
           `transform="translate(${p.x - bw / 2},${p.y - bh / 2})">` +
           `<rect width="${bw}" height="${bh}" rx="4" fill="#0d1b2a" stroke="${col}" stroke-width="2"/>` +
           `<text class="topo-label" x="${bw / 2}" y="${bh / 2 + 4}" text-anchor="middle">${_esc(n.label || n.id)}</text></g>`;
  }).join("");

  const headers = [["controller", 0], ["zones / groups", 520], ["switches / APs", 1040]]
    .map(([t, x]) => `<text class="topo-flow-col" x="${x}" y="${minY + 28}" text-anchor="middle">${_esc(t)}</text>`)
    .join("");

  return `<svg class="topo-svg" viewBox="${minX} ${minY} ${w} ${h}" ` +
         `preserveAspectRatio="xMidYMid meet"><g data-topo-scene>` +
         `${ribbons}${bars}${headers}</g></svg>`;
}
```

- [ ] Extend the export. Add `renderFlow` to the `module.exports` list:

```javascript
    fmtRate, nodeRadius, layoutGraph, visibleGraph, edgePath, healthWeight, nodeGlowStyle, ribbonCounts, filterProblemsOnly, layoutLayered, flowWidth, renderFlow,
```

- [ ] Run tests, expect PASS. Command: `python -m pytest tests/integration/test_topology_node.py -k render_flow -q`. Expected: 2 passed.

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/static/topology.js tests/integration/test_topology_node.py
git commit -m "feat(topology): renderFlow layered Sankey paint (zero-dep SVG)"
```

---

### Task 11 — View-toggle markup + styles (`graph` | `flow`)

Add a `[data-topo-view]` graph/flow toggle to the toolbar, mirroring the generic module view-toggle pattern (`module.html:21-22`) and reusing the existing `.view-toggle` CSS (`styles.css:252-253`).

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/templates/topology.html` (toolbar, after the `Problems` button)
- Modify: `RUCKUS/ruckus_dashboard/static/styles.css` (small adjustment only if needed — reuse `.view-toggle`)
- Test: `tests/integration/test_topology_js.py` (append)

Steps:

- [ ] Add the failing test. Append to `tests/integration/test_topology_js.py`:

```python
def test_topology_template_has_view_toggle():
    html = pathlib.Path("RUCKUS/ruckus_dashboard/templates/topology.html").read_text(encoding="utf-8")
    assert "data-topo-view" in html
    assert 'data-view="graph"' in html
    assert 'data-view="flow"' in html
```

- [ ] Run it, expect FAIL. Command: `python -m pytest tests/integration/test_topology_js.py::test_topology_template_has_view_toggle -q`. Expected: `assert "data-topo-view" in html` fails.

- [ ] Minimal implementation. In `RUCKUS/ruckus_dashboard/templates/topology.html`, insert into `.topo-controls` immediately after the `data-topo-problems` button added in Task 6:

```html
      <span class="view-toggle" data-topo-view>
        <button data-view="graph" class="active" title="Health-glow wall">Graph</button>
        <button data-view="flow" title="Traffic flow">Flow</button>
      </span>
```

- [ ] Run tests, expect PASS. Command: `python -m pytest tests/integration/test_topology_js.py::test_topology_template_has_view_toggle -q`. Expected: passed. (The `.view-toggle` CSS at `styles.css:252-253` already styles these buttons; no CSS change required.)

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/templates/topology.html tests/integration/test_topology_js.py
git commit -m "feat(topology): graph|flow view toggle markup"
```

---

### Task 12 — `setView` dispatch in `renderTopology` + advertise `supports_views`

Wire the view toggle: `setView(root, view)` stores `topoState.view` and re-renders; `renderTopology` dispatches to `renderFlow` when `view === "flow"` (injecting its SVG string and re-wiring tooltip/zoom), else runs the existing health-glow `graph` path. Advertise `supports_views=("graph","flow")` on the `ModuleSpec`. The flow view writes no layout pins, so `routes/topology_layout.py` is untouched (spec §5.4).

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/topology.js` (early-return flow branch in `renderTopology` after line 327; add `setView`; wire `[data-topo-view]` buttons in `wireToolbar`; extend export)
- Modify: `RUCKUS/ruckus_dashboard/modules/topology.py` (line 251)
- Test: `tests/integration/test_topology_js.py` (append symbol), `tests/unit/modules/test_topology.py` (append)

Steps:

- [ ] Add the failing tests. Append to `tests/integration/test_topology_js.py`:

```python
def test_topology_js_has_set_view_and_flow_dispatch():
    js = pathlib.Path("RUCKUS/ruckus_dashboard/static/topology.js").read_text(encoding="utf-8")
    for sym in ["setView", "renderFlow", 'topoState.view', "data-topo-view"]:
        assert sym in js, f"missing {sym}"
```

  And append to `tests/unit/modules/test_topology.py`:

```python
def test_topology_advertises_graph_and_flow_views():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["topology"].supports_views == ("graph", "flow")
```

- [ ] Run them, expect FAIL. Commands:
  - `python -m pytest tests/integration/test_topology_js.py::test_topology_js_has_set_view_and_flow_dispatch -q` → `missing setView`.
  - `python -m pytest tests/unit/modules/test_topology.py::test_topology_advertises_graph_and_flow_views -q` → `assert ('graph',) == ('graph', 'flow')`.

- [ ] Minimal implementation, part 1 — flow dispatch in `renderTopology`. In `topology.js`, insert immediately after line 327 (`topoState.visEdges = vis.edges;`) — note `updateRates(nodes)` at line 325 already ran, so `topoState.rates` is current:

```javascript
  if (topoState.view === "flow") {
    canvas.innerHTML = renderFlow({ nodes: vis.nodes, edges: vis.edges }, topoState.rates);
    _wireTopo(root, canvas.querySelector("svg"));
    _renderTopoLegend(root, data.legend);
    return;
  }
```

- [ ] Minimal implementation, part 2 — `setView`. In `topology.js`, add after `rerenderFromState` (after line 221):

```javascript
function setView(root, view) {
  topoState.view = view === "flow" ? "flow" : "graph";
  const toggle = root.querySelector("[data-topo-view]");
  if (toggle) toggle.querySelectorAll("button").forEach(b =>
    b.classList.toggle("active", b.getAttribute("data-view") === topoState.view));
  rerenderFromState();
}
```

- [ ] Minimal implementation, part 3 — wire the buttons. In `topology.js`, inside `wireToolbar`, add after the `problems` handler block from Task 7:

```javascript
  const viewToggle = root.querySelector("[data-topo-view]");
  if (viewToggle) viewToggle.querySelectorAll("button").forEach(b =>
    b.addEventListener("click", () => setView(root, b.getAttribute("data-view"))));
```

- [ ] Extend the export. Add `setView` to the `module.exports` list:

```javascript
    fmtRate, nodeRadius, layoutGraph, visibleGraph, edgePath, healthWeight, nodeGlowStyle, ribbonCounts, filterProblemsOnly, layoutLayered, flowWidth, renderFlow, setView,
```

- [ ] Minimal implementation, part 4 — advertise the view. In `RUCKUS/ruckus_dashboard/modules/topology.py`, change line 251 from:

```python
    supports_views=("graph",), warmup=True, merge=merge,
```
  to:
```python
    supports_views=("graph", "flow"), warmup=True, merge=merge,
```

- [ ] Run tests, expect PASS. Commands:
  - `python -m pytest tests/integration/test_topology_js.py::test_topology_js_has_set_view_and_flow_dispatch tests/unit/modules/test_topology.py -q`
  - `python -m pytest tests/integration/test_topology_node.py -q` (all Node tests still green)

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/static/topology.js RUCKUS/ruckus_dashboard/modules/topology.py tests/integration/test_topology_js.py tests/unit/modules/test_topology.py
git commit -m "feat(topology): wire graph|flow view dispatch and advertise views"
```

- [ ] **Phase 1 + 2 full-suite gate.** Run the entire suite + lint to confirm nothing regressed. Commands:
  - `python -m pytest -q`
  - `ruff check RUCKUS/ruckus_dashboard tests`
  Expected: all tests pass (301 prior + the new tests added in Tasks 1–12), ruff clean.

---

## Phase 3 — Optional D-rich: SwitchM Port Throughput

> Build Phase 3 only if richer per-port flow is approved (spec §5.7, Open Question 3). It is purely additive and degrades to Phase 2 behavior when port data is absent.

### Task 13 — `_port_flow(ctx)` best-effort port throughput

Add a best-effort server helper returning `{switchId: bps}` from SwitchM port usage (`clients/switchm.py` exposes `traffic/top/portusage`, per spec §1.1/Concept D), wrapped so any client error yields `{}` (mirrors `_traffic_map`, `topology.py:104-112`). Read `clients/switchm.py` first to confirm the exact `switch_manager_query` endpoint string and response envelope before writing the call.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/modules/topology.py` (add `_port_flow` near `_traffic_map`, after line 112)
- Test: `tests/unit/modules/test_topology.py` (append)

Steps:

- [ ] Read `RUCKUS/ruckus_dashboard/clients/switchm.py` and confirm: (a) `switch_manager_query(connection, path, config)` signature (already imported at `topology.py:13`), (b) that `traffic/top/portusage` returns a `{"list": [...]}` envelope with per-row `key`/`value` like `traffic/top/usage`. Record the exact row keys used below.

- [ ] Add the failing test. Append to `tests/unit/modules/test_topology.py`:

```python
@responses.activate
def test_port_flow_best_effort_and_shape():
    base = "https://sz.example:8443/wsg/api/public"  # noqa: F841
    sw = "https://sz.example:8443/switchm/api"
    responses.add(responses.POST, f"{sw}/v11_0/traffic/top/portusage",
                  json={"list": [{"key": "s1", "value": 4000000}]},
                  status=200, match_querystring=False)
    out = topology_mod._port_flow(_ctx())
    assert out.get("S1") == 4000000 or out.get("s1") == 4000000


def test_port_flow_returns_empty_on_error():
    # No responses registered + connection refused → best-effort empty dict.
    assert topology_mod._port_flow(_ctx()) == {}
```

- [ ] Run it, expect FAIL. Command: `python -m pytest tests/unit/modules/test_topology.py -k port_flow -q`. Expected failure: `AttributeError: module 'ruckus_dashboard.modules.topology' has no attribute '_port_flow'`.

- [ ] Minimal implementation. In `RUCKUS/ruckus_dashboard/modules/topology.py`, add after `_traffic_map` (after line 112) — adjust the row keys/endpoint only if the Task-13 read step found different ones:

```python
def _port_flow(ctx) -> dict:
    """{switchId (UPPER): bytes} from SwitchM port usage. Best-effort → {}."""
    out: dict = {}
    data = _safe(lambda: switch_manager_query(
        ctx.connection, "traffic/top/portusage", ctx.config)) or {}
    for r in (data.get("list") or []):
        if isinstance(r, dict):
            key = r.get("key") or r.get("id")
            if key:
                out[str(key).upper()] = int(r.get("value") or 0)
    return out
```

- [ ] Run tests, expect PASS. Command: `python -m pytest tests/unit/modules/test_topology.py -k port_flow -q`. Expected: 2 passed.

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/modules/topology.py tests/unit/modules/test_topology.py
git commit -m "feat(topology): best-effort SwitchM port-flow helper"
```

---

### Task 14 — Attach optional `flow` key in `fetch()`; client fallback

Attach a `flow` dict to the `fetch()` output (additive; absence ⇒ flow view keeps using `topoState.rates` from `updateRates`). The envelope shape `{nodes, edges, legend, items}` is preserved with `flow` added as an extra key, so all existing `fetch()` tests stay green. Client side, prefer `data.flow[id]` over computed rates in `renderFlow` when present.

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/modules/topology.py` (`fetch`, lines 36-51; `_build_graph` return, line 215)
- Modify: `RUCKUS/ruckus_dashboard/static/topology.js` (`renderFlow` rate lookup; flow dispatch passes `data.flow`)
- Test: `tests/unit/modules/test_topology.py` (append), `tests/integration/test_topology_node.py` (append)

Steps:

- [ ] Add the failing server test. Append to `tests/unit/modules/test_topology.py`:

```python
def test_build_graph_accepts_and_emits_flow_key():
    g = topology_mod._build_graph(CLUSTER, ZONES, APS, SWITCHES, {"s1": 1024},
                                  port_flow={"S1": 4000000})
    assert g["flow"] == {"S1": 4000000}
    # envelope still intact
    assert set(g) >= {"nodes", "edges", "legend", "items", "flow"}


def test_build_graph_flow_defaults_empty():
    g = topology_mod._build_graph(CLUSTER, ZONES, APS, SWITCHES, {})
    assert g["flow"] == {}
```

- [ ] Run it, expect FAIL. Command: `python -m pytest tests/unit/modules/test_topology.py -k flow_key -q`. Expected failure: `TypeError: _build_graph() got an unexpected keyword argument 'port_flow'`.

- [ ] Minimal implementation, part 1 — thread `port_flow` through `_build_graph`. In `RUCKUS/ruckus_dashboard/modules/topology.py`, change the signature at line 115-116 from:

```python
def _build_graph(cluster, zones, aps, switches, traffic_by_mac,
                 alarms_by_name=None, expand=frozenset(), rssi_by_ap=None):
```
  to:
```python
def _build_graph(cluster, zones, aps, switches, traffic_by_mac,
                 alarms_by_name=None, expand=frozenset(), rssi_by_ap=None,
                 port_flow=None):
```

  And change the return at line 215-216 from:
```python
    return {"nodes": nodes, "edges": edges,
            "legend": {"status": STATUS_COLORS}, "items": []}
```
  to:
```python
    return {"nodes": nodes, "edges": edges,
            "legend": {"status": STATUS_COLORS}, "items": [],
            "flow": port_flow or {}}
```

- [ ] Minimal implementation, part 2 — pass it from `fetch()`. In `topology.py` `fetch`, add after line 42 (`traffic_by_mac = _traffic_map(ctx)`):

```python
    port_flow = _port_flow(ctx)
```
  And change the `return _build_graph(...)` call at lines 49-51 to pass `port_flow=port_flow`:
```python
    return _build_graph(cluster, zones, aps, switches, traffic_by_mac,
                        alarms_by_name=alarms_by_name, expand=expand,
                        rssi_by_ap=rssi_by_ap, port_flow=port_flow)
```

- [ ] Update `merge` to keep the `flow` key on the empty-graph fallback. In `topology.py`, change the fallback return in `merge` (line 243) from:
```python
    return {"nodes": [], "edges": [], "legend": {"status": STATUS_COLORS}, "items": []}
```
  to:
```python
    return {"nodes": [], "edges": [], "legend": {"status": STATUS_COLORS}, "items": [], "flow": {}}
```

- [ ] Run server tests, expect PASS. Command: `python -m pytest tests/unit/modules/test_topology.py -q`. Expected: all pass, including the existing `test_topology_fetch_assembles_graph` (which now also exercises `_port_flow`'s best-effort path — it registers no `portusage` mock, so `_port_flow` returns `{}` and the assertions on node types are unaffected).

- [ ] Add the failing client test for the flow-key preference. Append to `tests/integration/test_topology_node.py`:

```python
def test_render_flow_prefers_server_flow_over_rates():
    # When renderFlow receives an explicit flow map, it uses those bps.
    snippet = (
        "const data={nodes:["
        "{id:'g1',type:'group',status:'online',label:'Core',meta:{}},"
        "{id:'s1',type:'switch',status:'online',label:'SW',meta:{}}],"
        "edges:[{source:'g1',target:'s1',status:'online',label:''}]};"
        "const a=T.renderFlow(data,{s1:1e3});"      # thin (rates)
        "const b=T.renderFlow(data,{s1:1e9});"      # fat (server flow)
        "const wa=parseFloat(a.match(/topo-flow-ribbon[^>]*stroke-width=\"([0-9.]+)\"/)[1]);"
        "const wb=parseFloat(b.match(/topo-flow-ribbon[^>]*stroke-width=\"([0-9.]+)\"/)[1]);"
        "console.log(JSON.stringify(wb>wa));"
    )
    assert _run(snippet) is True
```

- [ ] Confirm the client already satisfies it. `renderFlow(data, rates)` already takes a rate map as its second argument (Task 10), and Task 12's dispatch passes `topoState.rates`. Update the dispatch to prefer the server `flow` key when present. In `topology.js`, change the flow dispatch line added in Task 12 from:

```javascript
    canvas.innerHTML = renderFlow({ nodes: vis.nodes, edges: vis.edges }, topoState.rates);
```
  to:
```javascript
    const flowRates = (data.flow && Object.keys(data.flow).length) ? data.flow : topoState.rates;
    canvas.innerHTML = renderFlow({ nodes: vis.nodes, edges: vis.edges }, flowRates);
```

- [ ] Run the client test, expect PASS. Command: `python -m pytest tests/integration/test_topology_node.py -k prefers_server_flow -q`. Expected: passed.

- [ ] Commit. Command:
```
git add RUCKUS/ruckus_dashboard/modules/topology.py RUCKUS/ruckus_dashboard/static/topology.js tests/unit/modules/test_topology.py tests/integration/test_topology_node.py
git commit -m "feat(topology): attach optional server flow key, client prefers it"
```

- [ ] **Final full-suite + lint gate.** Commands:
  - `python -m pytest -q`
  - `ruff check RUCKUS/ruckus_dashboard tests`
  Expected: all green, ruff clean.

---

## Self-Review

### Spec coverage map (spec §5.6 "Concrete files that change" → tasks)

| Spec item (§5.3 interfaces / §5.6 file changes / §5.7 phasing) | Task(s) |
|---|---|
| `static/topology.js`: `renderHealthWall` (evolve `renderTopology`) — severity sizing/glow | 4 (health-glow encoding folded into existing `renderTopology` graph path, per §5.2 step 4 "Health-glow is the default `graph` render with the new theme") |
| `static/topology.js`: `healthWeight(node) -> number` (extends `nodeRadius`) | 3 |
| `static/topology.js`: `filterProblemsOnly(nodes, edges) -> {nodes, edges}` (pattern of `visibleGraph`) | 7 |
| `static/topology.js`: status-ribbon update from node counts | 5 |
| `static/topology.js`: `layoutLayered(nodes, edges) -> positions` | 8 |
| `static/topology.js`: `renderFlow(root, data)` layered Sankey | 9 (`flowWidth`), 10 (`renderFlow`) |
| `static/topology.js`: `setView("graph"\|"flow")` toggle + dispatch in `renderTopology` (§5.2 step 3) | 12 |
| `templates/topology.html`: `[data-topo-view]` graph/flow toggle | 11 |
| `templates/topology.html`: `Problems only` toggle | 6 (markup), 7 (wiring) |
| `templates/topology.html`: status-ribbon element | 6 |
| `static/styles.css`: glow/gradient theme | 4 |
| `static/styles.css`: status-ribbon styles | 6 |
| `static/styles.css`: flow-ribbon/column styles | 9 |
| `modules/topology.py`: `supports_views=("graph","flow")` (§5.3) | 12 (+ Task 1 makes `"flow"` valid in `_base.py`) |
| `modules/topology.py`: `_port_flow(ctx)` + optional `flow` key (§5.3, Phase 3) | 13, 14 |
| `routes/topology_layout.py`: **no change** (§5.6) | — (explicitly untouched) |
| Testing §5.5: Node-run determinism/monotonicity/finiteness + symbol tests | 2 (harness), 3, 5, 7, 8, 9, 10, 14 (Node), 1/12/13/14 (pytest), symbol tests throughout |
| Error handling §5.4: empty-graph guard both views; flow never NaN; "measuring…" floor; idempotent re-render | 7 (problems-empty guard), 9 (`flowWidth` NaN floor), 10 (`renderFlow` empty guard), 12 (idempotent `rerenderFromState`) |
| `_esc` HTML-escaping preserved (§5.4, §5.5 regression) | 10 (`renderFlow` escapes labels — `test_render_flow_escapes_node_labels`); existing graph path unchanged |
| Reduced-motion-safe (approach note) | 4 (`@media (prefers-reduced-motion: reduce)` disables pulse) |
| Phasing 1/2/3 (§5.7) | Tasks 1–7 / 8–12 / 13–14 |

**Deferred/declined per approach note (correctly NOT planned):** Concept B (geo) — deferred (Phase 4, blocked on geo data Open Question 1); Concept C (force-directed) — declined. No tasks for either.

### Placeholder scan
No "TBD", "similar to Task N", "add error handling", or "write tests for the above" appears. Every code step contains complete, runnable code. The only conditional is Phase 3 (Tasks 13–14), explicitly gated as "optional / build only if approved" per spec §5.7 — its code is nonetheless written in full. Task 13's first step requires reading `clients/switchm.py` to confirm the exact `portusage` endpoint string/row keys; the provided implementation mirrors the proven `_traffic_map` shape and the step notes to adjust only if the read finds different keys (grounded, not a placeholder).

### Type / name consistency
- `topoState` new fields `problemsOnly` (bool) and `view` ("graph"|"flow") are declared once in Task 7 and read in Tasks 7/12. `view` default `"graph"`.
- Pure-function signatures are stable across tasks and tests: `healthWeight(n)`, `nodeGlowStyle(n)`, `ribbonCounts(nodes)`, `filterProblemsOnly(nodes, edges)`, `layoutLayered(nodes, edges)`, `flowWidth(edge, rates)`, `renderFlow(data, rates)`, `setView(root, view)`. Note `renderFlow`'s **actual** signature is `(data, rates)` (DOM-free, returns SVG string) — this intentionally differs from the spec's illustrative `renderFlow(root, data)` because the spec (§5.5) also requires `renderFlow` to be unit-tested for finite widths without a DOM; the test files in Tasks 10/14 use `(data, rates)` consistently, and the caller in Task 12 passes `(payloadSubset, flowRates)`. This deviation is documented here for the reviewer.
- The `module.exports` list grows monotonically and is shown in full at each task that extends it, ending with: `fmtRate, nodeRadius, layoutGraph, visibleGraph, edgePath, healthWeight, nodeGlowStyle, ribbonCounts, filterProblemsOnly, layoutLayered, flowWidth, renderFlow, setView`.
- Server: `_build_graph(..., port_flow=None)` and `_port_flow(ctx)` names match between `topology.py` and `test_topology.py`. Output key is `flow` (dict, default `{}`); envelope `{nodes, edges, legend, items, flow}`.
- Colors reuse the existing `TOPO_COLORS`/`STATUS_COLORS` maps (no new color constants that could drift from the server's `STATUS_COLORS`).
- Test-file data-attribute strings (`data-topo-ribbon`, `data-topo-problems`, `data-topo-view`, `data-view="graph"`, `data-view="flow"`) match the template markup exactly.

### Regression safety
- `routes/topology_layout.py` untouched → `test_topology_layout_api.py` (3 tests) unaffected.
- Existing `test_topology_js.py` symbol/CSS/template tests assert strings that remain present (original `data-topo-*` hooks, `@keyframes topo-pulse`, `.topo-badge`, etc. are not removed).
- Existing `test_topology.py` `_build_graph`/`fetch`/`summary`/`merge` tests: Phase 3 adds an optional kwarg with a default and an extra dict key, so positional calls and existing key assertions still hold; `fetch()` now calls `_port_flow` which is best-effort `{}` under the existing mocks.
- `test_base.py::test_module_spec_rejects_invalid_view` still raises (uses `"invalid-view"`, not `"flow"`).
- Node tests `pytest.skip` when `node` is absent → suite stays green on JS-less machines; CI ubuntu/windows runners ship Node, so they execute. Coverage gate (`--cov=ruckus_dashboard`, 75%) is Python-only and unaffected by JS tests.
- ruff lints `tests` too: new pytest files use only stdlib + `responses` + `pytest`; the `# noqa: F841` on the unused `base` local in Task 13's test keeps ruff clean.

---

## Execution Handoff

**Recommended: subagent-driven (superpowers:subagent-driven-development).** Tasks 1–12 are mostly independent client/CSS/template edits with isolated tests; a fresh subagent per task keeps context small. Suggested batching:
- **Phase 1:** Task 1 → Task 2 (harness, blocks all Node tests) → Tasks 3, 4, 5, 6, 7 in order (4 depends on 3; 6 markup precedes 7 wiring; 5 precedes 6's ribbon styling but the pure fn in 5 has no DOM dep).
- **Phase 2:** Task 8 → 9 → 10 → 11 → 12 (12 depends on 10's `renderFlow` and 11's toggle markup). Run the Phase-1+2 full-suite gate at the end of Task 12.
- **Phase 3 (only if approved):** Task 13 → 14 (read `clients/switchm.py` first in Task 13).

Each task is self-contained: failing test → run (see expected failure) → minimal code → run (PASS) → commit. Do not batch commits across tasks.

**Alternative: inline (superpowers:executing-plans)** in this session with review checkpoints after Task 7 (end of Phase 1 — the shippable health-glow wall), after Task 12 (end of Phase 2 — flow view live), and after Task 14 (Phase 3). Run `python -m pytest -q && ruff check RUCKUS/ruckus_dashboard tests` at each checkpoint and require green before proceeding.

**Manual verification (both paths), after Phase 2:** launch the app, open `/m/topology`, confirm (1) healthy nodes are dim and an offline/flagged zone blooms a red halo, (2) the status ribbon shows live counts, (3) `⚠ Problems` hides all-green subtrees, (4) the `Flow` toggle renders left→right ribbons whose thickness tracks switch traffic, (5) toggling `Graph`/`Flow` is instant and idempotent, (6) with OS "reduce motion" on, nodes do not pulse.
