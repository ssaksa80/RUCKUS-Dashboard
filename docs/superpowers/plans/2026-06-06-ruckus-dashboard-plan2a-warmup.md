# Plan 2a — Auto-Discovery + Warmup Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `WarmupScheduler` + SSE progress stream + UI strip so that after login, every applicable module fetcher runs once in the background and pre-warms `app.module_cache`. Modules still stub-only — real fetchers come in Plan 2b/2c/2d.

**Architecture:** Three layers. `infra/parallel_fetch.py` provides `ParallelFetcher` (ThreadPoolExecutor + timeout). `infra/warmup.py` wraps it with module-registry iteration + per-module status tracking. `routes/warmup.py` exposes SSE stream + sync status. `dashboard.js` opens EventSource on Overview load and updates tiles in real time. `routes/connect.py` and `/logout` plumb scheduler lifecycle.

**Tech Stack:** Python `concurrent.futures.ThreadPoolExecutor`, Flask SSE (no Flask-SSE dependency — manual generator), vanilla `EventSource` API, `pytest`.

**Source spec:** `docs/superpowers/specs/2026-06-06-ruckus-dashboard-plan2-design.md`

**Follow-up plans (not in scope):** Plan 2b (wireless modules), Plan 2c (switching modules), Plan 2d (cross-cutting + bootstrap).

---

## File Structure

```
RUCKUS/ruckus_dashboard/
├── infra/
│   ├── parallel_fetch.py        # CREATE — ParallelFetcher wrapper
│   └── warmup.py                # CREATE — WarmupScheduler + WarmupStatus
├── routes/
│   ├── warmup.py                # CREATE — SSE + sync status endpoints
│   └── connect.py               # MODIFY — start/cancel scheduler on login/logout
├── modules/
│   ├── _base.py                 # MODIFY — add `warmup: bool = True`, `merge` field
│   └── _registry.py             # MODIFY — flip api-explorer to warmup=False
├── static/
│   └── dashboard.js             # MODIFY — EventSource integration
├── templates/
│   ├── overview.html            # MODIFY — embed warmup_strip
│   └── partials/
│       ├── warmup_strip.html    # CREATE
│       └── tile_skeleton.html   # CREATE
├── clients/
│   ├── smartzone.py             # MODIFY — rename _smartzone_* → smartzone_* (public)
│   └── switchm.py               # MODIFY — rename _switch_manager_post → switch_manager_post
└── app.py                       # MODIFY — init app.warmup_state, app.warmup_scheduler

tests/
├── unit/infra/
│   ├── test_parallel_fetch.py   # CREATE
│   └── test_warmup.py           # CREATE
├── integration/
│   ├── test_warmup_routes.py    # CREATE
│   └── test_connect.py          # MODIFY — assert scheduler kicked off
```

---

### Task 1: Public-rename `_smartzone_*` helpers + update call sites

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/clients/smartzone.py`
- Modify: `RUCKUS/ruckus_dashboard/clients/ruckus_one.py` (if imports any `_smartzone_*`)
- Modify: `RUCKUS/ruckus_dashboard/clients/capabilities.py` (likely uses `_controller_root`)
- Test: full existing suite (`tests/unit/clients/test_smartzone.py`) must still pass

- [ ] **Step 1: Identify all underscore helpers to rename**

Run from repo root:
```bash
grep -n "^def _smartzone_" RUCKUS/ruckus_dashboard/clients/smartzone.py
grep -rn "_smartzone_" RUCKUS/ruckus_dashboard tests
```

Expected set to rename (drop leading underscore, keep behavior):
- `_smartzone_paged_get` → `smartzone_paged_get`
- `_smartzone_get` → `smartzone_get`
- `_smartzone_optional_get` → `smartzone_optional_get`
- `_smartzone_post` → `smartzone_post`
- `_smartzone_query_paged` → `smartzone_query_paged`
- `_smartzone_alarm_summary` → `smartzone_alarm_summary`

Do NOT rename truly private internals (`_normalize`, `_aggregate_ap_status`, `_first_value`, etc.) — only the request-helper public API.

- [ ] **Step 2: Apply renames in `clients/smartzone.py`**

For each helper above:
- Change `def _smartzone_post(...)` to `def smartzone_post(...)`.
- Find all internal call sites in the same file and update.

Use `sed` or your editor's replace-in-file (case-sensitive, whole-word). Verify with:
```bash
grep -n "_smartzone_post\|smartzone_post" RUCKUS/ruckus_dashboard/clients/smartzone.py | head -20
```

- [ ] **Step 3: Apply renames in other files**

```bash
grep -rln "_smartzone_post\|_smartzone_get\|_smartzone_paged_get\|_smartzone_optional_get\|_smartzone_query_paged\|_smartzone_alarm_summary" RUCKUS/ruckus_dashboard tests
```

For each file listed, update the calls.

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest -q
```

Expected: 99 passed (unchanged from prior). If a test fails because it referenced the old underscore name, update the test to use the public name.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: promote _smartzone_* request helpers to public API

Drops the underscore prefix on six SmartZone HTTP helpers that the new
modules/<slug>.py files will import. Pure rename — no behavior change.
All 99 existing tests pass unchanged."
```

---

### Task 2: Public-rename `_switch_manager_post` + sibling switchm helpers

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/clients/switchm.py`
- Modify: any callers in `clients/smartzone.py`, `clients/capabilities.py`

- [ ] **Step 1: Identify renames**

```bash
grep -n "^def _switch" RUCKUS/ruckus_dashboard/clients/switchm.py
grep -rn "_switch_manager_post\|_switch_query_payload" RUCKUS/ruckus_dashboard tests
```

Renames:
- `_switch_manager_post` → `switch_manager_post` (already public per Task 14 of Plan 1; verify and skip if already public)
- `_switch_query_payload` → `switch_query_payload` (verify)

If both already public, this task is a no-op — commit nothing and proceed.

- [ ] **Step 2: Apply renames if needed**

Same approach as Task 1.

- [ ] **Step 3: Run tests**

```bash
python -m pytest -q
```

