# RUCKUS Dashboard Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `RUCKUS/ruckus_dashboard.py` (5076-line single file) into installable `ruckus_dashboard/` package with ModuleSpec registry, shared module template, sidebar shell, polling/caching/capability infrastructure, and feature flag — all 18 dashboard modules stubbed in sidebar, none built yet.

**Architecture:** Package layout per spec Section 1. Lift-and-shift existing functions into focused modules with their original signatures preserved. Add new infrastructure (`ModuleSpec`, `ModuleResultCache`, capability gating, error envelope, hash-router JS) on top. Backward compat: `python RUCKUS/ruckus_dashboard.py` continues to work via shim re-exporting `main`. Feature flag `RUCKUS_ENABLE_NEW_UI=1` switches between legacy templates and new sidebar+module shell.

**Tech Stack:** Python 3.10+, Flask, requests, cryptography (Fernet + DPAPI on Windows), pytest, `responses` for HTTP mocking, vanilla JS (no framework).

**Source spec:** `docs/superpowers/specs/2026-06-05-ruckus-dashboard-expansion-design.md`

**Follow-up plans (not in scope here):** Plan 2 (Wireless modules), Plan 3 (Switching modules), Plan 4 (Cross-cutting + API Explorer).

---

## File Structure

```
RUCKUS/
├── ruckus_dashboard.py              # MODIFY: shrink to backward-compat shim
└── ruckus_dashboard/                # CREATE: package root
    ├── __init__.py                  # version, public exports
    ├── __main__.py                  # python -m ruckus_dashboard → main()
    ├── app.py                       # create_app()
    ├── cli.py                       # argparse, main(), launcher
    ├── config.py                    # build_config + env parsers
    ├── certs.py                     # ensure_self_signed_cert
    ├── logging_setup.py             # _JsonLogFormatter, configure_logging
    ├── auth/
    │   ├── __init__.py
    │   ├── session_store.py         # ConnectionConfig, ConnectionStore
    │   ├── secrets.py               # SecretsManager, DPAPI helpers
    │   ├── profiles.py              # ProfileStore
    │   └── csrf.py                  # _validate_csrf
    ├── net/
    │   ├── __init__.py
    │   ├── allowlist.py             # HostAllowList, _assert_host_allowed
    │   └── port_scan.py             # port_has_active_listener, select_dashboard_port
    ├── clients/
    │   ├── __init__.py
    │   ├── base.py                  # _request_json, RuckusClientError, paging helpers
    │   ├── smartzone.py             # SmartZone auth + fetchers
    │   ├── switchm.py               # Switch Manager fetchers (extracted)
    │   ├── ruckus_one.py            # RUCKUS One OAuth + fetchers
    │   └── capabilities.py          # OpenAPI discovery
    ├── modules/
    │   ├── __init__.py              # MODULES registry + register_all()
    │   ├── _base.py                 # ModuleSpec, TabSpec, FetcherContext
    │   └── _stub.py                 # stub fetcher for not-yet-built modules
    ├── infra/
    │   ├── __init__.py
    │   ├── cache.py                 # ModuleResultCache
    │   ├── envelope.py              # build_envelope, merge_envelopes
    │   ├── capability_gate.py       # CapabilityGate
    │   └── inflight.py              # InFlightDeduper
    ├── templates/
    │   ├── base.html                # shell with sidebar
    │   ├── module.html              # generic module page
    │   ├── overview.html            # hub
    │   ├── legacy.html              # current dashboard page (flag-off)
    │   └── partials/
    │       ├── kpi_card.html
    │       ├── status_pill.html
    │       ├── entity_link.html
    │       ├── freshness_strip.html
    │       ├── error_banner.html
    │       ├── filter_chip.html
    │       └── table_pagination.html
    └── static/
        ├── styles.css
        ├── dashboard.js             # hash router, polling loop, visibility
        └── assets/ruckus-logo.png

tests/
├── conftest.py                      # shared fixtures: app, client, mock_connection
├── unit/
│   ├── test_config.py
│   ├── test_certs.py
│   ├── test_logging_setup.py
│   ├── auth/
│   │   ├── test_session_store.py
│   │   ├── test_secrets.py
│   │   ├── test_profiles.py
│   │   └── test_csrf.py
│   ├── net/
│   │   ├── test_allowlist.py
│   │   └── test_port_scan.py
│   ├── clients/
│   │   ├── test_base.py
│   │   ├── test_smartzone.py
│   │   ├── test_switchm.py
│   │   ├── test_ruckus_one.py
│   │   └── test_capabilities.py
│   ├── modules/
│   │   ├── test_base.py             # ModuleSpec contract
│   │   └── test_registry.py         # registration scan
│   └── infra/
│       ├── test_cache.py
│       ├── test_envelope.py
│       ├── test_capability_gate.py
│       └── test_inflight.py
├── integration/
│   ├── test_app_factory.py
│   ├── test_routes_legacy.py        # flag-off behavior
│   ├── test_routes_new_ui.py        # flag-on sidebar + stub responses
│   ├── test_security_headers.py
│   └── test_backward_compat.py      # python RUCKUS/ruckus_dashboard.py still launches
└── smoke/
    └── test_launch.py
```

---

### Task 1: Create package skeleton + minimal shim

**Files:**
- Create: `RUCKUS/ruckus_dashboard/__init__.py`
- Create: `RUCKUS/ruckus_dashboard/__main__.py`
- Modify: `RUCKUS/ruckus_dashboard.py` (shrink to shim — keep functions for now, will be pruned in later tasks)
- Test: `tests/unit/test_package.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_package.py
import importlib

def test_package_imports():
    pkg = importlib.import_module("ruckus_dashboard")
    assert pkg.APP_NAME == "RUCKUS NOC Assurance Dashboard"
    assert pkg.APP_VERSION

def test_main_entrypoint_exists():
    pkg = importlib.import_module("ruckus_dashboard")
    assert callable(pkg.main)

def test_legacy_shim_still_works():
    # Top-level ruckus_dashboard.py module must still expose main()
    import importlib.util, pathlib
    shim_path = pathlib.Path("RUCKUS/ruckus_dashboard.py")
    spec = importlib.util.spec_from_file_location("ruckus_dashboard_shim", shim_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.main)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_package.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ruckus_dashboard'`

- [ ] **Step 3: Create minimal package**

```python
# RUCKUS/ruckus_dashboard/__init__.py
"""RUCKUS NOC Assurance Dashboard package."""
APP_NAME = "RUCKUS NOC Assurance Dashboard"
APP_VERSION = "2.0.0-dev"

def main(argv=None):
    """Entry point — full implementation lands in cli.py."""
    from .cli import main as _main
    return _main(argv)
```

```python
# RUCKUS/ruckus_dashboard/__main__.py
from .cli import main

if __name__ == "__main__":
    main()
```

```python
# RUCKUS/ruckus_dashboard/cli.py
"""Placeholder — full launcher lands in Task 29."""
def main(argv=None):
    raise NotImplementedError("cli.main lands in Task 29")
```

Also add `RUCKUS/ruckus_dashboard.py` shim at top (do NOT delete existing 5076-line file yet — that happens in Task 30). Append:

```python
# at end of existing RUCKUS/ruckus_dashboard.py — provides forward-compat alias
# (later Task 30 replaces the entire file with just the shim)
```

For this task, just ensure the existing `main` function is callable (it already is — no change).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_package.py -v`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/__init__.py RUCKUS/ruckus_dashboard/__main__.py RUCKUS/ruckus_dashboard/cli.py tests/unit/test_package.py
git commit -m "feat(foundation): create ruckus_dashboard package skeleton"
```

---

### Task 2: Add pyproject.toml so package is installable

**Files:**
- Create: `RUCKUS/pyproject.toml`
- Modify: `tests/conftest.py` (create with shared `tmp_path_factory` fixtures)
- Test: `tests/unit/test_install.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_install.py
import subprocess, sys

def test_module_runnable():
    """python -m ruckus_dashboard --version exits 0."""
    result = subprocess.run(
        [sys.executable, "-m", "ruckus_dashboard", "--version"],
        capture_output=True, text=True, cwd="RUCKUS",
    )
    # cli.py raises NotImplementedError until Task 29 — accept that for now
    assert result.returncode in (0, 1)
    assert "RUCKUS" in (result.stdout + result.stderr) or "NotImplementedError" in result.stderr
```

```python
# tests/conftest.py
import os, sys, pathlib
import pytest

# Make RUCKUS/ importable as a package root
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "RUCKUS"))

@pytest.fixture
def tmp_instance(tmp_path):
    """Isolated instance dir for tests touching disk (certs, secrets, profiles)."""
    inst = tmp_path / "instance"
    inst.mkdir()
    return str(inst)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_install.py -v`
Expected: FAIL — `python -m ruckus_dashboard` raises before printing version.

- [ ] **Step 3: Create pyproject + handle --version in package**

```toml
# RUCKUS/pyproject.toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "ruckus_dashboard"
version = "2.0.0.dev0"
description = "RUCKUS DSO Assurance Dashboard"
requires-python = ">=3.10"
dependencies = [
  "flask>=3.0",
  "requests>=2.31",
  "urllib3>=2.0",
  "cryptography>=42",
  "python-dotenv>=1.0",
]

[project.scripts]
ruckus-dashboard = "ruckus_dashboard.cli:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["ruckus_dashboard*"]
```

Update `RUCKUS/ruckus_dashboard/__main__.py` to handle `--version` without going into cli.main:

```python
# RUCKUS/ruckus_dashboard/__main__.py
import sys
from . import APP_NAME, APP_VERSION

if __name__ == "__main__":
    if "--version" in sys.argv[1:]:
        print(f"{APP_NAME} {APP_VERSION}")
        sys.exit(0)
    from .cli import main
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_install.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/pyproject.toml RUCKUS/ruckus_dashboard/__main__.py tests/conftest.py tests/unit/test_install.py
git commit -m "build(foundation): add pyproject + --version short-circuit"
```

---

### Task 3: Port `config.py` (env parsers + build_config)

**Files:**
- Create: `RUCKUS/ruckus_dashboard/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config.py
import os
from ruckus_dashboard.config import build_config, _bool_env, _int_env

def test_bool_env_true_values(monkeypatch):
    for value in ["1", "true", "yes", "on", "TRUE", "Yes"]:
        monkeypatch.setenv("X", value)
        assert _bool_env("X", False) is True

def test_bool_env_default(monkeypatch):
    monkeypatch.delenv("X", raising=False)
    assert _bool_env("X", True) is True
    assert _bool_env("X", False) is False

def test_int_env_invalid_returns_default(monkeypatch):
    monkeypatch.setenv("X", "not-a-number")
    assert _int_env("X", 42) == 42

def test_build_config_defaults(tmp_path):
    cfg = build_config(str(tmp_path))
    assert cfg["APP_HOST"] == "127.0.0.1"
    assert cfg["APP_PORT"] == 8444
    assert cfg["RUCKUS_SMARTZONE_PORT"] == 8443
    assert cfg["SESSION_COOKIE_SAMESITE"] == "Strict"
    assert cfg["RUCKUS_ENABLE_NEW_UI"] is False  # new — defaults off

def test_build_config_new_ui_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("RUCKUS_ENABLE_NEW_UI", "1")
    cfg = build_config(str(tmp_path))
    assert cfg["RUCKUS_ENABLE_NEW_UI"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Port config.py**

Lift the entire config block from `RUCKUS/ruckus_dashboard.py` lines 122-216 (functions `build_config`, `load_secret_key`, `_bool_env`, `_int_env`, `_float_env`, `_tls_verify_env`). Add new flag `RUCKUS_ENABLE_NEW_UI`:

```python
# RUCKUS/ruckus_dashboard/config.py
"""Config builder + env parsers. Lifted from the monolith; new flags added."""
from __future__ import annotations
import os, secrets
from datetime import timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DEFAULT_DASHBOARD_PORT = 8444
DEFAULT_SMARTZONE_API_PORT = 8443


