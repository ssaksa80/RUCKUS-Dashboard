# DSO Overview Bar + Missing-Value Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent DSO health bar + overview-as-landing, fix Alarms KPIs, and ship a raw-shape diagnostic so Controller/Traffic/VLAN field mappings can be fixed from evidence.

**Architecture:** Health bar is a shell-level partial populated by `renderHealthBar()` reading the existing `/api/warmup/status` cache + SSE. Overview route reuse for `/m/overview`. Alarms summary derives from list rows. Dump gains a redacted `raw_sample` per module; traffic/vlans surface a `raw_rows` sample.

**Tech Stack:** Flask + Jinja, vanilla JS, pytest + responses.

---

### Task 1: Alarms summary from list rows

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/modules/alarms.py`
- Test: `tests/unit/modules/test_alarms.py`

- [ ] **Step 1: Write failing test** — summary counts by severity from items

```python
def test_alarms_summary_derives_from_items():
    from ruckus_dashboard.modules import alarms as m
    data = {"items": [
        {"severity": "critical", "count": 2},
        {"severity": "major", "count": 1},
        {"severity": "major", "count": 1},
        {"severity": "warning", "count": 3},
    ]}
    s = m.summary(data)
    assert s["critical"] == 2
    assert s["major"] == 2
    assert s["warning"] == 3
    assert s["total"] == 7
```

- [ ] **Step 2: Run, expect FAIL.** `pytest tests/unit/modules/test_alarms.py::test_alarms_summary_derives_from_items -v`

- [ ] **Step 3: Implement** — replace `summary()` to fold over items:

```python
def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    buckets = {"critical": 0, "major": 0, "minor": 0, "warning": 0}
    total = 0
    for it in items:
        sev = str(it.get("severity") or "").lower()
        cnt = int(it.get("count") or 1)
        total += cnt
        if sev in buckets:
            buckets[sev] += cnt
    return {**buckets, "total": total}
```

Drop any `alert/alarmSummary` call feeding the summary (keep the list fetch).

- [ ] **Step 4: Run, expect PASS.** Then full file: `pytest tests/unit/modules/test_alarms.py -v`
- [ ] **Step 5: Commit** `fix(live): derive alarm severity KPIs from list rows`

---

### Task 2: Dump captures redacted raw sample per module

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/dump.py` (`_dump_module`)
- Modify: `RUCKUS/ruckus_dashboard/modules/traffic.py` (fetch returns `raw_rows`)
- Modify: `RUCKUS/ruckus_dashboard/modules/vlans.py` (fetch returns `raw_rows`)
- Test: `tests/unit/test_dump.py` (add case)

- [ ] **Step 1: Write failing test** — dump entry has `raw_sample` with non-item data keys

```python
def test_dump_captures_raw_sample(monkeypatch):
    from ruckus_dashboard import dump as d
    class Spec:
        summary_fn = None; drill_fetcher = None
        def fetcher(self, ctx):
            return {"items": [{"id": "a"}], "raw_rows": [{"weirdKey": 1}]}
    entry = d._dump_module("x", Spec(), object(), {}, _gate())
    assert entry["raw_sample"]["raw_rows"] == [{"weirdKey": 1}]
    assert "items" not in entry["raw_sample"]  # items captured separately
```
(`_gate()` helper builds `CapabilityGate(set())`.)

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement** in `_dump_module`, after computing `summary`, before drill:

```python
    # raw_sample: non-item keys of the fetcher result, redacted + truncated,
    # so live API field shapes are visible without guessing.
    if isinstance(data, dict):
        raw = {k: v for k, v in data.items() if k != "items"}
        entry["raw_sample"] = _truncate(_redact(raw))
```

Add a `_truncate(obj, depth=4, maxlen=40)` helper that caps list lengths to 3 and recursion depth (keeps dump small).

For traffic.py `fetch`, add `"raw_rows": rows[:2]` to the returned dict (raw upstream rows before normalize). Same for vlans.py `fetch`: `"raw_rows": rows[:2]`.

- [ ] **Step 4: Run, expect PASS.** Full suite.
- [ ] **Step 5: Commit** `feat(dump): capture redacted raw_sample per module for field mapping`

---

### Task 3: `/m/overview` renders tile grid

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/routes/pages.py` (`module_page`)
- Test: `tests/integration/test_pages.py` (or existing smoke)

- [ ] **Step 1: Write failing test** — GET `/m/overview` returns tile grid markup, not module table

```python
def test_overview_route_renders_tiles(client_authed):
    r = client_authed.get("/m/overview")
    assert r.status_code == 200
    assert b"tile-grid" in r.data
```

- [ ] **Step 2: Run, expect FAIL** (currently renders module.html table).

- [ ] **Step 3: Implement** — in `module_page`, short-circuit overview:

```python
@bp.get("/m/<slug>")
def module_page(slug: str):
    spec = MODULES.get(slug)
    if spec is None:
        abort(404)
    if slug == "overview":
        return render_template("overview.html",
                               modules=all_modules(),
                               csrf_token=session.get("csrf_token", ""))
    return render_template("module.html", module=spec,
                           modules=all_modules(),
                           csrf_token=session.get("csrf_token", ""))