Expected: 99 passed.

- [ ] **Step 4: Commit (if renames applied)**

```bash
git add -A
git commit -m "refactor: promote remaining _switch_* helpers to public API"
```

If nothing changed: skip commit, move to Task 3.

---

### Task 3: Add `warmup` + `merge` fields to `ModuleSpec`

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/modules/_base.py`
- Test: `tests/unit/modules/test_base.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/modules/test_base.py`:

```python
def test_module_spec_warmup_defaults_true():
    spec = ModuleSpec(
        slug="x", title="X", group="Wireless", icon="?",
        poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=noop_summary,
        requires_platforms=("smartzone",), requires_capabilities=(),
        supports_views=("table",),
    )
    assert spec.warmup is True
    assert spec.merge is None


def test_module_spec_warmup_false_when_set():
    spec = ModuleSpec(
        slug="x2", title="X2", group="Wireless", icon="?",
        poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=noop_summary,
        requires_platforms=("smartzone",), requires_capabilities=(),
        supports_views=("table",), warmup=False,
    )
    assert spec.warmup is False


def test_module_spec_merge_function_attaches():
    def my_merge(results): return {"items": []}
    spec = ModuleSpec(
        slug="x3", title="X3", group="Wireless", icon="?",
        poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=noop_summary,
        requires_platforms=("smartzone",), requires_capabilities=(),
        supports_views=("table",), merge=my_merge,
    )
    assert spec.merge is my_merge
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/modules/test_base.py -v
```

Expected: 3 new FAIL with `unexpected keyword argument 'warmup'` / `'merge'`.

- [ ] **Step 3: Add fields to `ModuleSpec`**

Edit `RUCKUS/ruckus_dashboard/modules/_base.py`. Inside the `ModuleSpec` dataclass, add:

```python
    warmup: bool = True
    merge: Callable[[list[dict]], dict] | None = None
```

Place after `supports_views`. Since dataclass is `frozen=True`, default values just work.

- [ ] **Step 4: Run tests pass**

```bash
python -m pytest tests/unit/modules/test_base.py -v
```

Expected: all 3 new pass + 4 existing pass = 7 pass.

Then full suite:
```bash
python -m pytest -q
```

Expected: 102 passed.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/modules/_base.py tests/unit/modules/test_base.py
git commit -m "feat: add warmup + merge fields to ModuleSpec"
```

---

### Task 4: Flip `api-explorer` stub to `warmup=False`

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/modules/_registry.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/modules/test_registry.py`:

```python
def test_api_explorer_excluded_from_warmup():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["api-explorer"].warmup is False