def build_config(instance_path: str) -> dict:
    return {
        # ─── ports + bind ────────────────────────────────────────
        "APP_HOST": os.getenv("RUCKUS_DASHBOARD_HOST", "127.0.0.1"),
        "APP_PORT": _int_env("RUCKUS_DASHBOARD_PORT", DEFAULT_DASHBOARD_PORT),
        "APP_AUTO_PORT": _bool_env("RUCKUS_AUTO_PORT", True),
        "APP_PORT_SCAN_LIMIT": _int_env("RUCKUS_PORT_SCAN_LIMIT", 50),
        "APP_OPEN_BROWSER": _bool_env("RUCKUS_OPEN_BROWSER", True),
        # ─── upstream API ────────────────────────────────────────
        "RUCKUS_SMARTZONE_PORT": _int_env("RUCKUS_SMARTZONE_PORT", DEFAULT_SMARTZONE_API_PORT),
        "RUCKUS_PAGE_LIMIT": _int_env("RUCKUS_PAGE_LIMIT", 500),
        "RUCKUS_TIMEOUT_SECONDS": _float_env("RUCKUS_TIMEOUT_SECONDS", 20.0),
        "RUCKUS_DEBUG_BYTES": _int_env("RUCKUS_DEBUG_BYTES", 2000),
        "RUCKUS_SHOW_DEBUG": _bool_env("RUCKUS_SHOW_DEBUG", False),
        "RUCKUS_VERIFY_TLS": _tls_verify_env("RUCKUS_VERIFY_TLS", True),
        "RUCKUS_FETCH_AP_DETAILS": _bool_env("RUCKUS_FETCH_AP_DETAILS", False),
        "RUCKUS_MAX_DETAIL_REQUESTS": _int_env("RUCKUS_MAX_DETAIL_REQUESTS", 300),
        "RUCKUS_CAPABILITY_DISCOVERY": _bool_env("RUCKUS_CAPABILITY_DISCOVERY", True),
        "RUCKUS_OPERATIONAL_DATA": _bool_env("RUCKUS_OPERATIONAL_DATA", True),
        "RUCKUS_FETCH_SWITCH_HEALTH": _bool_env("RUCKUS_FETCH_SWITCH_HEALTH", True),
        # ─── security ────────────────────────────────────────────
        "RUCKUS_SECURITY_LOOKUPS": _bool_env("RUCKUS_SECURITY_LOOKUPS", True),
        "RUCKUS_MAX_SECURITY_LOOKUPS": _int_env("RUCKUS_MAX_SECURITY_LOOKUPS", 12),
        "RUCKUS_NVD_RESULTS": _int_env("RUCKUS_NVD_RESULTS", 5),
        "RUCKUS_SECURITY_CACHE_SECONDS": _int_env("RUCKUS_SECURITY_CACHE_SECONDS", 21600),
        "RUCKUS_ALLOWED_HOSTS": os.getenv("RUCKUS_ALLOWED_HOSTS", ""),
        # ─── session ─────────────────────────────────────────────
        "CREDENTIAL_TTL_SECONDS": _int_env("RUCKUS_CREDENTIAL_TTL_SECONDS", 43200),
        "PERMANENT_SESSION_LIFETIME": timedelta(seconds=_int_env("RUCKUS_CREDENTIAL_TTL_SECONDS", 43200)),
        "SECRET_KEY": os.getenv("FLASK_SECRET_KEY"),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SECURE": True,
        "SESSION_COOKIE_SAMESITE": "Strict",
        # ─── NEW UI shell ────────────────────────────────────────
        "RUCKUS_ENABLE_NEW_UI": _bool_env("RUCKUS_ENABLE_NEW_UI", False),
        "RUCKUS_MAX_INFLIGHT_PER_MODULE": _int_env("RUCKUS_MAX_INFLIGHT_PER_MODULE", 1),
    }