```

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `fix(ui): /m/overview renders DSO tile grid instead of empty table`

---

### Task 4: Pin DSO Overview at top of nav

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/templates/base.html` (nav block)

- [ ] **Step 1: Implement** — above the grouped `module-nav`, add a pinned overview link and exclude overview from the grouped loop:

```html
    <nav class="module-nav">
      <a href="/" data-slug="overview"
         class="nav-item nav-pinned {% if active_slug == 'overview' %}active{% endif %}">
        <span class="nav-icon">🛰️</span>
        <span class="nav-label">DSO Overview</span>
      </a>
      {% set groups = {} %}
      {% for m in modules if m.slug != 'overview' %}{% set _ = groups.setdefault(m.group, []).append(m) %}{% endfor %}
      ... (existing group loop unchanged) ...
```

- [ ] **Step 2: Verify** — smoke GET `/` and `/m/aps` both contain `nav-pinned`. Manual/quick test.
- [ ] **Step 3: Commit** `feat(ui): pin DSO Overview at top of sidebar`

---

### Task 5: Persistent DSO health bar

**Files:**
- Create: `RUCKUS/ruckus_dashboard/templates/partials/health_bar.html`
- Modify: `RUCKUS/ruckus_dashboard/templates/base.html` (mount after topbar)
- Modify: `RUCKUS/ruckus_dashboard/static/dashboard.js` (`renderHealthBar`, init)
- Modify: `RUCKUS/ruckus_dashboard/static/styles.css` (health-bar styles)
- Test: `tests/integration/test_dashboard_js.py` (symbol presence)

- [ ] **Step 1: Create partial** `health_bar.html`:

```html
<div class="health-bar" data-health-bar hidden>
  <span class="health-tag">DSO</span>
  {% set chips = [("aps","APs"),("clients","Clients"),("alarms","Alarms"),
                  ("rogues","Rogues"),("switches","Switches"),("poe","PoE"),
                  ("vlans","VLANs"),("zones","Zones")] %}
  {% for slug, label in chips %}
  <a class="health-chip" href="/m/{{ slug }}" data-health-chip="{{ slug }}">
    <span class="hc-label">{{ label }}</span>
    <span class="hc-value" data-health-value="{{ slug }}">…</span>
  </a>
  {% endfor %}
</div>
```

- [ ] **Step 2: Mount** in base.html, immediately after `</header>`:

```html
    </header>
    {% include "partials/health_bar.html" %}
```

- [ ] **Step 3: Implement `renderHealthBar()`** in dashboard.js — populate chips from `/api/warmup/status`, refresh via SSE, mark danger when alarms/rogues > 0:

```javascript
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
    if ((slug === "alarms" || slug === "rogues") && Number(n) > 0) chip.classList.add("danger");
    else if (chip) chip.classList.remove("danger");
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
  } catch { /* status load already ran */ }
}
```

Call it in `DOMContentLoaded` (always, since the bar is in the shell):

```javascript
  renderHealthBar();
```

- [ ] **Step 4: CSS** in styles.css:

```css
.health-bar{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;
  padding:.4rem .8rem;background:#0d1b2a;border-bottom:1px solid #1b263b;font-size:.8rem}
.health-tag{font-weight:700;color:#4cc9f0;letter-spacing:.05em}
.health-chip{display:flex;gap:.35rem;align-items:center;padding:.15rem .5rem;
  border:1px solid #1b263b;border-radius:6px;color:#c7d3e0;text-decoration:none}
.health-chip:hover{border-color:#4cc9f0}
.health-chip .hc-label{color:#7c8aa0;text-transform:uppercase;font-size:.65rem}
.health-chip .hc-value{font-weight:700}
.health-chip.danger{border-color:#e63946;color:#ff8088}
.health-chip.danger .hc-value{color:#ff5a5f}
```

- [ ] **Step 5: Test** `node -c dashboard.js`; integration test asserts `renderHealthBar` + `data-health-bar` present:

```python
def test_health_bar_symbols_present():
    js = pathlib.Path("RUCKUS/ruckus_dashboard/static/dashboard.js").read_text()
    assert "renderHealthBar" in js and "applyHealthState" in js
```

- [ ] **Step 6: Run full suite, JS check.**
- [ ] **Step 7: Commit** `feat(ui): persistent DSO health bar across all module pages`

---

### Task 6: Ship + request raw dump for field fixes

- [ ] Push all of the above to main.
- [ ] Ask user to pull + run one `--dump`, paste `modules.controller.raw_sample`, `modules.traffic.raw_sample`, `modules.vlans.raw_sample`.
- [ ] Follow-up tasks (separate commit, evidence-driven): fix `_normalize`/`summary` field keys in `controller.py`, `traffic.py`, `vlans.py` from the raw shapes; update mocks; full suite; push.

---

## Self-Review

- Spec coverage: health bar (T5), overview landing/top (T3,T4), `/m/overview` tiles (T3), alarms (T1), raw-shape diagnostic for controller/traffic/vlans (T2 + T6). All covered.
- Placeholders: none — code shown for each step. T6 field fixes intentionally deferred pending evidence (per spec section C; not guessing).
- Type consistency: `applyHealthState(slug,status,summary)`, `pickSummaryNumber(s)`, `renderHealthBar()` used consistently; `raw_sample` key consistent dump↔test.