def test_all_other_modules_warmup_enabled():
    from ruckus_dashboard.modules import MODULES
    warmup_disabled = {slug for slug, m in MODULES.items() if not m.warmup}
    assert warmup_disabled == {"api-explorer"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/modules/test_registry.py -v
```

Expected: 2 new FAIL (currently warmup=True for all).

- [ ] **Step 3: Edit registry**

Open `RUCKUS/ruckus_dashboard/modules/_registry.py`. Find the loop that calls `register(ModuleSpec(...))`. Refactor to pass `warmup` per-row:

Change the tuple list `_DEFS` so each row includes a `warmup` flag (default True, False only for `api-explorer`):

```python
_DEFS = [
    # (slug, title, group, icon, poll, caps, warmup)
    ("overview",      "DSO Overview",        "Wireless",      "📡", 15, (), True),
    ("zones",         "Zones",               "Wireless",      "🏢", 60, (("GET", "/rkszones"),), True),
    ("aps",           "Access Points",       "Wireless",      "📶", 30, (("POST", "/query/ap"),), True),
    ("wlans",         "WLANs",               "Wireless",      "🌐", 60, (("POST", "/query/wlan"),), True),
    ("clients",       "Wireless Clients",    "Wireless",      "👥", 20, (("POST", "/query/client"),), True),
    ("alarms",        "Alarms & Events",     "Wireless",      "🚨", 10, (("POST", "/alert/alarmSummary"),), True),
    ("rogues",        "Rogues",              "Wireless",      "👻", 60, (("POST", "/query/roguesInfoList"),), True),
    ("controller",    "Controller",          "Wireless",      "🎛️", 120, (("GET", "/cluster/state"),), True),
    ("switches",      "Switches",            "Switching",     "🔌", 60, (("POST", "/switch/view/details"),), True),
    ("switch-groups", "Switch Groups",       "Switching",     "🗂️", 120, (), True),
    ("ports",         "Ports",               "Switching",     "🔗", 30, (("POST", "/switch/ports/summary"),), True),
    ("traffic",       "Traffic",             "Switching",     "📊", 30, (("POST", "/traffic/top/usage"),), True),
    ("poe",           "PoE",                 "Switching",     "⚡", 60, (("POST", "/traffic/top/poeutilization"),), True),
    ("stack",         "Stack",               "Switching",     "🏗️", 60, (), True),
    ("vlans",         "VLANs",               "Switching",     "🏷️", 60, (), True),
    ("firmware",      "Firmware",            "Cross-cutting", "💾", 120, (), True),
    ("security",      "Security",            "Cross-cutting", "🔒", 600, (), True),
    ("api-explorer",  "API Explorer",        "Cross-cutting", "🧭", 600, (), False),
]

for slug, title, group, icon, poll, caps, warmup_flag in _DEFS:
    register(ModuleSpec(
        slug=slug, title=title, group=group, icon=icon, poll_seconds=poll,
        fetcher=stub_fetcher, drill_fetcher=None, drill_tabs=(),
        summary_fn=stub_summary,
        requires_platforms=("smartzone",),
        requires_capabilities=caps,
        supports_views=("table",),
        warmup=warmup_flag,
    ))
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/modules/ -v
```

Expected: all pass including the 2 new.

Full suite:
```bash
python -m pytest -q
```

Expected: 104 passed.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/modules/_registry.py tests/unit/modules/test_registry.py
git commit -m "feat: flip api-explorer module to warmup=False

The API Explorer enumerates the full 1354-op OpenAPI surface; warming
it up on every login would hammer the controller. Operator opens it
on demand."
```

---

### Task 5: Build `infra/parallel_fetch.py`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/infra/parallel_fetch.py`
- Create: `tests/unit/infra/test_parallel_fetch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/infra/test_parallel_fetch.py
import time
import pytest
from ruckus_dashboard.infra.parallel_fetch import ParallelFetcher, TaskResult


def test_runs_all_tasks_returns_results_keyed_by_id():
    pf = ParallelFetcher(max_workers=2, timeout=5)
    results = pf.run({
        "a": lambda: "result-a",
        "b": lambda: "result-b",
    })
    assert results["a"].ok is True
    assert results["a"].value == "result-a"
    assert results["b"].ok is True
    assert results["b"].value == "result-b"


def test_captures_exceptions_per_task():
    pf = ParallelFetcher(max_workers=2, timeout=5)
    def bad():
        raise ValueError("nope")
    results = pf.run({"good": lambda: 1, "bad": bad})
    assert results["good"].ok is True
    assert results["bad"].ok is False
    assert isinstance(results["bad"].error, ValueError)


def test_per_task_timeout():
    pf = ParallelFetcher(max_workers=2, timeout=0.05)
    def slow():
        time.sleep(0.5)
        return "late"
    results = pf.run({"slow": slow})
    assert results["slow"].ok is False
    assert results["slow"].timed_out is True


def test_empty_task_dict_returns_empty():
    pf = ParallelFetcher(max_workers=2, timeout=1)
    assert pf.run({}) == {}


def test_concurrent_execution_faster_than_sequential():
    pf = ParallelFetcher(max_workers=4, timeout=2)
    def busy():
        time.sleep(0.1)
        return 1
    start = time.time()
    pf.run({f"t{i}": busy for i in range(4)})
    elapsed = time.time() - start
    # 4 tasks × 0.1s sequential = 0.4s. Concurrent with 4 workers should be < 0.25s.
    assert elapsed < 0.25
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/infra/test_parallel_fetch.py -v
```

Expected: 5 FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `parallel_fetch.py`**

```python
# RUCKUS/ruckus_dashboard/infra/parallel_fetch.py
"""Concurrent fetcher with per-task timeout and exception capture."""
from __future__ import annotations
import concurrent.futures
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class TaskResult:
    ok: bool
    value: Any = None
    error: BaseException | None = None
    timed_out: bool = False


class ParallelFetcher:
    """Run a dict of `{id: callable}` concurrently with a per-task timeout.

    Returns `{id: TaskResult}`. Each TaskResult carries either a successful
    value or the captured exception. Timeouts produce `timed_out=True`.
    The fetcher does not raise — every task's outcome is reflected in the
    result dict.
    """

    def __init__(self, max_workers: int = 4, timeout: float = 30.0) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if timeout <= 0:
            raise ValueError("timeout must be > 0")
        self.max_workers = max_workers
        self.timeout = timeout

    def run(self, tasks: dict[str, Callable[[], Any]]) -> dict[str, TaskResult]:
        if not tasks:
            return {}
        results: dict[str, TaskResult] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_id = {pool.submit(fn): tid for tid, fn in tasks.items()}
            for future in concurrent.futures.as_completed(future_to_id, timeout=None):
                tid = future_to_id[future]
                try:
                    value = future.result(timeout=self.timeout)
                    results[tid] = TaskResult(ok=True, value=value)
                except concurrent.futures.TimeoutError as exc:
                    results[tid] = TaskResult(ok=False, error=exc, timed_out=True)
                    future.cancel()
                except BaseException as exc:  # noqa: BLE001 — captured for caller
                    results[tid] = TaskResult(ok=False, error=exc)
        return results
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/unit/infra/test_parallel_fetch.py -v
```

Expected: 5 PASS.

Full suite:
```bash
python -m pytest -q
```

Expected: 109 passed.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/infra/parallel_fetch.py tests/unit/infra/test_parallel_fetch.py
git commit -m "feat: add infra/parallel_fetch.py (ParallelFetcher)"
```

---

### Task 6: Build `infra/warmup.py` — `WarmupScheduler` + `WarmupStatus`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/infra/warmup.py`
- Create: `tests/unit/infra/test_warmup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/infra/test_warmup.py
import time
from dataclasses import dataclass
from ruckus_dashboard.infra.warmup import WarmupScheduler, WarmupStatus
from ruckus_dashboard.modules._base import ModuleSpec, FetcherContext


@dataclass
class FakeConn:
    platform: str = "smartzone"
    display_name: str = "FAKE"
    api_base: str = "https://fake/wsg/api/public"
    auth_token: str = "t"
    verify_tls: bool = False
    api_version: str = "v11_0"
    token_expires_at: float = 9999999999
    tenant_id: str = ""
    controller_version: str = ""


def make_spec(slug, fetcher, caps=(), warmup=True, platforms=("smartzone",)):
    return ModuleSpec(
        slug=slug, title=slug, group="Wireless", icon="?",
        poll_seconds=30, fetcher=fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=lambda d: {"total": len(d.get("items", []))},
        requires_platforms=platforms, requires_capabilities=caps,
        supports_views=("table",), warmup=warmup,
    )


def noop_fetcher(ctx):
    return {"items": [], "warmup_marker": True}


def slow_fetcher(ctx):
    time.sleep(0.2)
    return {"items": [{"x": 1}]}


def failing_fetcher(ctx):
    raise RuntimeError("upstream down")


def test_scheduler_runs_all_warmup_eligible_modules():
    spec_a = make_spec("a", noop_fetcher)
    spec_b = make_spec("b", noop_fetcher)
    scheduler = WarmupScheduler(
        connection=FakeConn(), config={}, modules={"a": spec_a, "b": spec_b},
        available_ops=set(),
    )
    scheduler.run()  # blocks until all done in test mode
    states = scheduler.snapshot()
    assert states["a"].status == "done"
    assert states["b"].status == "done"
    assert states["a"].summary == {"total": 0}


def test_scheduler_skips_warmup_false_modules():
    spec = make_spec("explorer", noop_fetcher, warmup=False)
    scheduler = WarmupScheduler(
        connection=FakeConn(), config={}, modules={"explorer": spec},
        available_ops=set(),
    )
    scheduler.run()
    states = scheduler.snapshot()
    assert states["explorer"].status == "skipped"


def test_scheduler_marks_failed_modules():
    spec = make_spec("bad", failing_fetcher)
    scheduler = WarmupScheduler(
        connection=FakeConn(), config={}, modules={"bad": spec},
        available_ops=set(),
    )
    scheduler.run()
    states = scheduler.snapshot()
    assert states["bad"].status == "failed"
    assert "upstream down" in states["bad"].error_message


def test_scheduler_marks_disabled_when_caps_missing():
    spec = make_spec("aps", noop_fetcher, caps=(("POST", "/query/ap"),))
    scheduler = WarmupScheduler(
        connection=FakeConn(), config={}, modules={"aps": spec},
        available_ops=set(),  # /query/ap NOT present
    )
    scheduler.run()
    states = scheduler.snapshot()
    assert states["aps"].status == "disabled"


def test_scheduler_caps_present_runs_module():
    spec = make_spec("aps", noop_fetcher, caps=(("POST", "/query/ap"),))
    scheduler = WarmupScheduler(
        connection=FakeConn(), config={}, modules={"aps": spec},
        available_ops={("POST", "/query/ap")},
    )
    scheduler.run()
    states = scheduler.snapshot()
    assert states["aps"].status == "done"


def test_scheduler_skips_modules_not_supporting_platform():
    spec = make_spec("r1only", noop_fetcher, platforms=("ruckus_one",))
    scheduler = WarmupScheduler(
        connection=FakeConn(platform="smartzone"), config={},
        modules={"r1only": spec}, available_ops=set(),
    )
    scheduler.run()
    states = scheduler.snapshot()
    assert states["r1only"].status == "skipped"


def test_cancel_stops_pending_tasks():
    started = []
    def long_fetcher(ctx):
        started.append(1)
        time.sleep(5)
        return {"items": []}
    spec_a = make_spec("a", long_fetcher)
    spec_b = make_spec("b", long_fetcher)
    scheduler = WarmupScheduler(
        connection=FakeConn(), config={},
        modules={"a": spec_a, "b": spec_b}, available_ops=set(),
        max_workers=1,
    )
    import threading
    t = threading.Thread(target=scheduler.run, daemon=True)
    t.start()
    time.sleep(0.05)
    scheduler.cancel()
    t.join(timeout=2)
    # At least one task was cancelled before starting
    assert len(started) < 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/infra/test_warmup.py -v
```

Expected: 7 FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `warmup.py`**

```python
# RUCKUS/ruckus_dashboard/infra/warmup.py
"""WarmupScheduler — runs every applicable module fetcher once per session.

Triggered by successful /connect. Iterates the MODULES registry, filters by
platform + capability, dispatches surviving fetchers onto ParallelFetcher,
records per-module status on a thread-safe `_states` dict that the SSE
endpoint observes.
"""
from __future__ import annotations
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..modules._base import FetcherContext, ModuleSpec
from .capability_gate import CapabilityGate
from .parallel_fetch import ParallelFetcher

LOG = logging.getLogger("ruckus_dashboard")


@dataclass
class WarmupStatus:
    slug: str
    status: str = "pending"          # pending | running | done | failed | disabled | skipped | timed_out
    summary: dict | None = None
    error_message: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    missing_capabilities: list[tuple[str, str]] = field(default_factory=list)


class WarmupScheduler:
    """Per-session scheduler. One instance per /connect."""

    def __init__(
        self,
        connection: Any,
        config: dict,
        modules: dict[str, ModuleSpec],
        available_ops: set[tuple[str, str]],
        max_workers: int = 4,
        timeout: float = 30.0,
    ) -> None:
        self.connection = connection
        self.config = config
        self.modules = modules
        self.gate = CapabilityGate(available=available_ops)
        self._states: dict[str, WarmupStatus] = {
            slug: WarmupStatus(slug=slug) for slug in modules
        }
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self._fetcher = ParallelFetcher(max_workers=max_workers, timeout=timeout)
        self._complete = threading.Event()
        self._listeners: list[threading.Event] = []

    # ─── lifecycle ───────────────────────────────────────────────────────
    def run(self) -> None:
        """Synchronous run — used inline in tests and from a daemon thread in prod."""
        tasks: dict[str, Any] = {}
        for slug, spec in self.modules.items():
            if self._cancelled.is_set():
                self._set(slug, status="skipped", error_message="cancelled")
                continue
            if not spec.warmup:
                self._set(slug, status="skipped")
                continue
            if self.connection.platform not in spec.requires_platforms:
                self._set(slug, status="skipped")
                continue
            if not self.gate.satisfied(spec.requires_capabilities):
                self._set(
                    slug, status="disabled",
                    missing_capabilities=self.gate.missing(spec.requires_capabilities),
                )
                continue
            tasks[slug] = self._make_task(spec)
            self._set(slug, status="running", started_at=time.time())

        if not tasks or self._cancelled.is_set():
            self._complete.set()
            self._wake_listeners()
            return

        results = self._fetcher.run(tasks)
        for slug, result in results.items():
            if result.ok:
                spec = self.modules[slug]
                summary = spec.summary_fn(result.value) if spec.summary_fn else {}
                self._set(slug, status="done", summary=summary, completed_at=time.time())
            elif result.timed_out:
                self._set(slug, status="timed_out",
                          error_message="upstream timeout", completed_at=time.time())
            else:
                self._set(slug, status="failed",
                          error_message=str(result.error), completed_at=time.time())
            self._wake_listeners()

        self._complete.set()
        self._wake_listeners()

    def run_in_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.run, name="warmup", daemon=True)
        t.start()
        return t

    def cancel(self) -> None:
        self._cancelled.set()
        self._complete.set()
        self._wake_listeners()

    # ─── observability ──────────────────────────────────────────────────
    def snapshot(self) -> dict[str, WarmupStatus]:
        with self._lock:
            return dict(self._states)

    def is_complete(self) -> bool:
        return self._complete.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._complete.wait(timeout=timeout)

    def add_listener(self) -> threading.Event:
        """Returns an Event that gets set on every state change. SSE uses this."""
        ev = threading.Event()
        with self._lock:
            self._listeners.append(ev)
        return ev

    def remove_listener(self, ev: threading.Event) -> None:
        with self._lock:
            if ev in self._listeners:
                self._listeners.remove(ev)

    # ─── internals ──────────────────────────────────────────────────────
    def _make_task(self, spec: ModuleSpec):
        ctx = FetcherContext(
            connection=self.connection, config=self.config, filters=None,
            capability_gate=self.gate, connection_label=getattr(self.connection, "display_name", ""),
        )
        return lambda: spec.fetcher(ctx)

    def _set(self, slug: str, **fields) -> None:
        with self._lock:
            current = self._states[slug]
            for k, v in fields.items():
                setattr(current, k, v)

    def _wake_listeners(self) -> None:
        with self._lock:
            for ev in self._listeners:
                ev.set()
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/unit/infra/test_warmup.py -v
```

Expected: 7 PASS.

Full suite:
```bash
python -m pytest -q
```

Expected: 116 passed.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/infra/warmup.py tests/unit/infra/test_warmup.py
git commit -m "feat: add infra/warmup.py (WarmupScheduler + WarmupStatus)"
```

---

### Task 7: Wire scheduler into `routes/connect.py` + `app.py`

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/app.py` (init `app.warmup_scheduler = None`)
- Modify: `RUCKUS/ruckus_dashboard/routes/connect.py` (start scheduler on connect, cancel on logout)
- Test: `tests/integration/test_connect.py` (extend)

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_connect.py`:

```python
def test_connect_starts_warmup_scheduler(monkeypatch):
    """After successful connect, app.warmup_scheduler is non-None and running."""
    from ruckus_dashboard.app import create_app
    from ruckus_dashboard.infra.warmup import WarmupScheduler
    import responses

    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})

    base = "https://sz.example:8443/wsg/api/public"
    with responses.RequestsMock() as r:
        r.add(responses.GET, f"{base}/apiInfo",
              json={"apiSupportVersions": ["v11_0"]}, status=200)
        r.add(responses.POST, f"{base}/v11_0/serviceTicket",
              json={"serviceTicket": "tkt", "controllerVersion": "6"}, status=200)
        # capability discovery probes — return 404 to skip
        r.add(responses.GET, "https://sz.example:8443/wsg/apiDoc/openapi",
              status=404)
        r.add(responses.GET, "https://sz.example:8443/switchm/api/openapi",
              status=404)

        with app.test_client() as c:
            c.get("/")
            with c.session_transaction() as s:
                token = s["csrf_token"]
            resp = c.post("/connect", data={
                "csrf_token": token,
                "platform": "smartzone",
                "smartzone_host": "sz.example",
                "smartzone_username": "u",
                "smartzone_password": "p",
                "smartzone_api_version": "auto",
                "smartzone_skip_tls_verify": "1",
            }, follow_redirects=False)
            assert resp.status_code == 302
            assert app.warmup_scheduler is not None
            assert isinstance(app.warmup_scheduler, WarmupScheduler)


