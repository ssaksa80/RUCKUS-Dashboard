# SP7 — Audit Fixes (Hardening + Capability Seam) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the High/Medium security and correctness findings from the SP7 audit and extract the `CapabilityRegistry` seam (SP6 Phase-A1), hardening the single-node appliance with no behavior regression.

**Architecture:** Strict TDD, one finding per task, frequent commits. Order: security (SSRF redirect, deny-by-default allow-list) → the `available_ops`→`CapabilityRegistry` per-connection seam → real fetch timeout → drill error-disclosure parity → file/secret hardening → config deep-merge. All work is in the `ruckus_dashboard` package; the existing 301-test suite is the regression net and must stay green after every task.

**Tech Stack:** Python 3.10–3.12, Flask, `requests`, `responses` (HTTP mocking in tests), `pytest`, `ruff`. Windows + Linux (CI matrix).

**Deferred to SP2 (do NOT fix here — SP2 rewrites notify state durably):** audit #4 (alert baseline-spam), #5 (daily-report dedup durability), #14 (`count or 1`). **Deferred / YAGNI:** #15 (ConnectionStore background sweep — eviction-on-access is acceptable for the appliance).

**Repo root:** `C:\Users\sshoaib\OneDrive - Mohamed & Obaid Almulla LLC\Documents\RUCKUS-Dashboard`
**Package root (paths below are relative to it):** `RUCKUS/ruckus_dashboard/`
**Run tests from:** the repo root, with the venv that has `pip install -e RUCKUS[test]` + `ruff`.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `RUCKUS/ruckus_dashboard/clients/base.py` | `request_json` — add `allow_redirects=False` | 1 |
| `RUCKUS/ruckus_dashboard/net/allowlist.py` | add `is_loopback` + `require_allowlist_for_bind` | 2 |
| `RUCKUS/ruckus_dashboard/cli.py` | call the bind guard before serving | 2 |
| `RUCKUS/ruckus_dashboard/infra/capability_registry.py` | **new** — per-connection ops store | 3 |
| `RUCKUS/ruckus_dashboard/app.py` | wire registry instead of `available_ops` set | 3 |
| `RUCKUS/ruckus_dashboard/routes/connect.py` | set/clear per-connection ops | 3 |
| `RUCKUS/ruckus_dashboard/routes/modules.py` | build gate from registry; drill error parity | 3, 5 |
| `RUCKUS/ruckus_dashboard/infra/parallel_fetch.py` | real per-task timeout (no straggler block) | 4 |
| `RUCKUS/ruckus_dashboard/auth/secrets.py` | chmod-before-replace; warn when unavailable; DPAPI scope env | 6, 7 |
| `RUCKUS/ruckus_dashboard/auth/profiles.py` | chmod-before-replace | 6 |
| `RUCKUS/ruckus_dashboard/notify/config.py` | chmod `notifications.json`; deep section merge | 6, 8 |

---

### Task 1: Block SSRF via HTTP redirect (audit #1)

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/clients/base.py` (`request_json`, the `requests.request(...)` call ~line 234)
- Test: `tests/unit/clients/test_base.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/clients/test_base.py`:

```python
@responses.activate
def test_request_json_does_not_follow_redirects():
    # A controller (or MITM) returning a 3xx to an internal host must NOT be followed.
    responses.add(
        responses.GET, "https://ctrl.example/wsg/api/public/apiInfo",
        status=302, headers={"Location": "http://169.254.169.254/latest/meta-data"},
    )
    cfg = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000, "RUCKUS_HOST_ALLOWLIST": None}
    with pytest.raises(RuckusClientError) as ei:
        request_json("GET", "https://ctrl.example/wsg/api/public/apiInfo", cfg, debug_label="probe")
    assert ei.value.status_code == 302          # surfaced as an error, not followed
    assert len(responses.calls) == 1            # the redirect target was never contacted
```

Ensure the test file imports exist (add if missing): `import pytest`, `import responses`, `from ruckus_dashboard.clients.base import request_json, RuckusClientError`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/clients/test_base.py::test_request_json_does_not_follow_redirects -v`
Expected: FAIL — without the fix `requests` follows the 302 to an unregistered URL, raising `ConnectionError` → `RuckusClientError(status_code=502)`, so `status_code == 302` fails (and `len(calls)` may be 2).