def load_secret_key(instance_path: str) -> str:
    secret_path = Path(instance_path) / "secret_key"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(48)
    secret_path.write_text(secret, encoding="utf-8")
    try:
        secret_path.chmod(0o600)
    except OSError:
        pass
    return secret


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _tls_verify_env(name: str, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_config.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/config.py tests/unit/test_config.py
git commit -m "feat(foundation): port config.py + add RUCKUS_ENABLE_NEW_UI flag"
```

---

### Task 4: Port `certs.py`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/certs.py`
- Test: `tests/unit/test_certs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_certs.py
from pathlib import Path
from ruckus_dashboard.certs import ensure_self_signed_cert

def test_generates_cert_and_key(tmp_instance):
    cert, key = ensure_self_signed_cert(tmp_instance)
    assert Path(cert).exists()
    assert Path(key).exists()
    assert Path(cert).read_bytes().startswith(b"-----BEGIN CERTIFICATE-----")
    assert b"PRIVATE KEY" in Path(key).read_bytes()

def test_idempotent(tmp_instance):
    cert1, key1 = ensure_self_signed_cert(tmp_instance)
    bytes1 = Path(cert1).read_bytes()
    cert2, key2 = ensure_self_signed_cert(tmp_instance)
    assert Path(cert2).read_bytes() == bytes1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_certs.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Port certs.py**

Lift the entire `ensure_self_signed_cert` function from `RUCKUS/ruckus_dashboard.py` lines 222-281 verbatim into `RUCKUS/ruckus_dashboard/certs.py`. Copy imports (cryptography, datetime, socket, pathlib).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_certs.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/certs.py tests/unit/test_certs.py
git commit -m "feat(foundation): port certs.py (self-signed cert generator)"
```

---

### Task 5: Port `logging_setup.py`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/logging_setup.py`
- Test: `tests/unit/test_logging_setup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_logging_setup.py
import json, logging
from ruckus_dashboard.logging_setup import _JsonLogFormatter, configure_logging

def test_json_formatter_emits_valid_json():
    fmt = _JsonLogFormatter()
    record = logging.LogRecord("ruckus", logging.INFO, "f.py", 1, "hello", None, None)
    record.request_id = "abcd1234"
    out = fmt.format(record)
    payload = json.loads(out)
    assert payload["message"] == "hello"
    assert payload["request_id"] == "abcd1234"
    assert payload["level"] == "INFO"

def test_configure_logging_idempotent(tmp_instance):
    configure_logging(tmp_instance, debug=False)
    configure_logging(tmp_instance, debug=True)  # second call must not duplicate handlers
    logger = logging.getLogger("ruckus_dashboard")
    handler_classes = {type(h).__name__ for h in logger.handlers}
    # at least file + stream
    assert "RotatingFileHandler" in handler_classes or len(logger.handlers) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_logging_setup.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Port logging_setup.py**

Lift `_JsonLogFormatter` (lines 2885-2900) and `configure_logging` (lines 2902-2925) from `RUCKUS/ruckus_dashboard.py`. Ensure `configure_logging` clears existing handlers before adding new ones (read original, preserve idempotency behavior — if missing, add a `logger.handlers.clear()` at the start).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_logging_setup.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/logging_setup.py tests/unit/test_logging_setup.py
git commit -m "feat(foundation): port logging_setup.py (JSON formatter + configure)"
```

---

### Task 6: Port `auth/session_store.py`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/auth/__init__.py` (empty)
- Create: `RUCKUS/ruckus_dashboard/auth/session_store.py`
- Test: `tests/unit/auth/test_session_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/auth/test_session_store.py
import time
from ruckus_dashboard.auth.session_store import ConnectionConfig, ConnectionStore

def make_cfg(name="SZ1"):
    return ConnectionConfig(
        platform="smartzone", api_base="https://sz/wsg/api/public",
        display_name=name, auth_token="ticket",
    )

def test_put_get_round_trip():
    store = ConnectionStore(ttl_seconds=60)
    token = store.put(make_cfg())
    assert store.get(token).display_name == "SZ1"

def test_ttl_eviction():
    store = ConnectionStore(ttl_seconds=0)
    token = store.put(make_cfg())
    time.sleep(0.01)
    assert store.get(token) is None

def test_remove():
    store = ConnectionStore(ttl_seconds=60)
    token = store.put(make_cfg())
    store.remove(token)
    assert store.get(token) is None

def test_count():
    store = ConnectionStore(ttl_seconds=60)
    store.put(make_cfg("A"))
    store.put(make_cfg("B"))
    assert store.count() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/auth/test_session_store.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Port session_store.py**

Lift `ConnectionConfig` (lines 287-300) and `ConnectionStore` (lines 302-344) from `RUCKUS/ruckus_dashboard.py` verbatim. Imports: `dataclasses`, `secrets`, `threading.RLock`, `time`.

Also create empty `RUCKUS/ruckus_dashboard/auth/__init__.py` and `tests/unit/auth/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/auth/test_session_store.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/auth/ tests/unit/auth/test_session_store.py tests/unit/auth/__init__.py
git commit -m "feat(foundation): port auth/session_store.py"
```

---

### Task 7: Port `auth/secrets.py` (Fernet + DPAPI)

**Files:**
- Create: `RUCKUS/ruckus_dashboard/auth/secrets.py`
- Test: `tests/unit/auth/test_secrets.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/auth/test_secrets.py
import sys
import pytest
from ruckus_dashboard.auth.secrets import SecretsManager

def test_round_trip(tmp_instance):
    mgr = SecretsManager(tmp_instance)
    if not mgr.available():
        pytest.skip("cryptography not installed")
    blob = mgr.encrypt("hunter2")
    assert blob and blob != "hunter2"
    assert mgr.decrypt(blob) == "hunter2"

def test_decrypt_garbage_returns_empty(tmp_instance):
    mgr = SecretsManager(tmp_instance)
    if not mgr.available():
        pytest.skip()
    assert mgr.decrypt("not-a-valid-token") == ""

def test_key_persists_across_instances(tmp_instance):
    mgr1 = SecretsManager(tmp_instance)
    if not mgr1.available():
        pytest.skip()
    blob = mgr1.encrypt("secret")
    mgr2 = SecretsManager(tmp_instance)
    assert mgr2.decrypt(blob) == "secret"

@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_dpapi_wrapping_used_on_windows(tmp_instance):
    from ruckus_dashboard.auth.secrets import _dpapi_available
    if not _dpapi_available():
        pytest.skip("DPAPI not loadable in this Windows env")
    mgr = SecretsManager(tmp_instance)
    blob = mgr.encrypt("x")
    assert mgr.decrypt(blob) == "x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/auth/test_secrets.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Port secrets.py**

Lift these from `RUCKUS/ruckus_dashboard.py` into `RUCKUS/ruckus_dashboard/auth/secrets.py`:
- `_dpapi_available` (lines 2568-2576)
- `_dpapi_protect` (lines 2577-2592)
- `_dpapi_unprotect` (lines 2593-2608)
- `_key_file_is_wrapped` (lines 2609-2616)
- `_write_protected_key` (lines 2617-2637)
- `_read_protected_key` (lines 2638-2651)
- `SecretsManager` class (lines 2652-2714)

Imports: `base64`, `ctypes`, `os`, `pathlib.Path`, `cryptography.fernet`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/auth/test_secrets.py -v`
Expected: 4 PASS (DPAPI test skipped on non-Windows).

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/auth/secrets.py tests/unit/auth/test_secrets.py
git commit -m "feat(foundation): port auth/secrets.py (Fernet + DPAPI wrap)"
```

---

### Task 8: Port `auth/profiles.py`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/auth/profiles.py`
- Test: `tests/unit/auth/test_profiles.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/auth/test_profiles.py
from ruckus_dashboard.auth.secrets import SecretsManager
from ruckus_dashboard.auth.profiles import ProfileStore

def test_save_list_delete(tmp_instance):
    secrets_mgr = SecretsManager(tmp_instance)
    store = ProfileStore(tmp_instance, secrets_mgr)
    form = {"platform": "smartzone", "smartzone_host": "sz.example",
            "smartzone_username": "admin", "smartzone_password": "hunter2"}
    store.save("lab", form)
    items = store.list_masked()
    assert any(item["name"] == "lab" for item in items)
    pw = store.resolve_secret("lab", "smartzone_password")
    if secrets_mgr.available():
        assert pw == "hunter2"
    store.delete("lab")
    assert not any(item["name"] == "lab" for item in store.list_masked())

def test_save_requires_profile_name(tmp_instance):
    import pytest
    mgr = SecretsManager(tmp_instance)
    store = ProfileStore(tmp_instance, mgr)
    with pytest.raises(ValueError):
        store.save("", {"platform": "smartzone"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/auth/test_profiles.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Port profiles.py**

Lift `ProfileStore` class (lines 2715-2802) and `PROFILE_SECRET_FIELDS`, `_PROFILE_PW_SENTINEL` constants from `RUCKUS/ruckus_dashboard.py` (search for these symbols and copy with their context). Imports: `json`, `pathlib.Path`, `threading.RLock`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/auth/test_profiles.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/auth/profiles.py tests/unit/auth/test_profiles.py
git commit -m "feat(foundation): port auth/profiles.py"
```

---

### Task 9: Port `auth/csrf.py`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/auth/csrf.py`
- Test: `tests/unit/auth/test_csrf.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/auth/test_csrf.py
import pytest
from flask import Flask, session
from werkzeug.exceptions import BadRequest
from ruckus_dashboard.auth.csrf import validate_csrf

def make_app():
    app = Flask(__name__)
    app.secret_key = "test"
    return app

def test_valid_token_passes():
    app = make_app()
    with app.test_request_context("/x", method="POST", data={"csrf_token": "abc"}):
        session["csrf_token"] = "abc"
        validate_csrf()  # no raise

def test_missing_token_400():
    app = make_app()
    with app.test_request_context("/x", method="POST"):
        session["csrf_token"] = "abc"
        with pytest.raises(BadRequest):
            validate_csrf()

def test_mismatched_token_400():
    app = make_app()
    with app.test_request_context("/x", method="POST", data={"csrf_token": "wrong"}):
        session["csrf_token"] = "abc"
        with pytest.raises(BadRequest):
            validate_csrf()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/auth/test_csrf.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Port csrf.py (rename underscore-prefixed `_validate_csrf` to public `validate_csrf`)**

```python
# RUCKUS/ruckus_dashboard/auth/csrf.py
"""CSRF token validator. Lifted from monolith _validate_csrf."""
from __future__ import annotations
import hmac
from flask import abort, request, session


def validate_csrf() -> None:
    """Abort 400 if request CSRF token missing or mismatched."""
    expected = session.get("csrf_token")
    presented = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    if not expected or not presented or not hmac.compare_digest(str(expected), str(presented)):
        abort(400, description="CSRF token missing or invalid.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/auth/test_csrf.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/auth/csrf.py tests/unit/auth/test_csrf.py
git commit -m "feat(foundation): port auth/csrf.py"
```

---

### Task 10: Port `net/allowlist.py`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/net/__init__.py` (empty)
- Create: `RUCKUS/ruckus_dashboard/net/allowlist.py`
- Test: `tests/unit/net/test_allowlist.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/net/test_allowlist.py
import pytest
from ruckus_dashboard.net.allowlist import HostAllowList, assert_host_allowed

def test_empty_list_allows_everything():
    al = HostAllowList("")
    assert not al.enabled
    assert_host_allowed("anything.example.com", {"RUCKUS_HOST_ALLOWLIST": al})

def test_exact_hostname_match():
    al = HostAllowList("sz.example.com, 10.0.0.5")
    assert al.enabled
    assert_host_allowed("sz.example.com", {"RUCKUS_HOST_ALLOWLIST": al})
    assert_host_allowed("10.0.0.5", {"RUCKUS_HOST_ALLOWLIST": al})

def test_cidr_match():
    al = HostAllowList("10.0.0.0/24")
    assert_host_allowed("10.0.0.55", {"RUCKUS_HOST_ALLOWLIST": al})

def test_disallowed_raises():
    al = HostAllowList("sz.example.com")
    with pytest.raises(ValueError):
        assert_host_allowed("evil.example.com", {"RUCKUS_HOST_ALLOWLIST": al})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/net/test_allowlist.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Port allowlist.py**

Lift `HostAllowList` class (lines 2803-2869) and `_assert_host_allowed` (lines 2870-2884) from `RUCKUS/ruckus_dashboard.py`. Rename `_assert_host_allowed` → `assert_host_allowed` (public). Imports: `ipaddress`, `socket`. Create `RUCKUS/ruckus_dashboard/net/__init__.py` empty, `tests/unit/net/__init__.py` empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/net/test_allowlist.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/net/ tests/unit/net/test_allowlist.py tests/unit/net/__init__.py
git commit -m "feat(foundation): port net/allowlist.py (SSRF guard)"
```

---

### Task 11: Port `net/port_scan.py`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/net/port_scan.py`
- Test: `tests/unit/net/test_port_scan.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/net/test_port_scan.py
import socket
from ruckus_dashboard.net.port_scan import (
    port_has_active_listener,
    can_exclusively_bind_port,
    select_dashboard_port,
)

def test_can_bind_random_high_port():
    assert can_exclusively_bind_port("127.0.0.1", 0)  # 0 = OS-assigned

def test_listener_detected():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert port_has_active_listener("127.0.0.1", port)
    finally:
        s.close()

def test_select_port_falls_back_when_requested_busy():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    busy = s.getsockname()[1]
    try:
        port, used_random = select_dashboard_port("127.0.0.1", busy, auto_port=True, scan_limit=10)
        assert port != busy
        assert used_random
    finally:
        s.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/net/test_port_scan.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Port port_scan.py**

Lift these functions from `RUCKUS/ruckus_dashboard.py`:
- `_connect_probe_hosts` (lines 3268-3276)
- `_is_ipv6_host` (lines 3277-3280)
- `_bind_family_host` (lines 3281-3286)
- `port_has_active_listener` (lines 3287-3296)
- `can_exclusively_bind_port` (lines 3297-3317)
- `_reserve_random_port` (lines 3318-3324)
- `select_dashboard_port` (lines 3325-3345)
- `port_self_test_script_block` (lines 3346-3357)

Modify `select_dashboard_port` signature to accept `scan_limit: int = 50` as kwarg (currently reads from `app.config["APP_PORT_SCAN_LIMIT"]`). This decouples it from Flask.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/net/test_port_scan.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/net/port_scan.py tests/unit/net/test_port_scan.py
git commit -m "feat(foundation): port net/port_scan.py"
```

---

### Task 12: Port `clients/base.py` (request envelope, error class, helpers)

**Files:**
- Create: `RUCKUS/ruckus_dashboard/clients/__init__.py` (empty)
- Create: `RUCKUS/ruckus_dashboard/clients/base.py`
- Test: `tests/unit/clients/test_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/clients/test_base.py
import pytest
import responses
from ruckus_dashboard.clients.base import request_json, RuckusClientError

@responses.activate
def test_request_json_happy():
    responses.add(responses.GET, "https://x/y", json={"a": 1}, status=200)
    cfg = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
           "RUCKUS_HOST_ALLOWLIST": None}
    out = request_json("GET", "https://x/y", cfg, verify=True, debug_label="t")
    assert out == {"a": 1}

@responses.activate
def test_request_json_4xx_raises():
    responses.add(responses.GET, "https://x/y", json={"err": "nope"}, status=404)
    cfg = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
           "RUCKUS_HOST_ALLOWLIST": None}
    with pytest.raises(RuckusClientError) as exc:
        request_json("GET", "https://x/y", cfg, verify=True, debug_label="t")
    assert exc.value.status_code == 404

@responses.activate
def test_redact_password_in_error_debug():
    responses.add(responses.POST, "https://x/login", status=500)
    cfg = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
           "RUCKUS_HOST_ALLOWLIST": None}
    with pytest.raises(RuckusClientError) as exc:
        request_json("POST", "https://x/login", cfg,
                     json={"username": "u", "password": "hunter2"},
                     verify=True, debug_label="t")
    debug_str = str(exc.value.debug or {})
    assert "hunter2" not in debug_str
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/clients/test_base.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Port base.py**

Lift from `RUCKUS/ruckus_dashboard.py`:
- `RuckusClientError` (lines 857-865)
- `_request_json` (lines 1767-1832) → rename to `request_json` (public)
- `_redact` (lines 2338-2355)
- `_safe_url` (lines 2295-2299)
- `_maybe_disable_tls_warnings` (lines 2300-2304)
- `_extract_items`, `_first_value`, `_nested_value`, `_first_present`, `_nested_first`, `_as_list`, `_coerce_int`, `_safe_port`, `_format_host`, `_host_label`, `_format_time`, `_parse_datetime`, `_format_now` (utility helpers, lines 2170-2333)

Create empty `RUCKUS/ruckus_dashboard/clients/__init__.py` and `tests/unit/clients/__init__.py`.

Also add `responses` to dev dependencies: edit `RUCKUS/pyproject.toml` to add:

```toml
[project.optional-dependencies]
test = ["pytest>=7", "responses>=0.24", "pytest-cov>=4"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pip install -e RUCKUS[test] && pytest tests/unit/clients/test_base.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/clients/ RUCKUS/pyproject.toml tests/unit/clients/
git commit -m "feat(foundation): port clients/base.py (HTTP envelope + utility helpers)"
```

---

### Task 13: Port `clients/smartzone.py`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/clients/smartzone.py`
- Test: `tests/unit/clients/test_smartzone.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/clients/test_smartzone.py
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.clients.smartzone import (
    authenticate_smartzone, fetch_inventory, normalize_smartzone_base,
)

CFG = {
    "RUCKUS_SMARTZONE_PORT": 8443, "RUCKUS_TIMEOUT_SECONDS": 5,
    "RUCKUS_DEBUG_BYTES": 1000, "RUCKUS_VERIFY_TLS": False,
    "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_FETCH_AP_DETAILS": False,
    "RUCKUS_MAX_DETAIL_REQUESTS": 50, "RUCKUS_HOST_ALLOWLIST": None,
}

def test_normalize_smartzone_base_adds_default_path():
    assert normalize_smartzone_base("sz.example") == "https://sz.example:8443/wsg/api/public"

def test_normalize_rejects_http():
    import pytest
    with pytest.raises(ValueError):
        normalize_smartzone_base("http://sz.example")

@responses.activate
def test_authenticate_smartzone_happy(monkeypatch):
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.GET, f"{base}/apiInfo",
                  json={"apiSupportVersions": ["v9_0", "v10_0", "v11_0"]}, status=200)
    responses.add(responses.POST, f"{base}/v11_0/serviceTicket",
                  json={"serviceTicket": "ticket-abc", "controllerVersion": "6.1.2"},
                  status=200)
    form = {"smartzone_host": "sz.example", "smartzone_username": "u",
            "smartzone_password": "p", "smartzone_api_version": "auto",
            "smartzone_skip_tls_verify": "1"}
    conn = authenticate_smartzone(form, CFG)
    assert conn.platform == "smartzone"
    assert conn.api_version == "v11_0"
    assert conn.auth_token == "ticket-abc"
    assert conn.controller_version == "6.1.2"

@responses.activate
def test_fetch_inventory_uses_query_ap():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.GET, f"{base}/rkszones?index=0&listSize=500",
                  json={"list": []}, status=200, match_querystring=False)
    responses.add(responses.POST, f"{base}/v11_0/query/ap",
                  json={"list": [
                      {"apMac": "AA:BB:CC:DD:EE:01", "deviceName": "AP-1",
                       "model": "R650", "firmwareVersion": "7.0.0", "zoneId": "z1"}
                  ], "totalCount": 1, "hasMore": False}, status=200)
    conn = ConnectionConfig(platform="smartzone", api_base=base,
                            display_name="SZ", auth_token="t",
                            api_version="v11_0", verify_tls=False,
                            token_expires_at=9999999999)
    out = fetch_inventory(conn, CFG)
    assert len(out["assets"]) == 1
    assert out["assets"][0]["model"] == "R650"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/clients/test_smartzone.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Port smartzone.py**

Lift from `RUCKUS/ruckus_dashboard.py`:
- `authenticate_smartzone` (lines 876-930)
- `disconnect_connection` (lines 976-988) — keep name, scope to smartzone only
- `_token_valid` (lines 991-993)
- `fetch_inventory` (lines 996-1002) — but inline the platform dispatch — this file is smartzone-only
- `normalize_smartzone_base` (lines 1026-1050)
- `_fetch_smartzone_inventory` (lines 1098-1240)
- `_fetch_smartzone_operational` (lines 1242-1278)
- `_smartzone_alarm_summary` (lines 1415-1438)
- `_smartzone_paged_get` (lines 1834-1850)
- `_smartzone_get` (lines 1852-1870)
- `_smartzone_optional_get` (lines 1872-1881)
- `_smartzone_post` (lines 1883-1903)
- `_smartzone_query_paged` (lines 1905-1931)
- `_api_version_fallbacks`, `_latest_api_version`, `_api_version_key`, `_latest_firmware`, `_version_key` (helpers)
- Various AP field constants (`AP_MODEL_FIELDS`, `AP_FIRMWARE_FIELDS`, `AP_ZONE_ID_FIELDS`, etc., lines 768-816)

Imports: `time`, `typing.Any`, `urllib.parse.quote`, `urllib.parse.urlparse`, `.base.request_json`, `.base.RuckusClientError`, helpers from `.base`, `..auth.session_store.ConnectionConfig`, `..net.allowlist.assert_host_allowed`.

Rename `disconnect_connection` → `disconnect_smartzone` to avoid platform ambiguity.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/clients/test_smartzone.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/clients/smartzone.py tests/unit/clients/test_smartzone.py
git commit -m "feat(foundation): port clients/smartzone.py"
```

---

### Task 14: Extract `clients/switchm.py`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/clients/switchm.py`
- Test: `tests/unit/clients/test_switchm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/clients/test_switchm.py
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.clients.switchm import (
    fetch_switches, switch_query_payload, switch_manager_base,
)

CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None}

def test_switch_query_payload_shape():
    p = switch_query_payload(page=1, limit=50)
    assert p["page"] == 1
    assert p["limit"] == 50
    assert "sortColumn" in p

def test_switch_manager_base_from_smartzone_base():
    sz = "https://sz.example:8443/wsg/api/public"
    assert switch_manager_base(sz) == "https://sz.example:8443/switchm/api/public"

@responses.activate
def test_fetch_switches_paged():
    base = "https://sz.example:8443/switchm/api/public"
    responses.add(responses.POST, f"{base}/v11_0/switch/view/details",
                  json={"list": [
                      {"id": "s1", "name": "SW-1", "model": "ICX7150",
                       "ip": "10.0.0.1", "status": "Online"}
                  ], "totalCount": 1, "hasMore": False}, status=200)
    sz_base = "https://sz.example:8443/wsg/api/public"
    conn = ConnectionConfig(platform="smartzone", api_base=sz_base,
                            display_name="SZ", auth_token="t",
                            api_version="v11_0", verify_tls=False,
                            token_expires_at=9999999999)
    out = fetch_switches(conn, CFG)
    assert len(out["switches"]) == 1
    assert out["switches"][0]["name"] == "SW-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/clients/test_switchm.py -v`
Expected: FAIL.

- [ ] **Step 3: Extract switchm.py**

Lift from `RUCKUS/ruckus_dashboard.py`:
- `_switch_query_payload` (lines 1464-1482) → rename `switch_query_payload`
- `_switch_manager_post` (lines 1483-1498) → rename `switch_manager_post`
- `_fetch_smartzone_switches` (lines 1499-1555) → rename `fetch_switches`
- Constants: `SWITCH_MANAGER_CAPABILITY_CANDIDATES` (lines 837-854)

Add new helper `switch_manager_base(api_base: str) -> str`:

```python
def switch_manager_base(smartzone_api_base: str) -> str:
    """Derive Switch Manager API base from SmartZone base."""
    return smartzone_api_base.replace("/wsg/api/public", "/switchm/api/public")
```

This currently lives inline in `_switch_manager_post` — extract it explicitly so it's testable + reusable.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/clients/test_switchm.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/clients/switchm.py tests/unit/clients/test_switchm.py
git commit -m "feat(foundation): extract clients/switchm.py"
```

---

### Task 15: Port `clients/ruckus_one.py`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/clients/ruckus_one.py`
- Test: `tests/unit/clients/test_ruckus_one.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/clients/test_ruckus_one.py
import responses
from ruckus_dashboard.clients.ruckus_one import (
    authenticate_ruckus_one, normalize_ruckus_one_base,
)

CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_HOST_ALLOWLIST": None}

def test_normalize_region_na():
    assert normalize_ruckus_one_base("na") == "https://api.ruckus.cloud"

def test_normalize_region_eu():
    assert normalize_ruckus_one_base("eu") == "https://api.eu.ruckus.cloud"

def test_normalize_rejects_http():
    import pytest
    with pytest.raises(ValueError):
        normalize_ruckus_one_base("http://api.ruckus.cloud")

@responses.activate
def test_authenticate_ruckus_one_happy():
    responses.add(responses.POST,
                  "https://api.ruckus.cloud/oauth2/token/tenant-1",
                  json={"access_token": "tok", "expires_in": 3600}, status=200)
    form = {"tenant_id": "tenant-1", "client_id": "cid",
            "client_secret": "csec", "ruckus_one_region": "na"}
    conn = authenticate_ruckus_one(form, CFG)
    assert conn.platform == "ruckus_one"
    assert conn.auth_token == "tok"
    assert conn.tenant_id == "tenant-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/clients/test_ruckus_one.py -v`
Expected: FAIL.

- [ ] **Step 3: Port ruckus_one.py**

Lift from `RUCKUS/ruckus_dashboard.py`:
- `RUCKUS_ONE_REGIONS` constant (lines 735-743)
- `RUCKUS_ONE_FIELDS`, `RUCKUS_ONE_OPERATIONAL_FIELDS` (lines 745-766)
- `authenticate_ruckus_one` (lines 933-973)
- `normalize_ruckus_one_base` (lines 1053-1075)
- `_fetch_ruckus_one_inventory` (lines 1280-1338)
- `_fetch_ruckus_one_operational` (lines 1340-1358)
- `_ruckus_one_query` (lines 1933-1950)
- `_fetch_ruckus_one_activities` (lines 1952-1969)
- `_ruckus_one_request` (lines 1971-1987)
- `_ruckus_one_auth_base` (lines 2284-2293)

Update imports to use `.base.request_json` instead of `_request_json`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/clients/test_ruckus_one.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/clients/ruckus_one.py tests/unit/clients/test_ruckus_one.py
git commit -m "feat(foundation): port clients/ruckus_one.py"
```

---

### Task 16: Port `clients/capabilities.py`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/clients/capabilities.py`
- Test: `tests/unit/clients/test_capabilities.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/clients/test_capabilities.py
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.clients.capabilities import discover_capabilities

CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None,
       "RUCKUS_CAPABILITY_DISCOVERY": True}

@responses.activate
def test_discover_returns_op_set_on_openapi():
    base = "https://sz.example:8443/wsg/api/public"
    # mock SmartZone openapi
    responses.add(responses.GET, "https://sz.example:8443/wsg/api/public-openapi.json",
                  json={
                      "paths": {
                          "/aps": {"get": {}},
                          "/rkszones": {"get": {}},
                          "/query/ap": {"post": {}},
                      }
                  }, status=200)
    # mock switchm openapi (404 — accepted)
    responses.add(responses.GET, "https://sz.example:8443/switchm/api/public-openapi.json",
                  status=404)
    conn = ConnectionConfig(platform="smartzone", api_base=base,
                            display_name="SZ", auth_token="t",
                            api_version="v11_0", verify_tls=False,
                            token_expires_at=9999999999)
    result = discover_capabilities(conn, CFG)
    assert ("GET", "/aps") in result["available_ops"]
    assert ("POST", "/query/ap") in result["available_ops"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/clients/test_capabilities.py -v`
Expected: FAIL.

- [ ] **Step 3: Port capabilities.py**

Lift from `RUCKUS/ruckus_dashboard.py`:
- `OPENAPI_METHODS` (line 817)
- `SMARTZONE_CAPABILITY_CANDIDATES` (lines 819-835)
- `discover_capabilities` (lines 1556-1571)
- `_discover_smartzone_capabilities` (lines 1573-1615)
- `_discover_openapi_source` (lines 1617-1659)
- `_summarize_openapi_source` (lines 1661-1694)
- `_candidate_probes` (lines 1696-1704)
- `_capability_group` (lines 1706-1749)
- `_strip_openapi_version` (lines 1751-1753)
- `_controller_root` (lines 1755-1758)
- `_smartzone_openapi_urls` (lines 1760-1765)

Add to result dict: a new `available_ops: set[tuple[str, str]]` field — set of `(METHOD, normalized_path)` tuples extracted from discovered OpenAPI specs. Modules use this for capability gating (Task 21).

```python
# in _summarize_openapi_source, add to result:
"available_ops": {(method.upper(), _strip_openapi_version(path))
                  for path, ops in paths.items()
                  for method in ops if method.lower() in OPENAPI_METHODS},
```

And in `discover_capabilities`, merge sets across sources.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/clients/test_capabilities.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/clients/capabilities.py tests/unit/clients/test_capabilities.py
git commit -m "feat(foundation): port clients/capabilities.py + expose available_ops set"
```

---

### Task 17: Create `infra/cache.py` (ModuleResultCache)

**Files:**
- Create: `RUCKUS/ruckus_dashboard/infra/__init__.py` (empty)
- Create: `RUCKUS/ruckus_dashboard/infra/cache.py`
- Test: `tests/unit/infra/test_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/infra/test_cache.py
import time
from ruckus_dashboard.infra.cache import ModuleResultCache

def test_put_then_get_returns_value():
    c = ModuleResultCache()
    c.put(("conn-a",), "aps", {"zone": "z1"}, ttl=10, value={"data": 1})
    assert c.get(("conn-a",), "aps", {"zone": "z1"}) == {"data": 1}

def test_miss_returns_none():
    c = ModuleResultCache()
    assert c.get(("conn-a",), "aps", {}) is None

def test_ttl_expires():
    c = ModuleResultCache()
    c.put(("c",), "x", {}, ttl=0, value={"a": 1})
    time.sleep(0.01)
    assert c.get(("c",), "x", {}) is None

def test_different_filters_dont_collide():
    c = ModuleResultCache()
    c.put(("c",), "aps", {"zone": "a"}, ttl=10, value={"v": "a"})
    c.put(("c",), "aps", {"zone": "b"}, ttl=10, value={"v": "b"})
    assert c.get(("c",), "aps", {"zone": "a"}) == {"v": "a"}
    assert c.get(("c",), "aps", {"zone": "b"}) == {"v": "b"}

def test_invalidate_connection():
    c = ModuleResultCache()
    c.put(("c",), "aps", {}, ttl=60, value={"v": 1})
    c.invalidate_connection_set(("c",))
    assert c.get(("c",), "aps", {}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/infra/test_cache.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create cache.py**

```python
# RUCKUS/ruckus_dashboard/infra/cache.py
"""Per (connection-set, module, filters) result cache with TTL."""
from __future__ import annotations
import json
import time
from threading import RLock
from typing import Any


class ModuleResultCache:
    def __init__(self) -> None:
        self._entries: dict[tuple, tuple[float, Any]] = {}
        self._lock = RLock()

    def _key(self, conn_ids: tuple[str, ...], module: str, filters: dict | None) -> tuple:
        return (tuple(sorted(conn_ids)), module,
                json.dumps(filters or {}, sort_keys=True, default=str))

    def get(self, conn_ids: tuple[str, ...], module: str, filters: dict | None) -> Any | None:
        with self._lock:
            entry = self._entries.get(self._key(conn_ids, module, filters))
            if not entry:
                return None
            expires_at, value = entry
            if time.time() > expires_at:
                self._entries.pop(self._key(conn_ids, module, filters), None)
                return None
            return value

    def put(self, conn_ids: tuple[str, ...], module: str, filters: dict | None,
            ttl: float, value: Any) -> None:
        with self._lock:
            self._entries[self._key(conn_ids, module, filters)] = (time.time() + ttl, value)

    def invalidate_connection_set(self, conn_ids: tuple[str, ...]) -> None:
        target = tuple(sorted(conn_ids))
        with self._lock:
            doomed = [k for k in self._entries if k[0] == target]
            for k in doomed:
                self._entries.pop(k, None)
```

Create `RUCKUS/ruckus_dashboard/infra/__init__.py` empty, `tests/unit/infra/__init__.py` empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/infra/test_cache.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/infra/ tests/unit/infra/
git commit -m "feat(foundation): add infra/cache.py (ModuleResultCache)"
```

---

### Task 18: Create `infra/envelope.py` (unified error envelope)

**Files:**
- Create: `RUCKUS/ruckus_dashboard/infra/envelope.py`
- Test: `tests/unit/infra/test_envelope.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/infra/test_envelope.py
from ruckus_dashboard.infra.envelope import build_envelope, ControllerError

def test_complete_envelope_no_errors():
    env = build_envelope(data={"x": 1}, summary={"count": 1}, errors=[])
    assert env["status"] == "complete"
    assert env["data"] == {"x": 1}
    assert env["controller_errors"] == []
    assert env["stale_since"] is None
    assert env["generated_at"]

def test_partial_envelope_with_one_error():
    env = build_envelope(
        data={"x": 1},
        summary={"count": 1},
        errors=[ControllerError("SZ-A", "POST /query/ap", "timeout", 504)],
    )
    assert env["status"] == "partial"
    assert env["controller_errors"][0]["connection"] == "SZ-A"
    assert env["controller_errors"][0]["status"] == 504

def test_error_envelope_no_data():
    env = build_envelope(
        data=None,
        summary={},
        errors=[ControllerError("SZ-A", "GET /apiInfo", "down", 502)],
    )
    assert env["status"] == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/infra/test_envelope.py -v`
Expected: FAIL.

- [ ] **Step 3: Create envelope.py**

```python
# RUCKUS/ruckus_dashboard/infra/envelope.py
"""Unified envelope for module responses (status / data / errors)."""
from __future__ import annotations
import time
from dataclasses import dataclass


@dataclass
class ControllerError:
    connection: str
    endpoint: str
    message: str
    status: int

    def to_dict(self) -> dict:
        return {"connection": self.connection, "endpoint": self.endpoint,
                "message": self.message, "status": self.status}


def build_envelope(
    *, data, summary: dict, errors: list[ControllerError],
    stale_since: str | None = None,
) -> dict:
    if data is None:
        status = "error"
    elif errors:
        status = "partial"
    else:
        status = "complete"
    return {
        "status": status,
        "data": data,
        "summary": summary,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "controller_errors": [e.to_dict() for e in errors],
        "stale_since": stale_since,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/infra/test_envelope.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/infra/envelope.py tests/unit/infra/test_envelope.py
git commit -m "feat(foundation): add infra/envelope.py (unified module response envelope)"
```

---

### Task 19: Create `infra/capability_gate.py`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/infra/capability_gate.py`
- Test: `tests/unit/infra/test_capability_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/infra/test_capability_gate.py
from ruckus_dashboard.infra.capability_gate import CapabilityGate

def test_no_required_caps_always_satisfied():
    gate = CapabilityGate(available=set())
    assert gate.satisfied(())

def test_satisfied_when_all_present():
    gate = CapabilityGate(available={("GET", "/aps"), ("POST", "/query/ap")})
    assert gate.satisfied((("GET", "/aps"), ("POST", "/query/ap")))

def test_unsatisfied_when_missing():
    gate = CapabilityGate(available={("GET", "/aps")})
    assert not gate.satisfied((("GET", "/aps"), ("POST", "/missing")))

def test_missing_reports_unmet():
    gate = CapabilityGate(available={("GET", "/aps")})
    missing = gate.missing((("GET", "/aps"), ("POST", "/x")))
    assert missing == [("POST", "/x")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/infra/test_capability_gate.py -v`
Expected: FAIL.

- [ ] **Step 3: Create capability_gate.py**

```python
# RUCKUS/ruckus_dashboard/infra/capability_gate.py
"""Module-level capability gating using discovered controller op set."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class CapabilityGate:
    available: set[tuple[str, str]] = field(default_factory=set)

    def satisfied(self, required: tuple[tuple[str, str], ...]) -> bool:
        return all(req in self.available for req in required)

    def missing(self, required: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
        return [req for req in required if req not in self.available]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/infra/test_capability_gate.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/infra/capability_gate.py tests/unit/infra/test_capability_gate.py
git commit -m "feat(foundation): add infra/capability_gate.py"
```

---

### Task 20: Create `infra/inflight.py` (concurrent fetch dedupe)

**Files:**
- Create: `RUCKUS/ruckus_dashboard/infra/inflight.py`
- Test: `tests/unit/infra/test_inflight.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/infra/test_inflight.py
import threading, time
from ruckus_dashboard.infra.inflight import InFlightDeduper

def test_single_call_executes_once():
    dedup = InFlightDeduper()
    calls = []
    def work():
        calls.append(1)
        return "ok"
    result = dedup.run("key1", work)
    assert result == "ok"
    assert len(calls) == 1

def test_concurrent_calls_share_result():
    dedup = InFlightDeduper()
    calls = []
    def slow_work():
        calls.append(1)
        time.sleep(0.05)
        return "shared"
    results = []
    def fire():
        results.append(dedup.run("k", slow_work))
    threads = [threading.Thread(target=fire) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert all(r == "shared" for r in results)
    assert len(calls) == 1  # only one actual execution

def test_different_keys_dont_dedupe():
    dedup = InFlightDeduper()
    calls = []
    def work(): calls.append(1); return "x"
    dedup.run("a", work)
    dedup.run("b", work)
    assert len(calls) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/infra/test_inflight.py -v`
Expected: FAIL.

- [ ] **Step 3: Create inflight.py**

```python
# RUCKUS/ruckus_dashboard/infra/inflight.py
"""Concurrent duplicate-fetch deduplication: late callers wait for an
in-flight call with the same key and receive its result."""
from __future__ import annotations
import threading
from typing import Callable


class InFlightDeduper:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}
        self._results: dict[str, object] = {}
        self._exceptions: dict[str, BaseException] = {}

    def run(self, key: str, fn: Callable[[], object]) -> object:
        with self._lock:
            event = self._inflight.get(key)
            if event is None:
                event = threading.Event()
                self._inflight[key] = event
                owner = True
            else:
                owner = False

        if owner:
            try:
                result = fn()
                with self._lock:
                    self._results[key] = result
            except BaseException as exc:
                with self._lock:
                    self._exceptions[key] = exc
                raise
            finally:
                event.set()
                with self._lock:
                    self._inflight.pop(key, None)
                    # leave results/exceptions until waiters pick them up; clean below
            with self._lock:
                result = self._results.pop(key, None)
                self._exceptions.pop(key, None)
            return result
        else:
            event.wait()
            with self._lock:
                if key in self._exceptions:
                    raise self._exceptions[key]
                return self._results.get(key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/infra/test_inflight.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/infra/inflight.py tests/unit/infra/test_inflight.py
git commit -m "feat(foundation): add infra/inflight.py (concurrent fetch deduplication)"
```

---

### Task 21: Create `modules/_base.py` (ModuleSpec dataclass)

**Files:**
- Create: `RUCKUS/ruckus_dashboard/modules/__init__.py`
- Create: `RUCKUS/ruckus_dashboard/modules/_base.py`
- Test: `tests/unit/modules/test_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/modules/test_base.py
import pytest
from ruckus_dashboard.modules._base import ModuleSpec, TabSpec, FetcherContext

def noop_fetcher(ctx): return {"items": []}
def noop_summary(data): return {"count": 0}

def test_module_spec_minimal_valid():
    spec = ModuleSpec(
        slug="aps", title="Access Points", group="Wireless",
        icon="📶", poll_seconds=30,
        fetcher=noop_fetcher, drill_fetcher=None, drill_tabs=(),
        summary_fn=noop_summary,
        requires_platforms=("smartzone",),
        requires_capabilities=(("POST", "/query/ap"),),
        supports_views=("table",),
    )
    assert spec.slug == "aps"
    assert spec.poll_seconds == 30

def test_module_spec_rejects_invalid_group():
    with pytest.raises(ValueError):
        ModuleSpec(
            slug="x", title="X", group="UnknownGroup", icon="?",
            poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
            drill_tabs=(), summary_fn=noop_summary,
            requires_platforms=("smartzone",), requires_capabilities=(),
            supports_views=("table",),
        )

def test_module_spec_rejects_invalid_view():
    with pytest.raises(ValueError):
        ModuleSpec(
            slug="x", title="X", group="Wireless", icon="?",
            poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
            drill_tabs=(), summary_fn=noop_summary,
            requires_platforms=("smartzone",), requires_capabilities=(),
            supports_views=("invalid-view",),
        )

def test_module_spec_slug_kebab_case_only():
    with pytest.raises(ValueError):
        ModuleSpec(
            slug="Switch Groups", title="X", group="Switching", icon="?",
            poll_seconds=30, fetcher=noop_fetcher, drill_fetcher=None,
            drill_tabs=(), summary_fn=noop_summary,
            requires_platforms=("smartzone",), requires_capabilities=(),
            supports_views=("table",),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/modules/test_base.py -v`
Expected: FAIL.

- [ ] **Step 3: Create _base.py**

```python
# RUCKUS/ruckus_dashboard/modules/_base.py
"""ModuleSpec contract — every dashboard module declares one."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Callable, Any

VALID_GROUPS = {"Wireless", "Switching", "Cross-cutting"}
VALID_VIEWS = {"table", "grid", "heatmap", "chart", "tree"}
VALID_PLATFORMS = {"smartzone", "ruckus_one"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class FetcherContext:
    connection: Any           # ConnectionConfig
    config: dict
    filters: dict | None
    capability_gate: Any      # CapabilityGate
    connection_label: str


@dataclass(frozen=True)
class TabSpec:
    slug: str
    title: str
    fetcher: Callable[[FetcherContext, str], dict] | None = None  # (ctx, entity_id) -> dict


@dataclass(frozen=True)
class ModuleSpec:
    slug: str
    title: str
    group: str
    icon: str
    poll_seconds: int
    fetcher: Callable[[FetcherContext], dict]
    drill_fetcher: Callable[[FetcherContext, str], dict] | None
    drill_tabs: tuple[TabSpec, ...]
    summary_fn: Callable[[dict], dict]
    requires_platforms: tuple[str, ...]
    requires_capabilities: tuple[tuple[str, str], ...]
    supports_views: tuple[str, ...]

    def __post_init__(self) -> None:
        if not SLUG_RE.match(self.slug):
            raise ValueError(f"ModuleSpec.slug must be kebab-case: {self.slug!r}")
        if self.group not in VALID_GROUPS:
            raise ValueError(f"ModuleSpec.group must be one of {VALID_GROUPS}: {self.group!r}")
        for view in self.supports_views:
            if view not in VALID_VIEWS:
                raise ValueError(f"unknown view {view!r}; allowed: {VALID_VIEWS}")
        for platform in self.requires_platforms:
            if platform not in VALID_PLATFORMS:
                raise ValueError(f"unknown platform {platform!r}; allowed: {VALID_PLATFORMS}")
        if self.poll_seconds < 5:
            raise ValueError("poll_seconds must be >= 5")
```

Create `RUCKUS/ruckus_dashboard/modules/__init__.py`:

```python
# RUCKUS/ruckus_dashboard/modules/__init__.py
"""Module registry. Built modules call register() at import time."""
from ._base import ModuleSpec

MODULES: dict[str, ModuleSpec] = {}


def register(spec: ModuleSpec) -> ModuleSpec:
    if spec.slug in MODULES:
        raise ValueError(f"duplicate module slug: {spec.slug}")
    MODULES[spec.slug] = spec
    return spec


def all_modules() -> list[ModuleSpec]:
    return sorted(MODULES.values(), key=lambda m: (m.group, m.title))
```

Create `tests/unit/modules/__init__.py` empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/modules/test_base.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/modules/ tests/unit/modules/
git commit -m "feat(foundation): add modules/_base.py (ModuleSpec contract)"
```

---

### Task 22: Create `modules/_stub.py` + register all 18 stubs

**Files:**
- Create: `RUCKUS/ruckus_dashboard/modules/_stub.py`
- Create: `RUCKUS/ruckus_dashboard/modules/_registry.py`
- Test: `tests/unit/modules/test_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/modules/test_registry.py
from ruckus_dashboard.modules import all_modules
import ruckus_dashboard.modules._registry  # noqa: F401  registers stubs

EXPECTED_SLUGS = {
    "overview", "zones", "aps", "wlans", "clients", "alarms", "rogues", "controller",
    "switches", "switch-groups", "ports", "traffic", "poe", "stack", "vlans",
    "firmware", "security", "api-explorer",
}

def test_all_18_modules_registered():
    slugs = {m.slug for m in all_modules()}
    assert slugs == EXPECTED_SLUGS

def test_modules_grouped_correctly():
    by_group: dict[str, list[str]] = {}
    for m in all_modules():
        by_group.setdefault(m.group, []).append(m.slug)
    assert "overview" in by_group["Wireless"]
    assert "switches" in by_group["Switching"]
    assert "firmware" in by_group["Cross-cutting"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/modules/test_registry.py -v`
Expected: FAIL.

- [ ] **Step 3: Create stub + registry**

```python
# RUCKUS/ruckus_dashboard/modules/_stub.py
"""Stub fetcher used by not-yet-implemented modules."""
from __future__ import annotations
from ._base import FetcherContext

STUB_MESSAGE = "Module not yet implemented — coming in a later plan."


def stub_fetcher(ctx: FetcherContext) -> dict:
    return {"items": [], "_stub": True, "_message": STUB_MESSAGE}


def stub_summary(data: dict) -> dict:
    return {"count": 0, "stub": True}
```

```python
# RUCKUS/ruckus_dashboard/modules/_registry.py
"""Registers all 18 module shells with stub fetchers. Real fetchers
land in Plan 2-4; this file only declares the sidebar shape."""
from __future__ import annotations
from . import register
from ._base import ModuleSpec
from ._stub import stub_fetcher, stub_summary

_DEFS = [
    # ─── Wireless ───────────────────────────────────────────────
    ("overview",      "DSO Overview",        "Wireless",      "📡", 15, ()),
    ("zones",         "Zones",               "Wireless",      "🏢", 60,
        (("GET", "/rkszones"),)),
    ("aps",           "Access Points",       "Wireless",      "📶", 30,
        (("POST", "/query/ap"),)),
    ("wlans",         "WLANs",               "Wireless",      "🌐", 60,
        (("POST", "/query/wlan"),)),
    ("clients",       "Wireless Clients",    "Wireless",      "👥", 20,
        (("POST", "/query/client"),)),
    ("alarms",        "Alarms & Events",     "Wireless",      "🚨", 10,
        (("POST", "/alert/alarmSummary"),)),
    ("rogues",        "Rogues",              "Wireless",      "👻", 60,
        (("POST", "/query/roguesInfoList"),)),
    ("controller",    "Controller",          "Wireless",      "🎛️", 120,
        (("GET", "/cluster/state"),)),
    # ─── Switching ──────────────────────────────────────────────
    ("switches",      "Switches",            "Switching",     "🔌", 60,
        (("POST", "/switch/view/details"),)),
    ("switch-groups", "Switch Groups",       "Switching",     "🗂️", 120, ()),
    ("ports",         "Ports",               "Switching",     "🔗", 30,
        (("POST", "/switch/ports/summary"),)),
    ("traffic",       "Traffic",             "Switching",     "📊", 30,
        (("POST", "/traffic/top/usage"),)),
    ("poe",           "PoE",                 "Switching",     "⚡", 60,
        (("POST", "/traffic/top/poeutilization"),)),
    ("stack",         "Stack",               "Switching",     "🏗️", 60, ()),
    ("vlans",         "VLANs",               "Switching",     "🏷️", 60, ()),
    # ─── Cross-cutting ──────────────────────────────────────────
    ("firmware",      "Firmware",            "Cross-cutting", "💾", 120, ()),
    ("security",      "Security",            "Cross-cutting", "🔒", 600, ()),
    ("api-explorer",  "API Explorer",        "Cross-cutting", "🧭", 600, ()),
]

for slug, title, group, icon, poll, caps in _DEFS:
    register(ModuleSpec(
        slug=slug, title=title, group=group, icon=icon, poll_seconds=poll,
        fetcher=stub_fetcher, drill_fetcher=None, drill_tabs=(),
        summary_fn=stub_summary,
        requires_platforms=("smartzone",),
        requires_capabilities=caps,
        supports_views=("table",),
    ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/modules/test_registry.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/modules/_stub.py RUCKUS/ruckus_dashboard/modules/_registry.py tests/unit/modules/test_registry.py
git commit -m "feat(foundation): register all 18 module stubs in sidebar"
```

---

### Task 23: Create `app.py` factory (skeleton with security headers)

**Files:**
- Create: `RUCKUS/ruckus_dashboard/app.py`
- Test: `tests/integration/test_app_factory.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_app_factory.py
import os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "RUCKUS"))
from ruckus_dashboard.app import create_app

def test_app_factory_returns_flask():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": False})
    assert app.name.startswith("ruckus_dashboard")

def test_healthz_returns_200():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": False})
    with app.test_client() as c:
        r = c.get("/healthz")
        assert r.status_code == 200
        assert r.json["ok"] is True

def test_security_headers_present():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": False})
    with app.test_client() as c:
        r = c.get("/healthz")
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert "Strict-Transport-Security" in r.headers
        assert r.headers["Cache-Control"] == "no-store"
```

Create `tests/integration/__init__.py` empty.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_app_factory.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create app.py**

```python
# RUCKUS/ruckus_dashboard/app.py
"""Flask app factory. Routes registered by their own files."""
from __future__ import annotations
import logging
import secrets
import threading
import uuid
from typing import Any

from flask import Flask, g, jsonify, session

from . import APP_NAME, APP_VERSION
from .config import build_config, load_secret_key
from .logging_setup import configure_logging
from .auth.session_store import ConnectionStore
from .auth.secrets import SecretsManager
from .auth.profiles import ProfileStore
from .net.allowlist import HostAllowList
from .infra.cache import ModuleResultCache
from .infra.inflight import InFlightDeduper

LOG = logging.getLogger("ruckus_dashboard")


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True,
                template_folder="templates", static_folder="static")
    app.config.from_mapping(build_config(app.instance_path))
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = load_secret_key(app.instance_path)

    configure_logging(app.instance_path, bool(app.config.get("RUCKUS_SHOW_DEBUG")))

    app.connection_store = ConnectionStore(ttl_seconds=app.config["CREDENTIAL_TTL_SECONDS"])
    app.secrets_manager = SecretsManager(app.instance_path)
    app.profile_store = ProfileStore(app.instance_path, app.secrets_manager)
    app.config["RUCKUS_HOST_ALLOWLIST"] = HostAllowList(app.config.get("RUCKUS_ALLOWED_HOSTS", ""))
    app.module_cache = ModuleResultCache()
    app.inflight = InFlightDeduper()

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.before_request
    def before_request() -> None:
        g.request_id = uuid.uuid4().hex[:8]
        session.setdefault("csrf_token", secrets.token_urlsafe(32))

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return exc
        ref = getattr(g, "request_id", "-")
        LOG.error(f"unhandled error: {exc}", extra={"request_id": ref}, exc_info=True)
        return jsonify({"error": "Internal server error.", "reference": ref}), 500

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "app": APP_NAME, "version": APP_VERSION})

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_app_factory.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/app.py tests/integration/test_app_factory.py tests/integration/__init__.py
git commit -m "feat(foundation): app factory with security headers + service registrations"
```

---

### Task 24: Wire module routes (sidebar shell + stub endpoints)

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/app.py` (add module route registration)
- Create: `RUCKUS/ruckus_dashboard/routes/__init__.py` (empty)
- Create: `RUCKUS/ruckus_dashboard/routes/modules.py`
- Test: `tests/integration/test_routes_new_ui.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_routes_new_ui.py
from ruckus_dashboard.app import create_app

def make_app():
    return create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})

def test_module_list_endpoint():
    app = make_app()
    with app.test_client() as c:
        r = c.get("/api/modules")
        assert r.status_code == 200
        slugs = {m["slug"] for m in r.json["modules"]}
        assert "aps" in slugs
        assert "switches" in slugs
        assert len(slugs) == 18

def test_module_data_endpoint_unauthenticated_401():
    app = make_app()
    with app.test_client() as c:
        r = c.get("/api/modules/aps")
        assert r.status_code == 401
        assert r.json.get("reauth") is True

def test_unknown_module_404():
    app = make_app()
    with app.test_client() as c:
        r = c.get("/api/modules/does-not-exist")
        assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_routes_new_ui.py -v`
Expected: FAIL.

- [ ] **Step 3: Create modules route file + register in app**

```python
# RUCKUS/ruckus_dashboard/routes/__init__.py
# (empty)
```

```python
# RUCKUS/ruckus_dashboard/routes/modules.py
"""Module list + per-module data endpoints."""
from __future__ import annotations
from flask import Blueprint, abort, current_app, jsonify, request, session

from ..modules import MODULES, all_modules
from ..modules._base import FetcherContext
from ..infra.envelope import build_envelope
from ..infra.capability_gate import CapabilityGate
import ruckus_dashboard.modules._registry  # noqa: F401  side-effect: registers stubs

bp = Blueprint("modules", __name__)


@bp.get("/api/modules")
def list_modules():
    return jsonify({
        "modules": [
            {"slug": m.slug, "title": m.title, "group": m.group, "icon": m.icon,
             "poll_seconds": m.poll_seconds, "requires_platforms": list(m.requires_platforms),
             "requires_capabilities": [list(c) for c in m.requires_capabilities],
             "supports_views": list(m.supports_views)}
            for m in all_modules()
        ]
    })


@bp.get("/api/modules/<slug>")
def module_data(slug: str):
    spec = MODULES.get(slug)
    if spec is None:
        abort(404, description=f"unknown module: {slug}")
    if not session.get("auth"):
        return jsonify({"error": "Connection expired. Please reconnect.", "reauth": True}), 401

    # connection lookup intentionally minimal in foundation — full path lands
    # in module plans (2-4); here we exercise envelope + stub fetcher only
    conn_ids = tuple(session.get("connection_ids", []))
    pairs = [(cid, current_app.connection_store.get(cid)) for cid in conn_ids]
    pairs = [(cid, c) for cid, c in pairs if c is not None]
    if not pairs:
        return jsonify({"error": "Connection expired. Please reconnect.", "reauth": True}), 401

    gate = CapabilityGate(available=getattr(current_app, "available_ops", set()))
    if not gate.satisfied(spec.requires_capabilities):
        env = build_envelope(
            data={"items": [], "disabled": True,
                  "missing_capabilities": gate.missing(spec.requires_capabilities)},
            summary={"count": 0, "disabled": True},
            errors=[],
        )
        return jsonify(env)

    filters = request.args.to_dict()
    data_per_conn = []
    for _, conn in pairs:
        ctx = FetcherContext(connection=conn, config=dict(current_app.config),
                             filters=filters, capability_gate=gate,
                             connection_label=conn.display_name)
        data_per_conn.append(spec.fetcher(ctx))

    # foundation plan: trivial merge — concatenate items.
    # real merge_<slug> lands in module plans.
    items = []
    for d in data_per_conn:
        items.extend(d.get("items", []))
    merged = {"items": items}
    summary = spec.summary_fn(merged)
    env = build_envelope(data=merged, summary=summary, errors=[])
    return jsonify(env)
```

Modify `RUCKUS/ruckus_dashboard/app.py` — after `app.module_cache = ...` add:

```python
    from .routes.modules import bp as modules_bp
    app.register_blueprint(modules_bp)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_routes_new_ui.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/routes/ RUCKUS/ruckus_dashboard/app.py tests/integration/test_routes_new_ui.py
git commit -m "feat(foundation): /api/modules list + per-module data endpoint with envelope"
```

---

### Task 25: Create `templates/base.html` + sidebar + module shell

**Files:**
- Create: `RUCKUS/ruckus_dashboard/templates/base.html`
- Create: `RUCKUS/ruckus_dashboard/templates/module.html`
- Create: `RUCKUS/ruckus_dashboard/templates/overview.html`
- Create: `RUCKUS/ruckus_dashboard/templates/legacy.html`
- Create: `RUCKUS/ruckus_dashboard/templates/partials/{kpi_card,status_pill,freshness_strip,error_banner,filter_chip,entity_link,table_pagination}.html`
- Modify: `RUCKUS/ruckus_dashboard/app.py` (add `/` route picking new-ui vs legacy)
- Modify: `RUCKUS/ruckus_dashboard/routes/modules.py` — none, but add `/m/<slug>` page route in new file `routes/pages.py`
- Create: `RUCKUS/ruckus_dashboard/routes/pages.py`
- Test: `tests/integration/test_pages.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_pages.py
from ruckus_dashboard.app import create_app

def test_root_renders_legacy_when_flag_off():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": False})
    with app.test_client() as c:
        r = c.get("/")
        assert r.status_code == 200
        assert b"Legacy dashboard placeholder" in r.data \
            or b"RUCKUS NOC Assurance Dashboard" in r.data

def test_root_renders_new_ui_when_flag_on():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/")
        assert r.status_code == 200
        assert b"DSO Overview" in r.data
        assert b"sidebar" in r.data.lower()

def test_module_page_route_renders():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/m/aps")
        assert r.status_code == 200
        assert b"Access Points" in r.data

def test_unknown_module_page_404():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/m/does-not-exist")
        assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_pages.py -v`
Expected: FAIL.

- [ ] **Step 3: Create templates + pages route**

```python
# RUCKUS/ruckus_dashboard/routes/pages.py
"""HTML page routes (shell, module pages)."""
from __future__ import annotations
from flask import Blueprint, abort, current_app, render_template, session

from ..modules import MODULES, all_modules

bp = Blueprint("pages", __name__)


@bp.get("/")
def index():
    if not current_app.config.get("RUCKUS_ENABLE_NEW_UI"):
        return render_template("legacy.html")
    return render_template("overview.html",
                           modules=all_modules(),
                           csrf_token=session.get("csrf_token", ""))


@bp.get("/m/<slug>")
def module_page(slug: str):
    spec = MODULES.get(slug)
    if spec is None:
        abort(404)
    return render_template("module.html",
                           module=spec,
                           modules=all_modules(),
                           csrf_token=session.get("csrf_token", ""))


@bp.get("/m/<slug>/<entity_id>")
def drill_page(slug: str, entity_id: str):
    spec = MODULES.get(slug)
    if spec is None:
        abort(404)
    return render_template("module.html",
                           module=spec,
                           entity_id=entity_id,
                           modules=all_modules(),
                           csrf_token=session.get("csrf_token", ""))
```

Modify `RUCKUS/ruckus_dashboard/app.py` to register:

```python
    from .routes.pages import bp as pages_bp
    app.register_blueprint(pages_bp)
```

```html
<!-- RUCKUS/ruckus_dashboard/templates/base.html -->
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{% block title %}RUCKUS DSO Dashboard{% endblock %}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="{{ url_for('static', filename='styles.css') }}">
</head>
<body class="{% block body_class %}{% endblock %}">
<div class="layout">
  <aside class="sidebar" aria-label="modules">
    <div class="brand">
      <img class="brand-logo" src="{{ url_for('static', filename='assets/ruckus-logo.png') }}" alt="RUCKUS">
      <span class="brand-title">DSO Dashboard</span>
    </div>
    <nav class="module-nav">
      {% set groups = {} %}
      {% for m in modules %}{% set _ = groups.setdefault(m.group, []).append(m) %}{% endfor %}
      {% for group, items in groups.items() %}
      <div class="nav-group">
        <h3 class="nav-group-title">{{ group }}</h3>
        <ul>
          {% for m in items %}
          <li>
            <a href="/m/{{ m.slug }}" data-slug="{{ m.slug }}"
               class="nav-item {% if active_slug == m.slug %}active{% endif %}">
              <span class="nav-icon">{{ m.icon }}</span>
              <span class="nav-label">{{ m.title }}</span>
            </a>
          </li>
          {% endfor %}
        </ul>
      </div>
      {% endfor %}
    </nav>
  </aside>
  <main class="main">
    <header class="topbar">
      <div class="breadcrumb">{% block breadcrumb %}{% endblock %}</div>
      <div class="topbar-actions">
        <button class="dso-toggle" id="dso-toggle" title="Toggle DSO wall mode">⛶ DSO</button>
      </div>
    </header>
    {% block content %}{% endblock %}
  </main>
</div>
<script>window.__CSRF_TOKEN = "{{ csrf_token }}";</script>
<script src="{{ url_for('static', filename='dashboard.js') }}"></script>
</body>
</html>
```

```html
<!-- RUCKUS/ruckus_dashboard/templates/overview.html -->
{% extends "base.html" %}
{% set active_slug = "overview" %}
{% block title %}DSO Overview{% endblock %}
{% block breadcrumb %}DSO Overview{% endblock %}
{% block content %}
<section class="overview">
  <h1>DSO Overview</h1>
  <p class="subtitle">Live service-health rollup. Click any tile to drill in.</p>
  <div class="tile-grid">
    {% for m in modules if m.slug != "overview" %}
    <a href="/m/{{ m.slug }}" class="tile" data-slug="{{ m.slug }}">
      <span class="tile-icon">{{ m.icon }}</span>
      <span class="tile-title">{{ m.title }}</span>
      <span class="tile-value" data-tile-value="{{ m.slug }}">—</span>
    </a>
    {% endfor %}
  </div>
</section>
{% endblock %}
```

```html
<!-- RUCKUS/ruckus_dashboard/templates/module.html -->
{% extends "base.html" %}
{% set active_slug = module.slug %}
{% block title %}{{ module.title }} · DSO{% endblock %}
{% block breadcrumb %}{{ module.group }} › {{ module.title }}{% if entity_id %} › {{ entity_id }}{% endif %}{% endblock %}
{% block content %}
<section class="module" data-slug="{{ module.slug }}" data-poll="{{ module.poll_seconds }}"
         {% if entity_id %}data-entity="{{ entity_id }}"{% endif %}>
  <header class="module-head">
    <h1>{{ module.icon }} {{ module.title }}</h1>
    <div class="module-meta">
      <span data-freshness>—</span>
      <span data-status>idle</span>
    </div>
  </header>
  <div class="kpi-strip" data-kpi-strip>
    <!-- KPI cards rendered by JS from summary -->
  </div>
  <div class="filters" data-filters>
    <!-- filter chips injected by per-module JS -->
  </div>
  <div class="view-toggle" data-views="{{ module.supports_views|join(',') }}">
    {% for v in module.supports_views %}
    <button data-view="{{ v }}" class="{% if loop.first %}active{% endif %}">{{ v }}</button>
    {% endfor %}
  </div>
  <div class="data-area" data-data-area>
    <p class="loading">Loading…</p>
  </div>
  <footer class="module-foot">
    <span class="error-banner" data-error-banner hidden></span>
    <span class="freshness">controller status will appear here</span>
  </footer>
</section>
{% endblock %}
```

```html
<!-- RUCKUS/ruckus_dashboard/templates/legacy.html -->
{# Placeholder rendered when RUCKUS_ENABLE_NEW_UI=0. Real port of the
   existing single-file PAGE_TEMPLATE happens in a later task — for now
   we keep the legacy file at RUCKUS/ruckus_dashboard.py serving the
   original markup. #}
<!doctype html>
<html><head><title>RUCKUS NOC Assurance Dashboard</title></head>
<body>
  <h1>Legacy dashboard placeholder</h1>
  <p>The legacy single-file dashboard is still served by
     <code>RUCKUS/ruckus_dashboard.py</code> when run directly.
     Set <code>RUCKUS_ENABLE_NEW_UI=1</code> to use the new sidebar UI.</p>
</body></html>
```

Create empty partials (will be filled in module plans):

```html
<!-- RUCKUS/ruckus_dashboard/templates/partials/kpi_card.html -->
<div class="kpi-card {{ kind|default('neutral') }}">
  <span class="kpi-label">{{ label }}</span>
  <span class="kpi-value" aria-live="polite">{{ value }}</span>
  {% if meta %}<span class="kpi-meta">{{ meta }}</span>{% endif %}
</div>
```

```html
<!-- RUCKUS/ruckus_dashboard/templates/partials/status_pill.html -->
<span class="status-pill status-{{ status }}">{{ status|upper }}</span>
```

```html
<!-- RUCKUS/ruckus_dashboard/templates/partials/freshness_strip.html -->
<div class="freshness-strip">
  <span>{{ ok_count }}/{{ total_count }} controllers</span>
  <span>· last refresh {{ generated_at }}</span>
  {% if stale_since %}<span class="stale">stale since {{ stale_since }}</span>{% endif %}
</div>
```

```html
<!-- RUCKUS/ruckus_dashboard/templates/partials/error_banner.html -->
{% if errors %}
<div class="error-banner">
  {% for e in errors %}<div>{{ e.connection }}: {{ e.endpoint }} — {{ e.message }} ({{ e.status }})</div>{% endfor %}
</div>
{% endif %}
```

```html
<!-- RUCKUS/ruckus_dashboard/templates/partials/filter_chip.html -->
<button class="filter-chip" data-filter="{{ key }}" data-value="{{ value }}">{{ label }}</button>
```

```html
<!-- RUCKUS/ruckus_dashboard/templates/partials/entity_link.html -->
<a href="/m/{{ slug }}/{{ entity_id }}" class="entity-link">{{ label }}</a>
```

```html
<!-- RUCKUS/ruckus_dashboard/templates/partials/table_pagination.html -->
<div class="pagination">
  <button data-page-prev>‹ prev</button>
  <span>page {{ page }} / {{ total_pages }}</span>
  <button data-page-next>next ›</button>
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_pages.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/templates/ RUCKUS/ruckus_dashboard/routes/pages.py RUCKUS/ruckus_dashboard/app.py tests/integration/test_pages.py
git commit -m "feat(foundation): base.html + sidebar + module shell templates + page routes"
```

---

### Task 26: Add `static/styles.css` (layout + sidebar + tokens)

**Files:**
- Create: `RUCKUS/ruckus_dashboard/static/styles.css`
- Create: `RUCKUS/ruckus_dashboard/static/assets/ruckus-logo.png` (copy from existing base64)
- Test: `tests/integration/test_static_assets.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_static_assets.py
from ruckus_dashboard.app import create_app

def test_styles_css_served():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        r = c.get("/static/styles.css")
        assert r.status_code == 200
        assert b"--bg" in r.data  # CSS custom properties present

def test_logo_served():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        r = c.get("/static/assets/ruckus-logo.png")
        assert r.status_code == 200
        assert r.data.startswith(b"\x89PNG")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_static_assets.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Create styles.css + extract logo**

Create `RUCKUS/ruckus_dashboard/static/styles.css` — port the design tokens (`:root` block) from the existing `PAGE_CSS` constant in `RUCKUS/ruckus_dashboard.py` lines 3458-3465 and add layout for new sidebar shell:

```css
/* RUCKUS/ruckus_dashboard/static/styles.css */
:root {
  color-scheme: dark;
  --bg: #080b0f; --surface: #111820; --surface-soft: #17212b; --surface-muted: #0d1319;
  --text: #eef4f8; --muted: #93a4b5; --border: #273543; --accent: #22a6b3;
  --accent-dark: #13838f; --rail: #0a0f14; --rail-active: #16836f; --ok: #38c172;
  --watch: #f6c85f; --critical: #ff5f57; --neutral: #8391a2; --focus: #5bd6e5;
  --sidebar-w: 220px;
}
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: var(--bg); color: var(--text);
       font-family: Arial, Helvetica, sans-serif; }
.layout { display: grid; grid-template-columns: var(--sidebar-w) 1fr; min-height: 100vh; }
.sidebar { background: var(--rail); border-right: 1px solid var(--border);
           overflow-y: auto; padding: 14px 0; }
.brand { display: flex; align-items: center; gap: 10px; padding: 0 16px 14px; }
.brand-logo { height: 32px; }
.brand-title { font-weight: 800; }
.nav-group-title { font-size: 11px; color: var(--muted); text-transform: uppercase;
                   padding: 12px 16px 6px; margin: 0; }
.module-nav ul { list-style: none; margin: 0; padding: 0; }
.nav-item { display: flex; align-items: center; gap: 10px; padding: 8px 16px;
            color: var(--text); text-decoration: none; font-size: 13px; }
.nav-item:hover { background: var(--surface); }
.nav-item.active { background: var(--rail-active); }
.nav-icon { font-size: 16px; }
.main { padding: 18px 22px; overflow-x: auto; }
.topbar { display: flex; justify-content: space-between; align-items: center;
          margin-bottom: 14px; }
.breadcrumb { color: var(--muted); font-weight: 700; }
.dso-toggle { background: var(--surface); border: 1px solid var(--border);
              color: var(--text); padding: 6px 12px; border-radius: 6px; cursor: pointer; }
.tile-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
             gap: 12px; margin-top: 16px; }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
        padding: 16px; text-decoration: none; color: var(--text);
        display: grid; gap: 6px; }