def test_logout_cancels_warmup_scheduler():
    """POST /logout calls cancel() on the active scheduler."""
    from ruckus_dashboard.app import create_app
    from ruckus_dashboard.infra.warmup import WarmupScheduler
    from unittest.mock import MagicMock

    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    fake_scheduler = MagicMock(spec=WarmupScheduler)
    app.warmup_scheduler = fake_scheduler

    with app.test_client() as c:
        c.get("/")
        with c.session_transaction() as s:
            s["auth"] = True
            s["connection_ids"] = []
            token = s["csrf_token"]
        resp = c.post("/logout", data={"csrf_token": token}, follow_redirects=False)
        assert resp.status_code in (200, 302)
        fake_scheduler.cancel.assert_called_once()
        assert app.warmup_scheduler is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/integration/test_connect.py -v
```

Expected: 2 new FAIL (no `app.warmup_scheduler` attribute).

- [ ] **Step 3: Modify `app.py`**

In `create_app()`, after `app.module_cache = ModuleResultCache()` add:

```python
    app.warmup_scheduler = None  # initialised by routes/connect.py on /connect
```

Verify `app.available_ops = set()` is already present (was added in feat/login-flow commit).

- [ ] **Step 4: Modify `routes/connect.py`**

In the `/connect` POST handler, after `session["connection_ids"] = [new_id]` and capability discovery already runs (look for where `current_app.available_ops` gets populated), add:

```python
    from ..infra.warmup import WarmupScheduler
    from ..modules import MODULES

    # Cancel any prior scheduler
    if getattr(current_app, "warmup_scheduler", None) is not None:
        current_app.warmup_scheduler.cancel()

    # Start a new one for this connection
    scheduler = WarmupScheduler(
        connection=connection,
        config=dict(current_app.config),
        modules=dict(MODULES),
        available_ops=set(current_app.available_ops),
        max_workers=int(current_app.config.get("RUCKUS_WARMUP_WORKERS", 4)),
        timeout=float(current_app.config.get("RUCKUS_WARMUP_TIMEOUT", 30.0)),
    )
    current_app.warmup_scheduler = scheduler
    scheduler.run_in_thread()