- [ ] **Step 3: Write minimal implementation**

In `RUCKUS/ruckus_dashboard/clients/base.py`, change the request call inside `request_json` from:

```python
        response = requests.request(method, url, timeout=timeout, **kwargs)
```
to:
```python
        # SSRF guard: the allow-list is checked on the initial host only, so a 3xx
        # must not be auto-followed to an unchecked host. RUCKUS APIs never redirect.
        response = requests.request(method, url, timeout=timeout, allow_redirects=False, **kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/clients/test_base.py -v`
Expected: PASS (new test + existing base tests).

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/clients/base.py tests/unit/clients/test_base.py
git commit -m "fix(security): do not follow HTTP redirects in request_json (SSRF guard)"
```

---

### Task 2: Deny-by-default allow-list for non-loopback bind (audit #3)

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/net/allowlist.py` (add two functions)
- Modify: `RUCKUS/ruckus_dashboard/cli.py` (call the guard before `app.run`/serve)
- Test: `tests/unit/net/test_allowlist.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/net/test_allowlist.py`:

```python
import pytest
from ruckus_dashboard.net.allowlist import HostAllowList, require_allowlist_for_bind

def test_loopback_bind_allows_empty_allowlist():
    require_allowlist_for_bind("127.0.0.1", HostAllowList(""))   # no raise

def test_non_loopback_bind_requires_allowlist():
    with pytest.raises(RuntimeError, match="RUCKUS_ALLOWED_HOSTS"):
        require_allowlist_for_bind("0.0.0.0", HostAllowList(""))

def test_non_loopback_bind_ok_when_allowlist_configured():
    require_allowlist_for_bind("0.0.0.0", HostAllowList("10.0.0.0/8"))   # no raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/net/test_allowlist.py -k require_allowlist -v`
Expected: FAIL with `ImportError: cannot import name 'require_allowlist_for_bind'`.

- [ ] **Step 3: Write minimal implementation**

Append to `RUCKUS/ruckus_dashboard/net/allowlist.py`:

```python
def is_loopback(host: str) -> bool:
    h = (host or "").strip().lower().strip("[]")
    if h in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def require_allowlist_for_bind(host: str, allowlist: "HostAllowList | None") -> None:
    """Fail fast on a non-loopback bind with no SSRF allow-list configured.

    Loopback binds (127.0.0.1/::1/localhost) are dev-safe and allowed empty.
    Any other interface without RUCKUS_ALLOWED_HOSTS is refused — the server
    must not be usable as an open SSRF proxy to internal hosts.
    """
    if is_loopback(host):
        return
    if allowlist is None or not allowlist.enabled:
        raise RuntimeError(
            "Refusing to bind to a non-loopback interface without RUCKUS_ALLOWED_HOSTS. "
            "Set RUCKUS_ALLOWED_HOSTS (CSV of hosts/CIDRs) or bind to 127.0.0.1."
        )
```