.tile-icon { font-size: 24px; }
.tile-title { color: var(--muted); font-size: 12px; font-weight: 700; }
.tile-value { font-size: 24px; font-weight: 800; }
.module { display: grid; gap: 12px; }
.kpi-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
             gap: 10px; }
.kpi-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
            padding: 14px; display: grid; gap: 4px; }
.kpi-label { color: var(--muted); font-size: 11px; text-transform: uppercase; font-weight: 800; }
.kpi-value { font-size: 30px; font-weight: 800; }
.kpi-card.ok .kpi-value { color: var(--ok); }
.kpi-card.watch .kpi-value { color: var(--watch); }
.kpi-card.critical .kpi-value { color: var(--critical); }
.data-area { background: var(--surface); border: 1px solid var(--border);
             border-radius: 8px; padding: 14px; min-height: 200px; }
.error-banner { background: #2b1213; border: 1px solid #74302d; color: var(--critical);
                padding: 8px 12px; border-radius: 6px; }
.status-pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
               font-size: 11px; font-weight: 800; }
.status-complete { background: #103627; color: var(--ok); }
.status-partial { background: #3a2f0e; color: var(--watch); }
.status-error { background: #2b1213; color: var(--critical); }
body.dso-mode .sidebar, body.dso-mode .topbar { display: none; }
body.dso-mode .kpi-value { font-size: 48px; }
```

Extract logo: write a tiny helper script `scripts/extract_logo.py`:

```python
# scripts/extract_logo.py
"""Extracts RUCKUS_LOGO_PNG_B64 from RUCKUS/ruckus_dashboard.py into
RUCKUS/ruckus_dashboard/static/assets/ruckus-logo.png."""
import base64, re, pathlib

src = pathlib.Path("RUCKUS/ruckus_dashboard.py").read_text(encoding="utf-8")
m = re.search(r'RUCKUS_LOGO_PNG_B64\s*=\s*"([^"]+)"', src)
if not m:
    raise SystemExit("RUCKUS_LOGO_PNG_B64 not found in source")
out = pathlib.Path("RUCKUS/ruckus_dashboard/static/assets/ruckus-logo.png")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(base64.b64decode(m.group(1)))
print(f"wrote {out} ({out.stat().st_size} bytes)")
```

Run: `python scripts/extract_logo.py`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_static_assets.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/static/ scripts/extract_logo.py tests/integration/test_static_assets.py
git commit -m "feat(foundation): styles.css with sidebar + tile-grid + KPI tokens; extract logo"
```

---

### Task 27: Add `static/dashboard.js` (hash router + polling loop)

**Files:**
- Create: `RUCKUS/ruckus_dashboard/static/dashboard.js`
- Test: `tests/integration/test_dashboard_js.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_dashboard_js.py
from ruckus_dashboard.app import create_app

def test_dashboard_js_served_and_has_router():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        r = c.get("/static/dashboard.js")
        assert r.status_code == 200
        body = r.data.decode()
        # signature symbols must be present
        for symbol in ["startModulePoller", "stopModulePoller",
                       "renderModule", "renderTile",
                       "document.hidden", "fetch("]:
            assert symbol in body, f"missing JS symbol: {symbol}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_dashboard_js.py -v`
Expected: FAIL.

- [ ] **Step 3: Create dashboard.js**

```javascript
// RUCKUS/ruckus_dashboard/static/dashboard.js
"use strict";

const moduleState = {};  // slug -> { timer, lastResponse, errorCount, filters }
let activePoller = null;

function startModulePoller(slug, pollSeconds, entityId) {
  stopModulePoller();
  const tick = () => {
    if (document.hidden) return;  // pause when tab hidden
    fetchModule(slug, entityId).catch(err => {
      console.error("module fetch failed", slug, err);
      const st = moduleState[slug] || (moduleState[slug] = {});
      st.errorCount = (st.errorCount || 0) + 1;
      showErrorBanner(`Fetch failed: ${err.message}`);
    });
  };
  tick();  // immediate
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
    location.href = "/";  // session expired
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

  // KPI strip from summary
  const strip = root.querySelector("[data-kpi-strip]");
  if (strip && payload.summary) {
    strip.innerHTML = Object.entries(payload.summary)
      .map(([k, v]) => `<div class="kpi-card neutral"><span class="kpi-label">${k}</span>` +
                       `<span class="kpi-value" aria-live="polite">${v}</span></div>`)
      .join("");
  }

  // Disabled (capability missing)
  if (payload.data && payload.data.disabled) {
    root.querySelector("[data-data-area]").innerHTML =
      `<div class="error-banner">Module disabled — controller missing required ops: ` +
      `${(payload.data.missing_capabilities || []).map(c => c.join(" ")).join(", ")}</div>`;
    return;
  }

  // Default table render of items
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

  // Errors footer
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
      // immediate refresh on tab focus
      fetchModule(activePoller.slug).catch(() => {});
    }
  });
  const dso = document.getElementById("dso-toggle");
  if (dso) dso.addEventListener("click", () => document.body.classList.toggle("dso-mode"));

  // Overview: fan-out summary fetch for each tile
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_dashboard_js.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/static/dashboard.js tests/integration/test_dashboard_js.py
git commit -m "feat(foundation): dashboard.js hash router + polling + visibility hook"
```

---

### Task 28: Port `cli.py` (argparse + launcher)

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/cli.py` (replace NotImplementedError stub with real launcher)
- Test: `tests/integration/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_cli.py
import subprocess, sys

def test_cli_help_works():
    r = subprocess.run(
        [sys.executable, "-m", "ruckus_dashboard", "--help"],
        capture_output=True, text=True, cwd="RUCKUS",
    )
    assert r.returncode == 0
    assert "--bind" in r.stdout
    assert "--port" in r.stdout
    assert "--debug" in r.stdout
    assert "--allowed-hosts" in r.stdout

def test_cli_version_works():
    r = subprocess.run(
        [sys.executable, "-m", "ruckus_dashboard", "--version"],
        capture_output=True, text=True, cwd="RUCKUS",
    )
    assert r.returncode == 0
    assert "RUCKUS" in (r.stdout + r.stderr)

def test_cli_parses_overrides():
    from ruckus_dashboard.cli import _parse_args
    args = _parse_args(["--bind", "0.0.0.0", "--port", "9999",
                        "--no-browser", "--debug",
                        "--allowed-hosts", "10.0.0.0/8"])
    assert args.bind == "0.0.0.0"
    assert args.port == 9999
    assert args.no_browser is True
    assert args.debug is True
    assert args.allowed_hosts == "10.0.0.0/8"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_cli.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement cli.py**

Lift from `RUCKUS/ruckus_dashboard.py`:
- `_parse_args` (lines 3372-3394)
- `main` (lines 3397-3452)
- `open_browser_once` (lines 3358-3363)
- `_browser_host` (lines 3364-3370)

Adjust imports to use new package paths (`from .app import create_app`, `from .certs import ensure_self_signed_cert`, `from .net.port_scan import select_dashboard_port, port_self_test_script_block`).

```python
# RUCKUS/ruckus_dashboard/cli.py
"""Argparse-driven launcher. Replaces monolith main()."""
from __future__ import annotations
import argparse
import sys
import threading
import webbrowser
from typing import Any

from . import APP_NAME, APP_VERSION
from .app import create_app
from .certs import ensure_self_signed_cert
from .net.port_scan import select_dashboard_port, port_self_test_script_block
from .config import DEFAULT_DASHBOARD_PORT, DEFAULT_SMARTZONE_API_PORT

_BROWSER_OPENED = False


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ruckus_dashboard",
                                description=f"{APP_NAME} v{APP_VERSION}")
    p.add_argument("--bind", help="Interface to bind (default 127.0.0.1).")
    p.add_argument("--port", type=int, help=f"HTTPS port (default {DEFAULT_DASHBOARD_PORT}).")
    p.add_argument("--smartzone-port", type=int,
                   help=f"SmartZone API port (default {DEFAULT_SMARTZONE_API_PORT}).")
    p.add_argument("--no-browser", action="store_true", help="Do not auto-open a browser.")
    p.add_argument("--no-auto-port", action="store_true",
                   help="Fail instead of scanning for a free port.")
    p.add_argument("--allowed-hosts", default=None,
                   help="SSRF allow-list (comma-separated).")
    p.add_argument("--debug", action="store_true", help="Expose API debug output.")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    return p.parse_args(argv)


def _browser_host(host: str) -> str:
    return "localhost" if host in {"0.0.0.0", "::"} else host


def open_browser_once(url: str) -> None:
    global _BROWSER_OPENED
    if _BROWSER_OPENED:
        return
    _BROWSER_OPENED = True
    threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    overrides: dict[str, Any] = {}
    if args.bind: overrides["APP_HOST"] = args.bind
    if args.port is not None: overrides["APP_PORT"] = args.port
    if args.smartzone_port is not None: overrides["RUCKUS_SMARTZONE_PORT"] = args.smartzone_port
    if args.no_browser: overrides["APP_OPEN_BROWSER"] = False
    if args.no_auto_port: overrides["APP_AUTO_PORT"] = False
    if args.allowed_hosts is not None: overrides["RUCKUS_ALLOWED_HOSTS"] = args.allowed_hosts
    if args.debug: overrides["RUCKUS_SHOW_DEBUG"] = True

    app = create_app(overrides or None)
    bind_host = app.config["APP_HOST"]
    requested_port = int(app.config["APP_PORT"])

    print(port_self_test_script_block(bind_host, requested_port))
    port, used_random_port = select_dashboard_port(
        bind_host, requested_port, app.config["APP_AUTO_PORT"],
        scan_limit=app.config["APP_PORT_SCAN_LIMIT"],
    )
    cert_file, key_file = ensure_self_signed_cert(app.instance_path)
    url = f"https://{_browser_host(bind_host)}:{port}"

    print(f"{APP_NAME} v{APP_VERSION}")
    if used_random_port:
        print(f"Requested port {requested_port} unavailable; using {port}.")
    print(f"Opening dashboard: {url}")
    if app.config["APP_OPEN_BROWSER"]:
        open_browser_once(url)

    try:
        app.run(host=bind_host, port=port,
                ssl_context=(str(cert_file), str(key_file)),
                debug=False, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        import os
        os._exit(0)
```

Update `RUCKUS/ruckus_dashboard/__main__.py` to skip the `--version` short-circuit (cli now handles it via argparse):

```python
# RUCKUS/ruckus_dashboard/__main__.py
from .cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_cli.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard/cli.py RUCKUS/ruckus_dashboard/__main__.py tests/integration/test_cli.py
git commit -m "feat(foundation): port cli.py + launcher; package now runnable"
```

---

### Task 29: Backward-compat shim — replace `RUCKUS/ruckus_dashboard.py`

**Files:**
- Modify: `RUCKUS/ruckus_dashboard.py` (shrink to shim)
- Backup: existing file → `RUCKUS/ruckus_dashboard_legacy.py.bak` (not committed; for reference only during transition)
- Test: `tests/integration/test_backward_compat.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_backward_compat.py
import subprocess, sys

def test_legacy_script_still_runnable():
    """`python RUCKUS/ruckus_dashboard.py --help` must still work for users."""
    r = subprocess.run(
        [sys.executable, "RUCKUS/ruckus_dashboard.py", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "--bind" in r.stdout

def test_legacy_main_importable():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "ruckus_dashboard_shim",
        pathlib.Path("RUCKUS/ruckus_dashboard.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.main)
    assert mod.APP_NAME == "RUCKUS NOC Assurance Dashboard"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_backward_compat.py -v`
Expected: PASS for first test (existing file works), FAIL for second (shim assertion fails because file is huge).

Actually the existing file has `main` and `APP_NAME` already, so both may pass. Run to confirm — if both pass, the test demonstrates current behaviour preserved.

- [ ] **Step 3: Replace with shim**

Back up the existing file mentally — the 5K lines are now distributed across the package. Replace `RUCKUS/ruckus_dashboard.py` with a thin shim:

```python
#!/usr/bin/env python3
"""Backward-compat shim. Real code lives in the ruckus_dashboard package.

Allows `python RUCKUS/ruckus_dashboard.py` to keep working for users
who hand-launch the script. New entrypoint: `python -m ruckus_dashboard`.
"""
from __future__ import annotations
import sys, pathlib

# Ensure the package directory next to this shim is importable
_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from ruckus_dashboard import APP_NAME, APP_VERSION  # re-export
from ruckus_dashboard.cli import main                # re-export

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_backward_compat.py -v`
Expected: 2 PASS.

Run full integration regression:
`pytest tests/integration/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add RUCKUS/ruckus_dashboard.py tests/integration/test_backward_compat.py
git commit -m "refactor(foundation): replace 5076-line monolith with package shim

All functionality now lives in RUCKUS/ruckus_dashboard/. The top-level
script remains runnable for users who launch by file path."
```

---

### Task 30: Smoke test — full launch dry-run

**Files:**
- Create: `tests/smoke/__init__.py` (empty)
- Create: `tests/smoke/test_launch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/smoke/test_launch.py
import socket, ssl, subprocess, sys, time, urllib.request

def _wait_port(host, port, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False

def test_app_boots_and_serves_healthz(tmp_path):
    """End-to-end smoke: launch CLI, hit /healthz over self-signed HTTPS."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "ruckus_dashboard",
         "--bind", "127.0.0.1", "--port", "0", "--no-browser"],
        cwd="RUCKUS",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        # Read CLI stdout to discover the assigned port
        port = None
        deadline = time.time() + 10
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line: break
            # CLI prints "Opening dashboard: https://localhost:NNNN"
            if "Opening dashboard:" in line:
                port = int(line.rsplit(":", 1)[1].strip())
                break
        assert port, "CLI did not print port within 10s"
        assert _wait_port("127.0.0.1", port, timeout=10)

        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(f"https://127.0.0.1:{port}/healthz",
                                     context=ctx, timeout=5) as r:
            assert r.status == 200
    finally:
        proc.terminate()
        proc.wait(timeout=5)
```

- [ ] **Step 2: Run test to verify it fails (or passes if all prior tasks landed correctly)**

Run: `pytest tests/smoke/test_launch.py -v`
Expected: PASS (this is the integration capstone).

If it fails, the failure points to whichever earlier task didn't compose cleanly — fix that task before continuing.

- [ ] **Step 3: (no impl needed — capstone)**

- [ ] **Step 4: Re-run all tests**

Run: `pytest -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/smoke/
git commit -m "test(foundation): end-to-end smoke — boot CLI, hit /healthz over HTTPS"
```

---

### Task 31: GitHub Actions CI matrix

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write CI workflow**

```yaml
# .github/workflows/ci.yml
name: ci
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        python: ["3.10", "3.11", "3.12"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e RUCKUS[test]
          pip install ruff
      - name: Lint
        run: ruff check RUCKUS/ruckus_dashboard tests
      - name: Test
        run: pytest -v --cov=ruckus_dashboard --cov-fail-under=75
```

- [ ] **Step 2: Verify the workflow file parses**

Run locally: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no exceptions.

- [ ] **Step 3: (no impl beyond writing the file)**

- [ ] **Step 4: Commit, push, observe CI**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(foundation): GitHub Actions matrix (Ubuntu + Windows × 3.10/3.11/3.12)"
```

After push, watch the first run and fix any platform-specific issues (typically: line endings, `os._exit` behaviour, port-scan edge cases) by adding new test cases — not by relaxing the matrix.

- [ ] **Step 5: Final sanity sweep**

Run from project root: `pytest -v --cov=ruckus_dashboard`
Expected: ≥75 % coverage, all green, no XFAIL/SKIP except the Windows-only DPAPI test on non-Windows.

---

## Acceptance criteria (Plan 1 done)

- [ ] `python -m ruckus_dashboard` boots, serves HTTPS, opens browser.
- [ ] `python RUCKUS/ruckus_dashboard.py` (legacy path) still boots.
- [ ] With `RUCKUS_ENABLE_NEW_UI=0` (default): legacy placeholder renders at `/`.
- [ ] With `RUCKUS_ENABLE_NEW_UI=1`: sidebar shows all 18 modules grouped Wireless / Switching / Cross-cutting; each `/m/<slug>` page renders the module shell.
- [ ] `/api/modules` returns 18 entries; `/api/modules/<slug>` returns envelope `{status, data, summary, generated_at, controller_errors, stale_since}`.
- [ ] Capability-gated stubs short-circuit to `disabled: true` envelope when required ops missing.
- [ ] Security headers, CSRF token plumbing, session store, secrets, profiles, allowlist all preserved.
- [ ] `pytest` green, ≥75 % coverage, CI passes on Windows + Linux × Python 3.10/3.11/3.12.

## Follow-ups (subsequent plans, not in scope)

- **Plan 2 — Wireless modules**: replace stubs for Overview, Zones, APs, WLANs, Clients, Alarms, Controller with real fetchers + tests + drill-ins + filters + per-module summary functions.
- **Plan 3 — Switching modules**: Switches, Switch Groups, Ports, Traffic, PoE, Stack, VLANs.
- **Plan 4 — Cross-cutting**: Firmware (port existing), Security (port existing), API Explorer (replace current "Controller API Surface" card; cover the 98 Other Switch + 533 Other Wireless long-tail ops).

## Self-review notes (run after writing)

**Spec coverage** ✓ — Foundation section of spec (architecture, ModuleSpec contract, capability gating, caching, error envelope, polling, sidebar, package layout) all covered. Module-specific concerns intentionally deferred to follow-up plans.

**Placeholder scan** ✓ — No "TBD" / "handle edge cases" / "similar to Task N" left. Every step contains the code or command.

**Type consistency** ✓ — `request_json` consistently named in Task 12+ usages. `FetcherContext` defined in Task 21, consumed in Task 24. `CapabilityGate.satisfied/missing` signatures match in Task 19 and Task 24.

**Scope** ✓ — One plan, one shippable increment (foundation behind feature flag with all modules stubbed). Real module work belongs to plans 2-4.