```

Also add to `config.py` (`build_config`):

```python
        "RUCKUS_WARMUP_WORKERS": _int_env("RUCKUS_WARMUP_WORKERS", 4),
        "RUCKUS_WARMUP_TIMEOUT": _float_env("RUCKUS_WARMUP_TIMEOUT", 30.0),
```

In the `/logout` handler, after `disconnect_*` calls but before `session.clear()`:

```python
    if getattr(current_app, "warmup_scheduler", None) is not None:
        current_app.warmup_scheduler.cancel()
        current_app.warmup_scheduler = None
```

- [ ] **Step 5: Run tests + commit**

```bash
python -m pytest tests/integration/test_connect.py -v
python -m pytest -q
```

Expected: full suite green.

```bash
git add RUCKUS/ruckus_dashboard/app.py RUCKUS/ruckus_dashboard/routes/connect.py RUCKUS/ruckus_dashboard/config.py tests/integration/test_connect.py
git commit -m "feat: kick off WarmupScheduler on /connect, cancel on /logout"
```

---

### Task 8: Build `routes/warmup.py` — sync `/api/warmup/status` endpoint

**Files:**
- Create: `RUCKUS/ruckus_dashboard/routes/warmup.py`
- Modify: `RUCKUS/ruckus_dashboard/app.py` (register blueprint)
- Create: `tests/integration/test_warmup_routes.py`

- [ ] **Step 1: Write failing test (sync endpoint first; SSE in Task 9)**

```python
# tests/integration/test_warmup_routes.py
from unittest.mock import MagicMock
from ruckus_dashboard.app import create_app
from ruckus_dashboard.infra.warmup import WarmupScheduler, WarmupStatus