(`ipaddress` is already imported at the top of the file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/net/test_allowlist.py -v`
Expected: PASS.

- [ ] **Step 5: Wire the guard into startup**

In `RUCKUS/ruckus_dashboard/cli.py`, in `main()`, AFTER the config + `RUCKUS_HOST_ALLOWLIST` are built and the effective bind host is known (the variable is `bind_host`, set ~line 234) and BEFORE the server starts (`app.run(...)` ~line 260), add:

```python
    from .net.allowlist import require_allowlist_for_bind
    require_allowlist_for_bind(bind_host, app.config.get("RUCKUS_HOST_ALLOWLIST"))
```

- [ ] **Step 6: Run the integration/CLI tests**

Run: `pytest tests/integration/test_cli.py tests/smoke/test_launch.py -v`
Expected: PASS — existing tests bind loopback, so the guard is a no-op for them.

- [ ] **Step 7: Commit**

```bash
git add RUCKUS/ruckus_dashboard/net/allowlist.py RUCKUS/ruckus_dashboard/cli.py tests/unit/net/test_allowlist.py
git commit -m "fix(security): refuse non-loopback bind without RUCKUS_ALLOWED_HOSTS"
```

---

### Task 3: Per-connection `CapabilityRegistry` seam (audit #2, SP6 Phase-A1)

Replaces the single process-global `available_ops` set with a per-connection store so two operators on different controllers cannot leak/clear each other's capability gating.

**Files:**
- Create: `RUCKUS/ruckus_dashboard/infra/capability_registry.py`
- Modify: `RUCKUS/ruckus_dashboard/app.py` (~line 50)
- Modify: `RUCKUS/ruckus_dashboard/routes/connect.py` (~lines 79, 113, 140-142)
- Modify: `RUCKUS/ruckus_dashboard/routes/modules.py` (gate build ~lines 81, 139, 170)
- Test: `tests/unit/infra/test_capability_registry.py`

- [ ] **Step 1: Write the failing test (isolation guarantee — the regression test for the bug)**

Create `tests/unit/infra/test_capability_registry.py`:

```python
from ruckus_dashboard.infra.capability_registry import CapabilityRegistry

def test_ops_isolated_per_connection():
    reg = CapabilityRegistry()
    reg.set_for("connA", {("GET", "/x")})
    reg.set_for("connB", {("POST", "/y")})
    assert reg.get_for(["connA"]) == {("GET", "/x")}
    assert reg.get_for(["connB"]) == {("POST", "/y")}
    assert reg.get_for(["connA", "connB"]) == {("GET", "/x"), ("POST", "/y")}

def test_clear_one_connection_does_not_affect_other():
    reg = CapabilityRegistry()
    reg.set_for("connA", {("GET", "/x")})
    reg.set_for("connB", {("POST", "/y")})
    reg.clear("connB")                       # operator B logs out
    assert reg.get_for(["connA"]) == {("GET", "/x")}   # A is untouched
    assert reg.get_for(["connB"]) == set()

def test_unknown_connection_returns_empty():
    assert CapabilityRegistry().get_for(["nope"]) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/infra/test_capability_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: ruckus_dashboard.infra.capability_registry`.

- [ ] **Step 3: Create the registry**

Create `RUCKUS/ruckus_dashboard/infra/capability_registry.py`:

```python
"""Per-connection capability (OpenAPI op) store.

Replaces the former process-global ``app.available_ops`` set, which was shared
across all sessions: a second operator's logout wiped the first's gating and a
second controller's ops leaked into the first operator's module visibility.
Keyed by connection_id, it is the Phase-A1 seam for a future Redis-backed impl.
"""
from __future__ import annotations

from threading import RLock
from typing import Iterable, Sequence


class CapabilityRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._ops: dict[str, set[tuple[str, str]]] = {}

    def set_for(self, connection_id: str, ops: Iterable[tuple[str, str]]) -> None:
        with self._lock:
            self._ops[connection_id] = set(ops)

    def get_for(self, connection_ids: Sequence[str]) -> set[tuple[str, str]]:
        with self._lock:
            out: set[tuple[str, str]] = set()
            for cid in connection_ids:
                out |= self._ops.get(cid, set())
            return out

    def clear(self, connection_id: str) -> None:
        with self._lock:
            self._ops.pop(connection_id, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/infra/test_capability_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Wire into the app factory**

In `RUCKUS/ruckus_dashboard/app.py`, replace the `available_ops` line (~50):

```python
    app.available_ops = set()
```
with:
```python
    from .infra.capability_registry import CapabilityRegistry
    app.capability_registry = CapabilityRegistry()
```

- [ ] **Step 6: Update connect.py (set on connect, clear on logout)**

In `RUCKUS/ruckus_dashboard/routes/connect.py`:

(a) In `connect()` where the warmup scheduler is built (~line 79) it currently passes `available_ops=set(current_app.available_ops)`. Change it to the new connection's ops:
```python
        available_ops=current_app.capability_registry.get_for([new_id]),
```

(b) In `logout()` (~line 113) replace `current_app.available_ops = set()` with a clear of each session connection BEFORE `session.clear()`:
```python
    for cid in list(session.get("connection_ids", [])):
        current_app.capability_registry.clear(cid)
```
(Place this in the existing logout loop that already calls `connection_store.remove(cid)`; remove the old `current_app.available_ops = set()` line.)

(c) In `_refresh_available_ops(connection)` (~lines 117-142): it is called before `new_id` exists in the current flow. Change the call site in `connect()` to capture the id and pass it. Replace the body's global union (~140-142):
```python
    ops = caps.get("available_ops") or set()
    current_app.capability_registry.set_for(connection_id, ops)
```
and change the function signature to `def _refresh_available_ops(connection, connection_id) -> None:` and its call in `connect()` (~line 67) to `_refresh_available_ops(connection, new_id)`. Note `new_id` is created at `connect.py:55` (`new_id = current_app.connection_store.put(connection)`) — call `_refresh_available_ops` after that line.

- [ ] **Step 7: Update modules.py (build the gate from the registry)**

In `RUCKUS/ruckus_dashboard/routes/modules.py`, every gate is built as:
```python
    gate = CapabilityGate(available=getattr(current_app, "available_ops", set()))
```
(occurs ~lines 81, 139, 170). Replace each with:
```python
    gate = CapabilityGate(available=current_app.capability_registry.get_for(conn_ids))
```
In `module_data` `conn_ids` is already defined (~line 75). In `module_drill` / `module_drill_tab`, `conn_ids` is also already computed from the session (~lines 133, 164) before the gate line — confirm and reuse it.

- [ ] **Step 8: Find and fix every remaining reference**

Run: `grep -rn "available_ops" RUCKUS/ruckus_dashboard`
Expected after edits: **only** occurrences inside `clients/capabilities.py` (the discovery payload key `caps["available_ops"]`) and `dump.py` (which reads `discover_capabilities(...)` directly, not the app global). There must be **no** `current_app.available_ops` / `app.available_ops` left. Fix any stragglers.

- [ ] **Step 9: Update tests that referenced the old global**

Run: `grep -rn "available_ops" tests`
For each integration test that set `app.available_ops = {...}` (e.g. `tests/integration/test_routes_new_ui.py`, `test_connect.py`), replace with:
```python
    app.capability_registry.set_for(<connection_id>, {(...)})
```
using the connection id the test stored in the session. Where a test used a fixture connection id, set the registry for that id.

- [ ] **Step 10: Run the full suite**

Run: `pytest -q`
Expected: PASS (301 + new tests). Then `ruff check RUCKUS/ruckus_dashboard tests` → clean.

- [ ] **Step 11: Commit**

```bash
git add RUCKUS/ruckus_dashboard/infra/capability_registry.py RUCKUS/ruckus_dashboard/app.py RUCKUS/ruckus_dashboard/routes/connect.py RUCKUS/ruckus_dashboard/routes/modules.py tests/
git commit -m "refactor(caps): per-connection CapabilityRegistry, replace process-global available_ops"
```

---

### Task 4: Make `ParallelFetcher` per-task timeout real (audit #6)

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/infra/parallel_fetch.py` (`run`, ~lines 37-59)
- Test: `tests/unit/infra/test_parallel_fetch.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/infra/test_parallel_fetch.py`:

```python
import time
from ruckus_dashboard.infra.parallel_fetch import ParallelFetcher

def test_run_returns_promptly_despite_hung_task():
    f = ParallelFetcher(max_workers=2, timeout=0.2)
    def hang():
        time.sleep(5)        # exceeds timeout
        return "late"
    started = time.monotonic()
    results = f.run({"fast": lambda: "ok", "slow": hang})
    elapsed = time.monotonic() - started
    assert results["fast"].ok and results["fast"].value == "ok"
    assert results["slow"].timed_out is True
    assert elapsed < 2.0      # must NOT block ~5s on the straggler's shutdown(wait=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/infra/test_parallel_fetch.py::test_run_returns_promptly_despite_hung_task -v`
Expected: FAIL — `elapsed` is ~5s because the `with ThreadPoolExecutor()` block's `__exit__` calls `shutdown(wait=True)` and blocks on the hung task.

- [ ] **Step 3: Write minimal implementation**

In `RUCKUS/ruckus_dashboard/infra/parallel_fetch.py`, rewrite `run` to not use the `with` block and to shut down without waiting on stragglers:

```python
    def run(self, tasks: dict[str, Callable[[], Any]]) -> dict[str, TaskResult]:
        if not tasks:
            return {}
        results: dict[str, TaskResult] = {}
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
        try:
            future_to_id = {pool.submit(fn): tid for tid, fn in tasks.items()}
            done, not_done = concurrent.futures.wait(future_to_id, timeout=self.timeout)
            for future in done:
                tid = future_to_id[future]
                try:
                    results[tid] = TaskResult(ok=True, value=future.result())
                except BaseException as exc:  # noqa: BLE001
                    results[tid] = TaskResult(ok=False, error=exc)
            for future in not_done:
                tid = future_to_id[future]
                future.cancel()
                results[tid] = TaskResult(
                    ok=False,
                    error=concurrent.futures.TimeoutError(
                        f"task {tid!r} exceeded {self.timeout}s"
                    ),
                    timed_out=True,
                )
        finally:
            # Do not block on still-running stragglers (the old `with` __exit__ did).
            pool.shutdown(wait=False, cancel_futures=True)
        return results
```

(`cancel_futures=True` is available on Python 3.9+; the project targets 3.10+.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/infra/test_parallel_fetch.py -v`
Expected: PASS (new + existing parallel-fetch tests).

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/infra/parallel_fetch.py tests/unit/infra/test_parallel_fetch.py
git commit -m "fix(infra): ParallelFetcher returns within timeout, no straggler block"
```

---

### Task 5: Drill endpoints — error-disclosure parity (audit #7)

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/routes/modules.py` (`module_drill` ~148, `module_drill_tab` ~185)
- Test: `tests/integration/test_routes_new_ui.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_routes_new_ui.py` (reuse the file's existing authed-app + connection helpers; `_authed_app_with_conn` / `make_app` are already defined there):

```python
def test_drill_error_hidden_unless_debug(monkeypatch):
    app = _authed_app_with_conn()            # existing helper in this file
    # Force the drill fetcher to raise a controller error with a secret-ish body.
    from ruckus_dashboard.modules import MODULES
    spec = next(s for s in MODULES.values() if s.drill_fetcher is not None)
    def boom(ctx, entity_id):
        from ruckus_dashboard.clients.base import RuckusClientError
        raise RuckusClientError("upstream failed", 502, {"raw": "SECRET-INTERNAL-BODY"})
    monkeypatch.setattr(spec, "drill_fetcher", boom)
    client = app.test_client()
    with app.app_context():
        app.config["RUCKUS_SHOW_DEBUG"] = False
    r = client.get(f"/api/modules/{spec.slug}/some-id")
    body = r.get_json()
    assert "SECRET-INTERNAL-BODY" not in (body.get("error") or "")
```

(If `_authed_app_with_conn` is named differently, use the file's existing authed-client fixture; the assertion is the contract.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_routes_new_ui.py::test_drill_error_hidden_unless_debug -v`
Expected: FAIL — drill currently returns `str(exc)` (and appends raw under debug via none), leaking the body.

- [ ] **Step 3: Write minimal implementation**

In `RUCKUS/ruckus_dashboard/routes/modules.py`, both `module_drill` and `module_drill_tab` currently do:
```python
    except Exception as exc:
        return jsonify({"error": str(exc), "slug": slug, "entity_id": entity_id}), 502
```
Replace each `except` with a `RuckusClientError`-aware pair that reuses the existing `_upstream_message` (already defined in this file, ~line 28, which gates raw bodies behind `RUCKUS_SHOW_DEBUG`):
```python
    except RuckusClientError as exc:
        return jsonify({"error": _upstream_message(exc), "slug": slug, "entity_id": entity_id}), exc.status_code
    except Exception as exc:  # noqa: BLE001
        LOG.exception("drill '%s' crashed on %s", slug, entity_id)
        msg = str(exc) if current_app.config.get("RUCKUS_SHOW_DEBUG") else "Drill-in failed."
        return jsonify({"error": msg, "slug": slug, "entity_id": entity_id}), 502
```
(For `module_drill_tab`, keep the extra `"tab": tab_slug` key in the JSON.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_routes_new_ui.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/routes/modules.py tests/integration/test_routes_new_ui.py
git commit -m "fix(routes): gate raw drill error bodies behind RUCKUS_SHOW_DEBUG"
```

---

### Task 6: File-permission + missing-crypto hardening (audit #9, #10, #12)

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/auth/secrets.py` (`_write_protected_key`; `SecretsManager.__init__` warning)
- Modify: `RUCKUS/ruckus_dashboard/auth/profiles.py` (`_write`)
- Modify: `RUCKUS/ruckus_dashboard/notify/config.py` (`save_config`)
- Test: `tests/unit/auth/test_secrets.py`, `tests/unit/notify/test_notify.py`

- [ ] **Step 1: Write the failing test (notifications.json perms + warn)**

Add to `tests/unit/notify/test_notify.py`:

```python
import os, sys, stat
from ruckus_dashboard.notify.config import save_config, _path

def test_notifications_file_is_chmod_600(tmp_path):
    class _Sec:
        def encrypt(self, s): return "enc:" + s
    save_config(str(tmp_path), {"smtp": {"password": "pw"}}, _Sec())
    p = _path(str(tmp_path))
    assert p.exists()
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/notify/test_notify.py::test_notifications_file_is_chmod_600 -v`
Expected: FAIL on non-Windows — `notifications.json` is written without `chmod` (default umask perms).

- [ ] **Step 3: Implement notifications.json chmod**

In `RUCKUS/ruckus_dashboard/notify/config.py`, in `save_config`, after `path.write_text(...)` (~line 66) add:
```python
    try:
        path.chmod(0o600)
    except OSError:
        pass
```

- [ ] **Step 4: Implement chmod-before-replace in secrets + profiles**

In `RUCKUS/ruckus_dashboard/auth/secrets.py`, `_write_protected_key`, replace the `tmp.write_bytes(payload); tmp.replace(path)` sequence (~89-91) with a private-mode create so there is no world-readable window:
```python
        tmp = path.parent / (path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        tmp.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
```
Add `import os` at the top of `secrets.py` if not present. Apply the same `os.open(..., 0o600)` pattern to `profiles.py:_write` (it writes text — encode to bytes, or use `os.open` + `os.fdopen(fd, "w")`).

- [ ] **Step 5: Implement the missing-crypto warning**

In `RUCKUS/ruckus_dashboard/auth/secrets.py`, `SecretsManager.__init__`, when `Fernet is None` or the key could not be created, log once:
```python
        if self._fernet is None:
            LOG.warning("cryptography unavailable or key unwritable; secrets will NOT be persisted "
                        "(profile/SMTP passwords entered will be silently dropped).")
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/unit/auth/test_secrets.py tests/unit/notify/test_notify.py -v`
Expected: PASS (new + existing). On Windows the perm assertion is skipped.

- [ ] **Step 7: Commit**

```bash
git add RUCKUS/ruckus_dashboard/auth/secrets.py RUCKUS/ruckus_dashboard/auth/profiles.py RUCKUS/ruckus_dashboard/notify/config.py tests/
git commit -m "fix(secrets): 0600 on create, chmod notifications.json, warn when crypto unavailable"
```

---

### Task 7: DPAPI scope is configurable (audit #11)

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/auth/secrets.py` (scope constant → env-driven)
- Test: `tests/unit/auth/test_secrets.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/auth/test_secrets.py`:

```python
import importlib
from ruckus_dashboard.auth import secrets as secmod

def test_dpapi_scope_defaults_to_machine(monkeypatch):
    monkeypatch.delenv("RUCKUS_DPAPI_SCOPE", raising=False)
    assert secmod._dpapi_flags() == secmod._CRYPTPROTECT_LOCAL_MACHINE

def test_dpapi_scope_user_when_requested(monkeypatch):
    monkeypatch.setenv("RUCKUS_DPAPI_SCOPE", "user")
    assert secmod._dpapi_flags() == 0      # CURRENT_USER == no LOCAL_MACHINE flag
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/auth/test_secrets.py -k dpapi_scope -v`
Expected: FAIL — `_dpapi_flags` does not exist.

- [ ] **Step 3: Implement**

In `RUCKUS/ruckus_dashboard/auth/secrets.py`, add (near the `_CRYPTPROTECT_LOCAL_MACHINE` constant):
```python
import os

def _dpapi_flags() -> int:
    # Default LOCAL_MACHINE (back-compat: any local user/service can decrypt).
    # Set RUCKUS_DPAPI_SCOPE=user to scope secrets to the current user account.
    scope = (os.getenv("RUCKUS_DPAPI_SCOPE", "machine") or "machine").strip().lower()
    return 0 if scope == "user" else _CRYPTPROTECT_LOCAL_MACHINE
```
Then in `_dpapi_protect` and `_dpapi_unprotect`, replace the hard-coded `_CRYPTPROTECT_LOCAL_MACHINE` argument passed to `CryptProtectData`/`CryptUnprotectData` with `_dpapi_flags()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/auth/test_secrets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/auth/secrets.py tests/unit/auth/test_secrets.py
git commit -m "feat(secrets): RUCKUS_DPAPI_SCOPE to scope DPAPI to current user"
```

---

### Task 8: `save_config` deep section-merge (audit #13)

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/notify/config.py` (`save_config` / `_merged`)
- Test: `tests/unit/notify/test_notify.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/notify/test_notify.py`:

```python
from ruckus_dashboard.notify.config import save_config, load_config

class _Sec:
    def encrypt(self, s): return "enc:" + s
    def decrypt(self, s): return s

def test_partial_post_preserves_other_subkeys(tmp_path):
    save_config(str(tmp_path), {"report": {"enabled": True, "recipients": ["a@x"], "time": "06:00"}}, _Sec())
    # A later partial POST that only flips enabled must NOT drop recipients/time.
    save_config(str(tmp_path), {"report": {"enabled": False}}, _Sec())
    cfg = load_config(str(tmp_path))
    assert cfg["report"]["enabled"] is False
    assert cfg["report"]["recipients"] == ["a@x"]
    assert cfg["report"]["time"] == "06:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/notify/test_notify.py::test_partial_post_preserves_other_subkeys -v`
Expected: FAIL — the current `{**current, **incoming-dicts}` replaces the whole `report` section, dropping `recipients`/`time`.

- [ ] **Step 3: Implement deep merge**

In `RUCKUS/ruckus_dashboard/notify/config.py`, change `save_config` so each incoming section is merged key-wise over the current section instead of replacing it. Replace the `merged = _merged({**current, **{...}})` line with:
```python
    sections = {}
    for k, v in current.items():
        sections[k] = dict(v) if isinstance(v, dict) else v
    for k, v in incoming.items():
        if isinstance(v, dict) and isinstance(sections.get(k), dict):
            sections[k].update(v)
        elif isinstance(v, dict):
            sections[k] = dict(v)
    merged = _merged(sections)
```
Leave the password-handling block (`pw = (incoming.get("smtp") or {}).get("password")` …) unchanged — it runs after this and still wins for the encrypted field.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/notify/test_notify.py -v`
Expected: PASS.

- [ ] **Step 5: Final full run + commit**

```bash
pytest -q && ruff check RUCKUS/ruckus_dashboard tests
git add RUCKUS/ruckus_dashboard/notify/config.py tests/unit/notify/test_notify.py
git commit -m "fix(notify): deep-merge config sections so partial saves keep other keys"
```

---

## Self-Review

**Spec coverage (audit findings → tasks):** #1→T1, #3→T2, #2→T3, #6→T4, #7→T5, #9/#10/#12→T6, #11→T7, #13→T8. #4/#5/#14 explicitly deferred to SP2 (notify-state rewrite); #15 deferred (YAGNI). All 15 accounted for.

**Placeholder scan:** every code/test step shows real code and a runnable command with expected output. The two soft spots are by-design: Task 3 Step 8/9 use `grep` to catch any `available_ops`/test references beyond the cited lines (the replacement pattern is shown), and Task 5's test reuses whatever authed-client helper the file already defines (contract asserted). No "TBD"/"add error handling"/"similar to" placeholders.

**Type/name consistency:** `CapabilityRegistry.set_for/get_for/clear` are used identically in T3 Steps 3, 5, 6, 7; `require_allowlist_for_bind`/`is_loopback` consistent T2 Steps 3/5; `_dpapi_flags` consistent T7 Steps 1/3; `_upstream_message` is an existing symbol reused in T5.

**Risk note:** Task 3 is the largest (multi-file). It is sequenced first among the structural changes and ends with a full `pytest -q` + `ruff` gate before later tasks build on it.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-30-sp7-audit-fixes.md`. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, two-stage review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints.

Which approach?