def _make_authed_app():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    return app


def test_status_endpoint_requires_auth():
    app = _make_authed_app()
    with app.test_client() as c:
        r = c.get("/api/warmup/status")
        assert r.status_code == 401


def test_status_returns_no_scheduler_when_none():
    app = _make_authed_app()
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["auth"] = True
        r = c.get("/api/warmup/status")
        assert r.status_code == 200
        body = r.get_json()
        assert body["complete"] is True
        assert body["states"] == {}


def test_status_reflects_scheduler_snapshot():
    app = _make_authed_app()
    fake = MagicMock(spec=WarmupScheduler)
    fake.is_complete.return_value = False
    fake.snapshot.return_value = {
        "aps": WarmupStatus(slug="aps", status="running"),
        "wlans": WarmupStatus(slug="wlans", status="done",
                              summary={"total": 12}),
    }
    app.warmup_scheduler = fake

    with app.test_client() as c:
        with c.session_transaction() as s:
            s["auth"] = True
        r = c.get("/api/warmup/status")
        body = r.get_json()
        assert body["complete"] is False
        assert body["states"]["aps"]["status"] == "running"
        assert body["states"]["wlans"]["status"] == "done"
        assert body["states"]["wlans"]["summary"] == {"total": 12}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/integration/test_warmup_routes.py -v
```

Expected: 3 FAIL with 404 (route not registered).

- [ ] **Step 3: Create `routes/warmup.py`**

```python
# RUCKUS/ruckus_dashboard/routes/warmup.py
"""Warmup observability endpoints (SSE + sync status)."""
from __future__ import annotations
from dataclasses import asdict
from flask import Blueprint, current_app, jsonify, session

bp = Blueprint("warmup", __name__)


@bp.get("/api/warmup/status")
def status():
    if not session.get("auth"):
        return jsonify({"error": "Not authenticated.", "reauth": True}), 401

    scheduler = getattr(current_app, "warmup_scheduler", None)
    if scheduler is None:
        return jsonify({"complete": True, "states": {}})

    snap = scheduler.snapshot()
    states = {slug: _serialise_status(st) for slug, st in snap.items()}
    return jsonify({"complete": scheduler.is_complete(), "states": states})


def _serialise_status(st) -> dict:
    return {
        "slug": st.slug,
        "status": st.status,
        "summary": st.summary,
        "error_message": st.error_message,
        "started_at": st.started_at,
        "completed_at": st.completed_at,
        "missing_capabilities": [list(c) for c in st.missing_capabilities],
    }
```

- [ ] **Step 4: Register blueprint in `app.py`**

After `app.register_blueprint(connect_bp)`:

```python
    from .routes.warmup import bp as warmup_bp
    app.register_blueprint(warmup_bp)
```

- [ ] **Step 5: Run tests + commit**

```bash
python -m pytest tests/integration/test_warmup_routes.py -v
python -m pytest -q
```

Expected: 3 new PASS, full suite green.

```bash
git add RUCKUS/ruckus_dashboard/routes/warmup.py RUCKUS/ruckus_dashboard/app.py tests/integration/test_warmup_routes.py
git commit -m "feat: GET /api/warmup/status sync endpoint"
```

---

### Task 9: Add SSE stream endpoint `/api/warmup`

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/routes/warmup.py`
- Modify: `tests/integration/test_warmup_routes.py`

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_warmup_routes.py`:

```python
import time

def test_sse_endpoint_streams_events():
    """Connect, attach a fake scheduler with completed state,
    consume the SSE stream, assert at least one module-ready event + complete."""
    app = _make_authed_app()
    fake = MagicMock(spec=WarmupScheduler)
    fake.is_complete.side_effect = [False, True]  # first poll incomplete, second complete
    fake.snapshot.return_value = {
        "aps": WarmupStatus(slug="aps", status="done", summary={"total": 5}),
    }
    listener_event = MagicMock()
    listener_event.wait = MagicMock(return_value=True)
    listener_event.clear = MagicMock()
    fake.add_listener.return_value = listener_event

    app.warmup_scheduler = fake

    with app.test_client() as c:
        with c.session_transaction() as s:
            s["auth"] = True
        r = c.get("/api/warmup", buffered=False)
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("text/event-stream")

        # Read up to 4KB of stream
        data = b""
        for chunk in r.response:
            data += chunk
            if b"event: complete" in data or len(data) > 4096:
                break
        text = data.decode()
        assert "event: module-ready" in text
        assert "aps" in text
        assert "event: complete" in text


def test_sse_endpoint_requires_auth():
    app = _make_authed_app()
    with app.test_client() as c:
        r = c.get("/api/warmup")
        assert r.status_code == 401
```

- [ ] **Step 2: Run test → expect FAIL**

```bash
python -m pytest tests/integration/test_warmup_routes.py::test_sse_endpoint_streams_events -v
```

Expected: FAIL (404 — route not added).

- [ ] **Step 3: Add SSE endpoint to `routes/warmup.py`**

Append to `routes/warmup.py`:

```python
import json
import time
from flask import Response, stream_with_context


@bp.get("/api/warmup")
def stream():
    if not session.get("auth"):
        return jsonify({"error": "Not authenticated.", "reauth": True}), 401

    scheduler = getattr(current_app, "warmup_scheduler", None)

    @stream_with_context
    def gen():
        if scheduler is None:
            yield "event: complete\ndata: {}\n\n"
            return

        listener = scheduler.add_listener()
        seen_states: dict[str, str] = {}
        try:
            # Initial flush — send current state of every terminal module
            for slug, st in scheduler.snapshot().items():
                if st.status in ("done", "failed", "disabled", "timed_out", "skipped"):
                    payload = json.dumps(_serialise_status(st))
                    yield f"event: module-ready\ndata: {payload}\n\n"
                    seen_states[slug] = st.status

            # Stream subsequent state changes
            while not scheduler.is_complete():
                listener.wait(timeout=2.0)
                listener.clear()
                for slug, st in scheduler.snapshot().items():
                    if seen_states.get(slug) != st.status and st.status in (
                        "done", "failed", "disabled", "timed_out", "skipped"
                    ):
                        payload = json.dumps(_serialise_status(st))
                        yield f"event: module-ready\ndata: {payload}\n\n"
                        seen_states[slug] = st.status

            yield "event: complete\ndata: {}\n\n"
        finally:
            scheduler.remove_listener(listener)

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
```

- [ ] **Step 4: Run tests + commit**

```bash
python -m pytest tests/integration/test_warmup_routes.py -v
python -m pytest -q
```

Expected: 5 PASS in this file, full suite green.

```bash
git add RUCKUS/ruckus_dashboard/routes/warmup.py tests/integration/test_warmup_routes.py
git commit -m "feat: GET /api/warmup SSE stream for warmup events"
```

---

### Task 10: Build progress strip + skeleton tile partials

**Files:**
- Create: `RUCKUS/ruckus_dashboard/templates/partials/warmup_strip.html`
- Create: `RUCKUS/ruckus_dashboard/templates/partials/tile_skeleton.html`
- Modify: `RUCKUS/ruckus_dashboard/templates/overview.html`
- Modify: `RUCKUS/ruckus_dashboard/static/styles.css` (append progress styles)
- Test: `tests/integration/test_pages.py`

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_pages.py`:

```python
def test_overview_renders_warmup_strip_when_authenticated():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        c.get("/")
        with c.session_transaction() as s:
            s["auth"] = True
            s["connection_ids"] = []
        r = c.get("/")
        assert r.status_code == 200
        assert b"warmup-strip" in r.data
        assert b"tile-skeleton" in r.data
```

- [ ] **Step 2: Run → expect FAIL**

```bash
python -m pytest tests/integration/test_pages.py::test_overview_renders_warmup_strip_when_authenticated -v
```

Expected: FAIL — markers absent.

- [ ] **Step 3: Create partials**

`RUCKUS/ruckus_dashboard/templates/partials/warmup_strip.html`:

```html
<div class="warmup-strip" data-warmup-strip hidden>
  <div class="warmup-bar"><div class="warmup-fill" data-warmup-fill></div></div>
  <span class="warmup-text" data-warmup-text>Discovering RUCKUS controller…</span>
</div>
```

`RUCKUS/ruckus_dashboard/templates/partials/tile_skeleton.html`:

```html
<span class="tile-skeleton" data-tile-skeleton>…</span>
```

Modify `overview.html` — add the strip just inside `{% block content %}` and replace the static `—` tile value with the skeleton:

```html
{% block content %}
{% include "partials/warmup_strip.html" %}
<section class="overview">
  <h1>DSO Overview</h1>
  <p class="subtitle">Live service-health rollup. Click any tile to drill in.</p>
  <div class="tile-grid">
    {% for m in modules if m.slug != "overview" %}
    <a href="/m/{{ m.slug }}" class="tile" data-slug="{{ m.slug }}" data-tile-status="pending">
      <span class="tile-icon">{{ m.icon }}</span>
      <span class="tile-title">{{ m.title }}</span>
      <span class="tile-value" data-tile-value="{{ m.slug }}">
        {% include "partials/tile_skeleton.html" %}
      </span>
    </a>
    {% endfor %}
  </div>
</section>
{% endblock %}
```

Append to `styles.css`:

```css
.warmup-strip { display: flex; align-items: center; gap: 12px;
                padding: 10px 14px; background: var(--surface-soft);
                border: 1px solid var(--border); border-radius: 8px;
                margin: 0 0 12px; font-size: 12px; color: var(--muted); }
.warmup-strip[hidden] { display: none; }
.warmup-bar { flex: 1; height: 6px; background: var(--rail); border-radius: 999px; overflow: hidden; }
.warmup-fill { height: 100%; width: 0%; background: var(--accent); transition: width 0.3s; }
.warmup-text { white-space: nowrap; font-weight: 700; }
.tile-skeleton { color: var(--muted); opacity: 0.55; font-weight: 400; }
.tile[data-tile-status="done"] .tile-value { color: var(--text); }
.tile[data-tile-status="failed"] .tile-value { color: var(--critical); }
.tile[data-tile-status="disabled"] .tile-value { color: var(--muted); }
```

- [ ] **Step 4: Run tests pass + commit**

```bash
python -m pytest tests/integration/test_pages.py -v
python -m pytest -q
```

```bash
git add RUCKUS/ruckus_dashboard/templates/ RUCKUS/ruckus_dashboard/static/styles.css tests/integration/test_pages.py
git commit -m "feat: warmup progress strip + tile skeletons on overview"
```

---

### Task 11: Wire `EventSource` warmup integration into `dashboard.js`

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/static/dashboard.js`
- Modify: `tests/integration/test_dashboard_js.py`

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_dashboard_js.py`:

```python
def test_dashboard_js_contains_warmup_integration():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        r = c.get("/static/dashboard.js")
        body = r.data.decode()
        for symbol in ["startWarmupStream", "updateTile", "EventSource",
                       "/api/warmup", "module-ready", "data-warmup-strip",
                       "data-tile-status"]:
            assert symbol in body, f"missing symbol: {symbol}"
```

- [ ] **Step 2: Run → expect FAIL**

```bash
python -m pytest tests/integration/test_dashboard_js.py -v
```

Expected: FAIL on new test.

- [ ] **Step 3: Extend `dashboard.js`**

Append to bottom of `dashboard.js` (before the closing `});` of DOMContentLoaded):

```javascript
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
    bar.style.width = `${Math.round(100 * done / total)}%`;
    text.textContent = `Discovering RUCKUS controller… ${done}/${total}`;
  };

  const finish = () => {
    strip.hidden = true;
  };

  try {
    const es = new EventSource("/api/warmup");
    es.addEventListener("module-ready", (e) => {
      try { updateTile(JSON.parse(e.data)); } catch {}
    });
    es.addEventListener("complete", () => { es.close(); finish(); });
    es.onerror = () => {
      es.close();
      // Polling fallback
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
    // EventSource unsupported — go straight to polling
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
```

In the existing `DOMContentLoaded` handler, after the per-tile `fetch` loop, replace that whole `document.querySelectorAll(".tile[data-slug]")` block with:

```javascript
  // Overview page: warmup-driven tile loading
  if (document.querySelector("[data-warmup-strip]")) {
    startWarmupStream();
  }
```

This stops the old fan-out fetch on Overview (the warmup stream + status endpoint replace it).

- [ ] **Step 4: Run tests + commit**

```bash
python -m pytest tests/integration/test_dashboard_js.py -v
python -m pytest -q
```

```bash
git add RUCKUS/ruckus_dashboard/static/dashboard.js tests/integration/test_dashboard_js.py
git commit -m "feat: dashboard.js opens EventSource on overview, updates tiles live"
```

---

### Task 12: End-to-end smoke test

**Files:**
- Modify: `tests/smoke/test_launch.py` (extend)

- [ ] **Step 1: Add smoke check that warmup endpoint serves**

Append to `tests/smoke/test_launch.py`:

```python
def test_warmup_status_endpoint_reachable_when_unauthenticated(tmp_path):
    """Boot CLI, hit /api/warmup/status — expect 401 (proves blueprint registered)."""
    import subprocess, sys, socket, time, ssl, urllib.request, json
    proc = subprocess.Popen(
        [sys.executable, "-m", "ruckus_dashboard",
         "--bind", "127.0.0.1", "--port", "0", "--no-browser"],
        cwd="RUCKUS",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        port = None
        deadline = time.time() + 10
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line: break
            if "Opening dashboard:" in line:
                port = int(line.rsplit(":", 1)[1].strip())
                break
        assert port

        # Wait for socket
        for _ in range(30):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)

        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(f"https://127.0.0.1:{port}/api/warmup/status")
        try:
            urllib.request.urlopen(req, context=ctx, timeout=5)
            assert False, "expected 401"
        except urllib.error.HTTPError as e:
            assert e.code == 401
    finally:
        proc.terminate()
        proc.wait(timeout=5)
```

- [ ] **Step 2: Run → expect PASS (route exists, just unauthenticated)**

```bash
python -m pytest tests/smoke/ -v
```

Expected: PASS.

- [ ] **Step 3: Full suite**

```bash
python -m pytest -q
```

Expected: full count green (~125+ depending on prior task counts).

- [ ] **Step 4: Commit**

```bash
git add tests/smoke/test_launch.py
git commit -m "test: smoke check /api/warmup/status route is registered"
```

---

## Acceptance criteria (Plan 2a done)

- [ ] `_smartzone_*` request helpers renamed to public names (no underscore prefix).
- [ ] `ModuleSpec` gains `warmup: bool = True` and `merge` field.
- [ ] `api-explorer` stub has `warmup=False`; all others `warmup=True`.
- [ ] `infra/parallel_fetch.py::ParallelFetcher` exists, tested.
- [ ] `infra/warmup.py::WarmupScheduler` exists, tested.
- [ ] `POST /connect` kicks off scheduler on success.
- [ ] `POST /logout` cancels scheduler.
- [ ] `GET /api/warmup/status` returns JSON snapshot.
- [ ] `GET /api/warmup` streams SSE module-ready + complete events.
- [ ] Overview page includes `warmup-strip` + tile skeletons.
- [ ] `dashboard.js` opens `EventSource("/api/warmup")` on overview load, updates tiles live, falls back to polling on SSE error.
- [ ] All existing tests still pass.
- [ ] Smoke test confirms `/api/warmup/status` route registered.

## Follow-ups (not in scope)

- **Plan 2b** — replace stub fetchers with real wireless module implementations (overview, zones, aps, wlans, clients, alarms, rogues, controller).
- **Plan 2c** — switching modules (switches, switch-groups, ports, traffic, poe, stack, vlans).
- **Plan 2d** — cross-cutting modules (firmware, security, api-explorer) + `scripts/install.sh` + `scripts/start.sh` + deploy docs.

## Self-review

**Spec coverage** ✓ — Section 1.1 (WarmupScheduler) → Task 6. Section 1.2 (SSE + status routes) → Tasks 8, 9. Section 1.3 (dashboard.js integration) → Task 11. Section 1.4 (ParallelFetcher) → Task 5. Section 1.5 (ModuleSpec extensions) → Task 3 (`warmup` + `merge` fields). API Explorer warmup=False → Task 4. Connect lifecycle → Task 7. Public-rename refactor → Tasks 1, 2.

**Placeholder scan** ✓ — every step has either exact commands, exact code, or an exact rename procedure. No "implement appropriately" or "similar to X".

**Type consistency** ✓ — `WarmupStatus` fields (`slug`, `status`, `summary`, `error_message`, `started_at`, `completed_at`, `missing_capabilities`) used consistently across Tasks 6, 8, 9, 11. `_serialise_status` shape in Task 8 matches what `dashboard.js::updateTile` reads in Task 11.

**Scope** ✓ — single shippable increment (warmup infra). No real fetchers leak in. Behind the existing `RUCKUS_ENABLE_NEW_UI=1` flag.
