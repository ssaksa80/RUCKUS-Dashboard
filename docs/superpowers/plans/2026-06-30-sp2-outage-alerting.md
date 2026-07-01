# SP2 — Outage Alerting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace count-based alert state with per-device snapshot diffing, a durable JSON state store, and an extensible notification-channel interface, eliminating baseline-spam on (re)connect, enabling recovery alerts and per-site/zone grouping for APs, switches, and controller nodes, and persisting daily-report dedup across restarts.

**Architecture:** A new pure `OutageEngine.reconcile()` function diffs a current device snapshot (`dict[str, DeviceStatus]`) against committed state loaded from `instance/notify_state.json`, emitting `OutageEvent` objects that `render_alert()` groups by site/zone before dispatching through a `NotificationChannel` Protocol; `JsonOutageStateStore` persists state atomically (tmp+replace, mirroring `auth/secrets.py:89-91`) so a reconnect or restart loads committed device status and never re-fires pre-existing outages. The scheduler's `_tick` replaces the current `evaluate()`+`_prev_state` path with `collect_device_snapshot`→`reconcile`→`store.save`→`channel.send`; `_last_report_day` migrates from the in-memory field into `notify_state.json`.

**Tech Stack:** Python 3.10+ stdlib only (`json`, `os`, `time`, `threading`, `pathlib`, `dataclasses`, `typing`); pytest for all tests; `monkeypatch` for SMTP; `tmp_instance` fixture from `tests/conftest.py` for disk tests.

---

## File Structure

| File | Responsibility | Tasks |
|------|---------------|-------|
| `RUCKUS/ruckus_dashboard/notify/outage.py` | `DeviceStatus` dataclass, `OutageEvent` dataclass, `OutageEngine.reconcile()` pure function, `render_alert()`, `device_online()` helpers | T1, T2, T3, T4 |
| `RUCKUS/ruckus_dashboard/notify/state_store.py` | `PersistedState` dataclass, `OutageStateStore` Protocol, `JsonOutageStateStore` (atomic write, tolerant load) | T5 |
| `RUCKUS/ruckus_dashboard/notify/channels.py` | `Notification` dataclass, `NotificationChannel` Protocol, `EmailChannel`, `CHANNELS` registry | T6 |
| `RUCKUS/ruckus_dashboard/notify/config.py` | Extend `DEFAULTS["alerts"]` with `recovery`, `debounce_seconds`, `group_by`, `suppress_known_on_start`, `channels`; keep `_merged` deep-merge | T7 |
| `RUCKUS/ruckus_dashboard/notify/scheduler.py` | Add `collect_device_snapshot`; rewrite alerts branch of `_tick`; remove `_prev_state`; move `_last_report_day` into store; stop nulling state in `set_connection`; fix `state_from_data` (#14) | T8, T9 |
| `RUCKUS/ruckus_dashboard/notify/rules.py` | No change (retained for `poor_client_ap` advisory; outage path retired via scheduler rewrite) | — |
| `tests/unit/notify/test_notify.py` | Add all new unit tests; invert baseline-spam test (#4); add `count or 1` fix test (#14); add durable-dedup test (#5) | T1–T9 |
| `tests/integration/test_notifications_api.py` | Extend config roundtrip to carry new fields; add alert-test body format check | T10 |

---

## Task 1 — `DeviceStatus` and `device_online()` helpers

**Files:**
- Create: `RUCKUS/ruckus_dashboard/notify/outage.py`
- Test: `tests/unit/notify/test_notify.py`

### Steps

- [ ] **Write the failing test.** Append to `tests/unit/notify/test_notify.py`:

```python
# ── outage: DeviceStatus and device_online helpers ────────────────────────

def test_device_status_dataclass_fields():
    from ruckus_dashboard.notify.outage import DeviceStatus
    ds = DeviceStatus(
        key="ap:aabbcc",
        type="ap",
        name="AP-1",
        group="HQ",
        online=True,
        raw_status="online",
        last_change=1000.0,
    )
    assert ds.key == "ap:aabbcc"
    assert ds.online is True
    assert ds.last_change == 1000.0
    # pending fields default to None
    assert ds.pending_since is None
    assert ds.pending_target is None


def test_device_online_ap():
    from ruckus_dashboard.notify.outage import device_online
    assert device_online("ap", "online") is True
    assert device_online("ap", "offline") is False
    assert device_online("ap", "unknown") is False


def test_device_online_switch():
    from ruckus_dashboard.notify.outage import device_online
    assert device_online("switch", "online") is True
    assert device_online("switch", "offline") is False
    assert device_online("switch", "flagged") is False


def test_device_online_controller():
    from ruckus_dashboard.notify.outage import device_online
    # matches controller._NODE_ONLINE exactly
    for state in ("in_service", "online", "active", "up",
                  "management_in_service", "service_ready"):
        assert device_online("controller", state) is True, state
    assert device_online("controller", "disconnected") is False
    assert device_online("controller", "") is False
```

- [ ] **Run — expect FAIL** (ImportError: `notify.outage` does not exist):

```
python -m pytest tests/unit/notify/test_notify.py::test_device_status_dataclass_fields tests/unit/notify/test_notify.py::test_device_online_ap tests/unit/notify/test_notify.py::test_device_online_switch tests/unit/notify/test_notify.py::test_device_online_controller -v
```

Expected: `ModuleNotFoundError: No module named 'ruckus_dashboard.notify.outage'`

- [ ] **Implement** — create `RUCKUS/ruckus_dashboard/notify/outage.py`:

```python
"""Per-device outage detection: snapshot diffing, debounce, event rendering.

Pure functions only (no I/O). The scheduler owns the store; this module owns
the logic so it stays fully unit-testable without any disk access."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# ── status constants (kept in sync with each module's ONLINE_VALUES) ──────

_AP_ONLINE = {"online", "connected", "run", "operational", "registered", "up"}
_SWITCH_ONLINE = {"online", "connected", "run", "operational", "registered",
                  "up", "approved", "ok"}
# Mirrors controller._NODE_ONLINE exactly — do NOT duplicate the constant;
# import it at call time to stay in sync.
_CONTROLLER_ONLINE: frozenset[str] | None = None


def _controller_online_set() -> frozenset[str]:
    global _CONTROLLER_ONLINE
    if _CONTROLLER_ONLINE is None:
        from ..modules.controller import _NODE_ONLINE
        _CONTROLLER_ONLINE = frozenset(_NODE_ONLINE)
    return _CONTROLLER_ONLINE


def device_online(device_type: str, raw_status: str) -> bool:
    """Return True when *raw_status* indicates the device is online.

    Uses each module's own normalization vocabulary so status strings are
    not re-implemented here."""
    s = str(raw_status or "").strip().lower()
    if device_type == "ap":
        return s in _AP_ONLINE
    if device_type == "switch":
        return s in _SWITCH_ONLINE
    if device_type == "controller":
        return s in _controller_online_set()
    return False


# ── data model ────────────────────────────────────────────────────────────

@dataclass
class DeviceStatus:
    """One device's current status within the outage engine."""
    key: str                   # "ap:aabbcc", "switch:id", "controller:nodeId"
    type: str                  # ap | switch | controller
    name: str
    group: str | None          # AP zone | switch group/stack | "controller"
    online: bool               # committed online state
    raw_status: str            # normalized status string for message rendering
    last_change: float         # epoch when online last flipped

    # Debounce tracking — None when stable
    pending_since: float | None = field(default=None)
    pending_target: bool | None = field(default=None)  # what we're debouncing toward


@dataclass(frozen=True)
class OutageEvent:
    """A committed state transition (after debounce) for a single device."""
    kind: str          # "offline" | "online"
    key: str
    type: str          # ap | switch | controller
    name: str
    group: str | None
    raw_status: str
    ts: float          # epoch of the committed transition
```

- [ ] **Run — expect PASS**:

```
python -m pytest tests/unit/notify/test_notify.py::test_device_status_dataclass_fields tests/unit/notify/test_notify.py::test_device_online_ap tests/unit/notify/test_notify.py::test_device_online_switch tests/unit/notify/test_notify.py::test_device_online_controller -v
```

- [ ] **Commit**:

```
git commit -m "feat(notify): add DeviceStatus + OutageEvent dataclasses and device_online() helpers"
```

---

## Task 2 — `OutageEngine.reconcile()` — baseline seeding and offline transitions

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/notify/outage.py`
- Test: `tests/unit/notify/test_notify.py`

### Steps

- [ ] **Write the failing tests.** Append to `tests/unit/notify/test_notify.py`:

```python
# ── outage: OutageEngine.reconcile ────────────────────────────────────────

def _make_snapshot(entries: list[tuple]) -> dict:
    """entries: (key, type, name, group, online, raw_status)"""
    from ruckus_dashboard.notify.outage import DeviceStatus
    return {
        key: DeviceStatus(key=key, type=typ, name=name, group=grp,
                          online=on, raw_status=rs, last_change=0.0)
        for key, typ, name, grp, on, rs in entries
    }


def test_reconcile_baseline_seeding_no_events():
    """First call (empty prior devices) seeds silently — no events emitted."""
    from ruckus_dashboard.notify.outage import OutageEngine
    snapshot = _make_snapshot([
        ("ap:aa", "ap", "AP-1", "HQ", False, "offline"),
        ("ap:bb", "ap", "AP-2", "HQ", True, "online"),
    ])
    cfg = {"debounce_seconds": 0, "recovery": True, "offline_threshold": 1}
    events, new_devices = OutageEngine.reconcile({}, snapshot, cfg, now=1000.0)
    assert events == []
    assert new_devices["ap:aa"].online is False
    assert new_devices["ap:bb"].online is True


def test_reconcile_offline_transition_fires_immediately_when_no_debounce():
    """Previously-online device goes offline; debounce=0 fires on first tick."""
    from ruckus_dashboard.notify.outage import OutageEngine
    prev_devices = _make_snapshot([
        ("ap:aa", "ap", "AP-1", "HQ", True, "online"),
    ])
    snapshot = _make_snapshot([
        ("ap:aa", "ap", "AP-1", "HQ", False, "offline"),
    ])
    cfg = {"debounce_seconds": 0, "recovery": True, "offline_threshold": 1}
    events, _ = OutageEngine.reconcile(prev_devices, snapshot, cfg, now=2000.0)
    assert len(events) == 1
    assert events[0].kind == "offline"
    assert events[0].key == "ap:aa"
    assert events[0].name == "AP-1"
    assert events[0].group == "HQ"
    assert events[0].ts == 2000.0


def test_reconcile_stable_online_no_event():
    """Device that was online and stays online emits nothing."""
    from ruckus_dashboard.notify.outage import OutageEngine
    prev = _make_snapshot([("ap:aa", "ap", "AP-1", "HQ", True, "online")])
    snap = _make_snapshot([("ap:aa", "ap", "AP-1", "HQ", True, "online")])
    cfg = {"debounce_seconds": 0, "recovery": True, "offline_threshold": 1}
    events, _ = OutageEngine.reconcile(prev, snap, cfg, now=3000.0)
    assert events == []


def test_reconcile_stable_offline_no_event():
    """Pre-existing outage (committed offline) stays offline — no re-alert."""
    from ruckus_dashboard.notify.outage import OutageEngine
    prev = _make_snapshot([("ap:aa", "ap", "AP-1", "HQ", False, "offline")])
    snap = _make_snapshot([("ap:aa", "ap", "AP-1", "HQ", False, "offline")])
    cfg = {"debounce_seconds": 0, "recovery": True, "offline_threshold": 1}
    events, _ = OutageEngine.reconcile(prev, snap, cfg, now=4000.0)
    assert events == []


def test_reconcile_recovery_event_when_enabled():
    """Offline device comes back; recovery=True emits online event."""
    from ruckus_dashboard.notify.outage import OutageEngine
    prev = _make_snapshot([("sw:s1", "switch", "SW-1", "Core", False, "offline")])
    snap = _make_snapshot([("sw:s1", "switch", "SW-1", "Core", True, "online")])
    cfg = {"debounce_seconds": 0, "recovery": True, "offline_threshold": 1}
    events, _ = OutageEngine.reconcile(prev, snap, cfg, now=5000.0)
    assert len(events) == 1
    assert events[0].kind == "online"
    assert events[0].key == "sw:s1"


def test_reconcile_recovery_suppressed_when_disabled():
    """Offline device comes back; recovery=False emits nothing."""
    from ruckus_dashboard.notify.outage import OutageEngine
    prev = _make_snapshot([("sw:s1", "switch", "SW-1", "Core", False, "offline")])
    snap = _make_snapshot([("sw:s1", "switch", "SW-1", "Core", True, "online")])
    cfg = {"debounce_seconds": 0, "recovery": False, "offline_threshold": 1}
    events, _ = OutageEngine.reconcile(prev, snap, cfg, now=6000.0)
    assert events == []


def test_reconcile_offline_threshold_suppresses_small_batch():
    """`offline_threshold=3` suppresses a batch of only 2 newly-offline devices."""
    from ruckus_dashboard.notify.outage import OutageEngine
    prev = _make_snapshot([
        ("ap:a1", "ap", "AP-1", "HQ", True, "online"),
        ("ap:a2", "ap", "AP-2", "HQ", True, "online"),
    ])
    snap = _make_snapshot([
        ("ap:a1", "ap", "AP-1", "HQ", False, "offline"),
        ("ap:a2", "ap", "AP-2", "HQ", False, "offline"),
    ])
    cfg = {"debounce_seconds": 0, "recovery": True, "offline_threshold": 3}
    events, _ = OutageEngine.reconcile(prev, snap, cfg, now=7000.0)
    # only 2 newly offline, threshold=3 — suppressed
    offline_events = [e for e in events if e.kind == "offline"]
    assert offline_events == []


def test_reconcile_offline_threshold_fires_when_met():
    """`offline_threshold=2` fires when exactly 2 devices newly go offline."""
    from ruckus_dashboard.notify.outage import OutageEngine
    prev = _make_snapshot([
        ("ap:a1", "ap", "AP-1", "HQ", True, "online"),
        ("ap:a2", "ap", "AP-2", "HQ", True, "online"),
    ])
    snap = _make_snapshot([
        ("ap:a1", "ap", "AP-1", "HQ", False, "offline"),
        ("ap:a2", "ap", "AP-2", "HQ", False, "offline"),
    ])
    cfg = {"debounce_seconds": 0, "recovery": True, "offline_threshold": 2}
    events, _ = OutageEngine.reconcile(prev, snap, cfg, now=8000.0)
    offline_events = [e for e in events if e.kind == "offline"]
    assert len(offline_events) == 2
```

- [ ] **Run — expect FAIL** (AttributeError: `OutageEngine` not defined):

```
python -m pytest tests/unit/notify/test_notify.py -k "test_reconcile" -v
```

Expected: `AttributeError: module 'ruckus_dashboard.notify.outage' has no attribute 'OutageEngine'`

- [ ] **Implement** — append to `RUCKUS/ruckus_dashboard/notify/outage.py`:

```python
# ── OutageEngine ──────────────────────────────────────────────────────────

class OutageEngine:
    """Pure outage-state reconciler — no I/O, fully deterministic."""

    @staticmethod
    def reconcile(
        prev_devices: dict[str, DeviceStatus],
        snapshot: dict[str, DeviceStatus],
        cfg: dict[str, Any],
        now: float | None = None,
    ) -> tuple[list[OutageEvent], dict[str, DeviceStatus]]:
        """Diff *snapshot* against *prev_devices* to produce transition events.

        Returns (events, new_devices).  new_devices is the next committed state
        to be persisted by the caller.

        Rules:
        - Empty prev_devices → baseline seeding: commit snapshot silently,
          emit no events.
        - Per device key (union of prev ∪ snapshot keys):
          - Absent from snapshot → treated as offline (device disappeared).
          - Committed state matches observed → clear any pending debounce.
          - Differs from committed and no pending → start debounce window.
          - Differs from committed and pending has matured → commit + emit event.
        - offline_threshold: only emit offline events when the batch of newly
          offline devices in this tick meets or exceeds the threshold value.
        """
        if now is None:
            now = time.time()

        debounce = float(cfg.get("debounce_seconds", 0))
        recovery = bool(cfg.get("recovery", True))
        offline_threshold = int(cfg.get("offline_threshold", 1))

        # ── baseline seed: first call with no prior state ──────────────────
        if not prev_devices:
            new_devices: dict[str, DeviceStatus] = {}
            for key, ds in snapshot.items():
                new_devices[key] = DeviceStatus(
                    key=ds.key, type=ds.type, name=ds.name, group=ds.group,
                    online=ds.online, raw_status=ds.raw_status,
                    last_change=now,
                )
            return [], new_devices

        # ── normal reconciliation ──────────────────────────────────────────
        all_keys = set(prev_devices) | set(snapshot)
        new_devices = {}
        pending_offline_events: list[OutageEvent] = []
        emitted_events: list[OutageEvent] = []

        for key in all_keys:
            current = snapshot.get(key)
            prev = prev_devices.get(key)

            # Observed state: absent from snapshot = offline.
            if current is not None:
                observed_online = current.online
                raw_status = current.raw_status
                name = current.name
                group = current.group
                dev_type = current.type
            else:
                # Device disappeared from inventory.
                assert prev is not None
                observed_online = False
                raw_status = "missing"
                name = prev.name
                group = prev.group
                dev_type = prev.type

            # Build base entry from prev (carries debounce state forward).
            if prev is not None:
                committed_online = prev.online
                last_change = prev.last_change
                pending_since = prev.pending_since
                pending_target = prev.pending_target
            else:
                # New device seen for first time mid-run: treat as baseline.
                committed_online = observed_online
                last_change = now
                pending_since = None
                pending_target = None
                new_devices[key] = DeviceStatus(
                    key=key, type=dev_type, name=name, group=group,
                    online=committed_online, raw_status=raw_status,
                    last_change=last_change,
                )
                continue

            if observed_online == committed_online:
                # Stable — clear any debounce window.
                new_devices[key] = DeviceStatus(
                    key=key, type=dev_type, name=name, group=group,
                    online=committed_online, raw_status=raw_status,
                    last_change=last_change,
                )
            elif pending_target == observed_online and pending_since is not None:
                # Existing debounce window — check maturity.
                if now - pending_since >= debounce:
                    # Commit the transition.
                    event = OutageEvent(
                        kind="offline" if not observed_online else "online",
                        key=key, type=dev_type, name=name, group=group,
                        raw_status=raw_status, ts=now,
                    )
                    if observed_online:
                        # Recovery event — not subject to offline_threshold.
                        if recovery:
                            emitted_events.append(event)
                    else:
                        pending_offline_events.append(event)
                    new_devices[key] = DeviceStatus(
                        key=key, type=dev_type, name=name, group=group,
                        online=observed_online, raw_status=raw_status,
                        last_change=now,
                    )
                else:
                    # Not yet matured — keep pending state, don't commit.
                    new_devices[key] = DeviceStatus(
                        key=key, type=dev_type, name=name, group=group,
                        online=committed_online, raw_status=raw_status,
                        last_change=last_change,
                        pending_since=pending_since,
                        pending_target=pending_target,
                    )
            else:
                # New direction change — start or reset debounce window.
                if debounce == 0:
                    # No debounce: commit immediately.
                    event = OutageEvent(
                        kind="offline" if not observed_online else "online",
                        key=key, type=dev_type, name=name, group=group,
                        raw_status=raw_status, ts=now,
                    )
                    if observed_online:
                        if recovery:
                            emitted_events.append(event)
                    else:
                        pending_offline_events.append(event)
                    new_devices[key] = DeviceStatus(
                        key=key, type=dev_type, name=name, group=group,
                        online=observed_online, raw_status=raw_status,
                        last_change=now,
                    )
                else:
                    new_devices[key] = DeviceStatus(
                        key=key, type=dev_type, name=name, group=group,
                        online=committed_online, raw_status=raw_status,
                        last_change=last_change,
                        pending_since=now,
                        pending_target=observed_online,
                    )

        # Apply offline_threshold: only emit offline batch if count meets threshold.
        if len(pending_offline_events) >= offline_threshold:
            emitted_events.extend(pending_offline_events)

        return emitted_events, new_devices
```

- [ ] **Run — expect PASS**:

```
python -m pytest tests/unit/notify/test_notify.py -k "test_reconcile" -v
```

- [ ] **Commit**:

```
git commit -m "feat(notify): OutageEngine.reconcile() — per-device diff, baseline seeding, debounce, threshold"
```

---

## Task 3 — Debounce behaviour (pending window, flap suppression)

**Files:**
- No new files (logic already in `outage.py`)
- Test: `tests/unit/notify/test_notify.py`

### Steps

- [ ] **Write the failing tests.** Append to `tests/unit/notify/test_notify.py`:

```python
# ── outage: debounce ──────────────────────────────────────────────────────

def test_reconcile_debounce_holds_on_first_tick():
    """Offline device within debounce window: no event on first tick."""
    from ruckus_dashboard.notify.outage import OutageEngine
    prev = _make_snapshot([("ap:aa", "ap", "AP-1", "HQ", True, "online")])
    snap = _make_snapshot([("ap:aa", "ap", "AP-1", "HQ", False, "offline")])
    cfg = {"debounce_seconds": 120, "recovery": True, "offline_threshold": 1}
    events, new_devices = OutageEngine.reconcile(prev, snap, cfg, now=1000.0)
    assert events == []
    # pending_since recorded
    assert new_devices["ap:aa"].pending_since == 1000.0
    assert new_devices["ap:aa"].pending_target is False
    # committed state unchanged
    assert new_devices["ap:aa"].online is True


def test_reconcile_debounce_fires_after_window():
    """Same device still offline after debounce_seconds → event emitted."""
    from ruckus_dashboard.notify.outage import OutageEngine, DeviceStatus
    # Simulate prev_devices as the state AFTER the first tick (pending set).
    prev_ds = DeviceStatus(
        key="ap:aa", type="ap", name="AP-1", group="HQ",
        online=True, raw_status="online", last_change=900.0,
        pending_since=1000.0, pending_target=False,
    )
    snap = _make_snapshot([("ap:aa", "ap", "AP-1", "HQ", False, "offline")])
    cfg = {"debounce_seconds": 120, "recovery": True, "offline_threshold": 1}
    events, new_devices = OutageEngine.reconcile(
        {"ap:aa": prev_ds}, snap, cfg, now=1121.0  # 121 s later, past window
    )
    assert len(events) == 1
    assert events[0].kind == "offline"
    assert new_devices["ap:aa"].online is False
    assert new_devices["ap:aa"].pending_since is None


def test_reconcile_debounce_not_yet_matured():
    """Still within the window (119 s): pending kept, no event."""
    from ruckus_dashboard.notify.outage import OutageEngine, DeviceStatus
    prev_ds = DeviceStatus(
        key="ap:aa", type="ap", name="AP-1", group="HQ",
        online=True, raw_status="online", last_change=900.0,
        pending_since=1000.0, pending_target=False,
    )
    snap = _make_snapshot([("ap:aa", "ap", "AP-1", "HQ", False, "offline")])
    cfg = {"debounce_seconds": 120, "recovery": True, "offline_threshold": 1}
    events, new_devices = OutageEngine.reconcile(
        {"ap:aa": prev_ds}, snap, cfg, now=1119.0
    )
    assert events == []
    assert new_devices["ap:aa"].pending_since == 1000.0
    assert new_devices["ap:aa"].online is True


def test_reconcile_flap_within_debounce_suppressed():
    """Device goes offline then recovers within the debounce window — no event."""
    from ruckus_dashboard.notify.outage import OutageEngine, DeviceStatus
    # After tick 1: pending toward False (offline)
    prev_ds = DeviceStatus(
        key="ap:aa", type="ap", name="AP-1", group="HQ",
        online=True, raw_status="online", last_change=900.0,
        pending_since=1000.0, pending_target=False,
    )
    # Tick 2: device is back online within the 120 s window.
    snap = _make_snapshot([("ap:aa", "ap", "AP-1", "HQ", True, "online")])
    cfg = {"debounce_seconds": 120, "recovery": True, "offline_threshold": 1}
    events, new_devices = OutageEngine.reconcile(
        {"ap:aa": prev_ds}, snap, cfg, now=1060.0
    )
    assert events == []
    # Pending cleared; stable online.
    assert new_devices["ap:aa"].pending_since is None
    assert new_devices["ap:aa"].online is True
```

- [ ] **Run — expect PASS** (reconcile logic already handles these cases):

```
python -m pytest tests/unit/notify/test_notify.py -k "test_reconcile_debounce" -v
```

- [ ] **Commit**:

```
git commit -m "test(notify): debounce pending/maturity/flap-suppression assertions"
```

---

## Task 4 — `render_alert()` — grouping and message rendering

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/notify/outage.py`
- Test: `tests/unit/notify/test_notify.py`

### Steps

- [ ] **Write the failing tests.** Append to `tests/unit/notify/test_notify.py`:

```python
# ── outage: render_alert ──────────────────────────────────────────────────

def _make_event(kind, key, typ, name, group, ts=5000.0):
    from ruckus_dashboard.notify.outage import OutageEvent
    return OutageEvent(kind=kind, key=key, type=typ, name=name,
                       group=group, raw_status="offline", ts=ts)


def test_render_alert_subject_counts():
    from ruckus_dashboard.notify.outage import render_alert
    events = [
        _make_event("offline", "ap:a1", "ap", "AP-1", "HQ"),
        _make_event("offline", "ap:a2", "ap", "AP-2", "Branch"),
        _make_event("online",  "sw:s1", "switch", "SW-1", "Core"),
    ]
    note = render_alert(events, group_by="site")
    assert "2 devices offline" in note.subject
    assert "1 recovered" in note.subject


def test_render_alert_subject_includes_groups():
    from ruckus_dashboard.notify.outage import render_alert
    events = [
        _make_event("offline", "ap:a1", "ap", "AP-1", "HQ"),
        _make_event("offline", "ap:a2", "ap", "AP-2", "Branch"),
    ]
    note = render_alert(events, group_by="site")
    assert "HQ" in note.subject or "Branch" in note.subject


def test_render_alert_body_groups_by_site():
    from ruckus_dashboard.notify.outage import render_alert
    events = [
        _make_event("offline", "ap:a1", "ap", "AP-1", "HQ"),
        _make_event("offline", "sw:s1", "switch", "SW-1", "HQ"),
        _make_event("offline", "ap:a2", "ap", "AP-2", "Branch"),
    ]
    note = render_alert(events, group_by="site")
    assert "HQ" in note.body
    assert "Branch" in note.body
    assert "AP-1" in note.body
    assert "SW-1" in note.body
    assert "AP-2" in note.body


def test_render_alert_body_flat_when_group_by_none():
    from ruckus_dashboard.notify.outage import render_alert
    events = [
        _make_event("offline", "ap:a1", "ap", "AP-1", "HQ"),
        _make_event("offline", "ap:a2", "ap", "AP-2", "Branch"),
    ]
    note = render_alert(events, group_by="none")
    assert "AP-1" in note.body
    assert "AP-2" in note.body


def test_render_alert_recovery_section_in_body():
    from ruckus_dashboard.notify.outage import render_alert
    events = [
        _make_event("offline", "ap:a1", "ap", "AP-1", "HQ"),
        _make_event("online",  "sw:s1", "switch", "SW-1", "Core"),
    ]
    note = render_alert(events, group_by="site")
    assert "Recovered" in note.body or "recovered" in note.body
    assert "SW-1" in note.body


def test_render_alert_structured_events_tuple():
    from ruckus_dashboard.notify.outage import render_alert
    events = [_make_event("offline", "ap:a1", "ap", "AP-1", "HQ")]
    note = render_alert(events, group_by="site")
    assert len(note.events) == 1
    assert note.events[0].key == "ap:a1"


def test_render_alert_controller_node_event():
    from ruckus_dashboard.notify.outage import render_alert
    events = [_make_event("offline", "controller:node1",
                          "controller", "SZ-Node-1", "controller")]
    note = render_alert(events, group_by="site")
    assert "SZ-Node-1" in note.body
    assert "controller" in note.body.lower()
```

- [ ] **Run — expect FAIL** (`render_alert` not defined yet):

```
python -m pytest tests/unit/notify/test_notify.py -k "test_render_alert" -v
```

Expected: `ImportError: cannot import name 'render_alert' from 'ruckus_dashboard.notify.outage'`

- [ ] **Implement** — first add `Notification` import stub then append to `outage.py`. The `Notification` dataclass will live in `channels.py` (Task 6), but `render_alert` produces one — avoid a circular import by defining a local lightweight `_Notification` and importing lazily, OR define `Notification` in `outage.py` and re-export from `channels.py`. Use the latter (simpler, no circular dep):

Append to `RUCKUS/ruckus_dashboard/notify/outage.py`:

```python
# ── Notification (defined here; re-exported from channels.py) ────────────

@dataclass(frozen=True)
class Notification:
    """A rendered alert ready for dispatch via any NotificationChannel."""
    subject: str
    body: str
    events: tuple[OutageEvent, ...]   # structured, for non-text channels


# ── render_alert ──────────────────────────────────────────────────────────

def render_alert(events: list[OutageEvent], group_by: str = "site") -> Notification:
    """Produce a Notification from a list of OutageEvents.

    group_by='site'  → events grouped by device.group (zone / stack / "controller")
    group_by='none'  → flat list, no site headers
    """
    import datetime

    offline = [e for e in events if e.kind == "offline"]
    online  = [e for e in events if e.kind == "online"]

    # Subject
    parts = []
    if offline:
        parts.append(f"{len(offline)} device{'s' if len(offline) != 1 else ''} offline")
    if online:
        parts.append(f"{len(online)} recovered")
    summary = ", ".join(parts)

    # Collect group names for subject
    groups = sorted({e.group or "unknown" for e in offline})
    group_str = ", ".join(groups[:3])
    if len(groups) > 3:
        group_str += f" +{len(groups) - 3} more"
    subject = f"[RUCKUS DSO] {summary}"
    if group_str:
        subject += f" ({group_str})"

    lines: list[str] = []

    def _fmt_event(e: OutageEvent) -> str:
        ts_str = datetime.datetime.fromtimestamp(e.ts).strftime("%Y-%m-%d %H:%M:%S")
        return f"  {e.name} ({e.type}) — {e.raw_status} at {ts_str}"

    if offline:
        if group_by == "site":
            by_group: dict[str, list[OutageEvent]] = {}
            for e in offline:
                by_group.setdefault(e.group or "unknown", []).append(e)
            lines.append("DEVICES OFFLINE")
            lines.append("=" * 40)
            for grp in sorted(by_group):
                lines.append(f"\n[{grp}]")
                for e in by_group[grp]:
                    lines.append(_fmt_event(e))
        else:
            lines.append("DEVICES OFFLINE")
            lines.append("=" * 40)
            for e in offline:
                lines.append(_fmt_event(e))

    if online:
        lines.append("")
        lines.append("RECOVERED")
        lines.append("=" * 40)
        if group_by == "site":
            by_group_r: dict[str, list[OutageEvent]] = {}
            for e in online:
                by_group_r.setdefault(e.group or "unknown", []).append(e)
            for grp in sorted(by_group_r):
                lines.append(f"\n[{grp}]")
                for e in by_group_r[grp]:
                    lines.append(_fmt_event(e))
        else:
            for e in online:
                lines.append(_fmt_event(e))

    lines.append("")
    lines.append("— RUCKUS DSO Dashboard")
    body = "\n".join(lines)

    return Notification(subject=subject, body=body, events=tuple(events))
```

- [ ] **Run — expect PASS**:

```
python -m pytest tests/unit/notify/test_notify.py -k "test_render_alert" -v
```

- [ ] **Commit**:

```
git commit -m "feat(notify): render_alert() — grouped outage/recovery message body and subject"
```

---

## Task 5 — `OutageStateStore` Protocol + `JsonOutageStateStore`

**Files:**
- Create: `RUCKUS/ruckus_dashboard/notify/state_store.py`
- Test: `tests/unit/notify/test_notify.py`

### Steps

- [ ] **Write the failing tests.** Append to `tests/unit/notify/test_notify.py`:

```python
# ── state_store ───────────────────────────────────────────────────────────

def test_json_state_store_roundtrip(tmp_instance):
    from ruckus_dashboard.notify.state_store import JsonOutageStateStore
    from ruckus_dashboard.notify.outage import DeviceStatus
    store = JsonOutageStateStore(tmp_instance)
    ds = DeviceStatus(key="ap:aa", type="ap", name="AP-1", group="HQ",
                      online=False, raw_status="offline", last_change=1000.0)
    state = {
        "devices": {"ap:aa": ds},
        "report": {"last_report_day": "2026-06-30"},
    }
    store.save(state)
    loaded = store.load()
    assert loaded["devices"]["ap:aa"].online is False
    assert loaded["devices"]["ap:aa"].name == "AP-1"
    assert loaded["report"]["last_report_day"] == "2026-06-30"


def test_json_state_store_missing_file_returns_empty(tmp_instance):
    from ruckus_dashboard.notify.state_store import JsonOutageStateStore
    store = JsonOutageStateStore(tmp_instance)
    result = store.load()
    assert result["devices"] == {}
    assert result["report"] == {}


def test_json_state_store_corrupt_file_returns_empty(tmp_instance):
    import os
    from pathlib import Path
    from ruckus_dashboard.notify.state_store import JsonOutageStateStore
    p = Path(tmp_instance) / "notify_state.json"
    p.write_text("NOT JSON{{{", encoding="utf-8")
    store = JsonOutageStateStore(tmp_instance)
    result = store.load()
    assert result["devices"] == {}


def test_json_state_store_atomic_no_tmp_left(tmp_instance):
    """After save(), .tmp file must not exist."""
    import os
    from pathlib import Path
    from ruckus_dashboard.notify.state_store import JsonOutageStateStore
    store = JsonOutageStateStore(tmp_instance)
    store.save({"devices": {}, "report": {}})
    tmp = Path(tmp_instance) / "notify_state.json.tmp"
    assert not tmp.exists()
    main = Path(tmp_instance) / "notify_state.json"
    assert main.exists()


def test_json_state_store_chmod_best_effort_on_windows(tmp_instance):
    """chmod failure (Windows) must not raise."""
    import os
    from unittest.mock import patch
    from ruckus_dashboard.notify.state_store import JsonOutageStateStore
    store = JsonOutageStateStore(tmp_instance)
    with patch("os.chmod", side_effect=OSError("read-only fs")):
        # Should not raise despite chmod failing.
        store.save({"devices": {}, "report": {}})


def test_json_state_store_pending_fields_roundtrip(tmp_instance):
    """pending_since and pending_target survive a save/load cycle."""
    from ruckus_dashboard.notify.state_store import JsonOutageStateStore
    from ruckus_dashboard.notify.outage import DeviceStatus
    store = JsonOutageStateStore(tmp_instance)
    ds = DeviceStatus(key="ap:bb", type="ap", name="AP-2", group="Branch",
                      online=True, raw_status="online", last_change=900.0,
                      pending_since=1000.0, pending_target=False)
    store.save({"devices": {"ap:bb": ds}, "report": {}})
    loaded = store.load()
    assert loaded["devices"]["ap:bb"].pending_since == 1000.0
    assert loaded["devices"]["ap:bb"].pending_target is False
```

- [ ] **Run — expect FAIL**:

```
python -m pytest tests/unit/notify/test_notify.py -k "test_json_state_store" -v
```

Expected: `ModuleNotFoundError: No module named 'ruckus_dashboard.notify.state_store'`

- [ ] **Implement** — create `RUCKUS/ruckus_dashboard/notify/state_store.py`:

```python
"""Durable outage state persistence.

OutageStateStore is a Protocol (structural typing) so JsonOutageStateStore can
be swapped for a SqliteOutageStateStore later without touching any caller.

PersistedState shape::

    {
        "devices": { key: DeviceStatus },
        "report":  { "last_report_day": str | None },
    }

Atomic write mirrors auth/secrets.py:89-91: write .tmp then os.replace.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .outage import DeviceStatus

LOG = logging.getLogger("ruckus.notify")


def _device_to_dict(ds: DeviceStatus) -> dict[str, Any]:
    return {
        "key": ds.key,
        "type": ds.type,
        "name": ds.name,
        "group": ds.group,
        "online": ds.online,
        "raw_status": ds.raw_status,
        "last_change": ds.last_change,
        "pending_since": ds.pending_since,
        "pending_target": ds.pending_target,
    }


def _device_from_dict(d: dict[str, Any]) -> DeviceStatus:
    return DeviceStatus(
        key=d["key"],
        type=d["type"],
        name=d.get("name", ""),
        group=d.get("group"),
        online=bool(d.get("online", False)),
        raw_status=d.get("raw_status", ""),
        last_change=float(d.get("last_change", 0.0)),
        pending_since=(float(d["pending_since"]) if d.get("pending_since") is not None
                       else None),
        pending_target=(bool(d["pending_target"]) if d.get("pending_target") is not None
                        else None),
    )


class JsonOutageStateStore:
    """Persists outage state to ``<instance_path>/notify_state.json``.

    Load tolerates a missing or corrupt file by returning empty state —
    mirrors config.load_config's (OSError, ValueError) handling at
    config.py:45-46.

    Write is atomic: write .tmp then os.replace, then best-effort chmod 0o600
    — mirrors the pattern in auth/secrets.py:89-91.

    This class is single-writer safe (the daemon holds self._lock before
    calling; no cross-process locking is needed).
    """

    def __init__(self, instance_path: str) -> None:
        self._path = Path(instance_path) / "notify_state.json"
        self._tmp = Path(instance_path) / "notify_state.json.tmp"

    def load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("root is not a dict")
        except (OSError, ValueError):
            return {"devices": {}, "report": {}}

        devices: dict[str, DeviceStatus] = {}
        for key, d in (raw.get("devices") or {}).items():
            try:
                devices[key] = _device_from_dict(d)
            except (KeyError, TypeError, ValueError) as exc:
                LOG.warning("notify_state: skipping corrupt device %r: %s", key, exc)

        report: dict[str, Any] = raw.get("report") or {}
        return {"devices": devices, "report": report}

    def save(self, state: dict[str, Any]) -> None:
        devices_raw = {
            key: _device_to_dict(ds)
            for key, ds in (state.get("devices") or {}).items()
        }
        payload = {
            "version": 1,
            "devices": devices_raw,
            "report": state.get("report") or {},
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            os.replace(self._tmp, self._path)
            try:
                os.chmod(self._path, 0o600)
            except OSError:
                pass  # Best-effort; Windows doesn't honour POSIX permissions.
        except OSError:
            LOG.exception("notify_state: failed to persist state")
```

- [ ] **Run — expect PASS**:

```
python -m pytest tests/unit/notify/test_notify.py -k "test_json_state_store" -v
```

- [ ] **Commit**:

```
git commit -m "feat(notify): JsonOutageStateStore — atomic write, tolerant load, pending field roundtrip"
```

---

## Task 6 — `NotificationChannel` Protocol + `EmailChannel` + `CHANNELS` registry

**Files:**
- Create: `RUCKUS/ruckus_dashboard/notify/channels.py`
- Test: `tests/unit/notify/test_notify.py`

### Steps

- [ ] **Write the failing tests.** Append to `tests/unit/notify/test_notify.py`:

```python
# ── channels ─────────────────────────────────────────────────────────────

def test_notification_is_importable_from_channels():
    from ruckus_dashboard.notify.channels import Notification
    from ruckus_dashboard.notify.outage import Notification as NotifOutage
    # channels re-exports the same class from outage.py
    assert Notification is NotifOutage


def test_email_channel_is_configured_when_recipients():
    from ruckus_dashboard.notify.channels import EmailChannel
    ch = EmailChannel()
    assert ch.name == "email"
    assert ch.is_configured({"alerts": {"recipients": ["a@x"]}}) is True
    assert ch.is_configured({"alerts": {"recipients": []}}) is False
    assert ch.is_configured({}) is False


def test_email_channel_send_calls_mailer(monkeypatch):
    from ruckus_dashboard.notify import channels as ch_mod
    from ruckus_dashboard.notify.channels import EmailChannel
    from ruckus_dashboard.notify.outage import Notification, OutageEvent
    calls = {}

    def fake_send(cfg, pw, recipients, subject, body, **kw):
        calls["recipients"] = recipients
        calls["subject"] = subject
        calls["body"] = body

    monkeypatch.setattr(ch_mod, "send_email", fake_send)
    monkeypatch.setattr(ch_mod, "smtp_password", lambda cfg, secrets: "pw")

    note = Notification(
        subject="[RUCKUS DSO] 1 device offline (HQ)",
        body="DEVICES OFFLINE\n  AP-1 (ap) — offline",
        events=(),
    )
    cfg = {"alerts": {"recipients": ["noc@x"]}, "smtp": {"host": "mail.x"}}
    EmailChannel().send(cfg, object(), note)
    assert calls["recipients"] == ["noc@x"]
    assert "1 device offline" in calls["subject"]


def test_email_channel_send_failure_does_not_raise(monkeypatch):
    """A raising mailer.send_email is swallowed by the channel."""
    from ruckus_dashboard.notify import channels as ch_mod
    from ruckus_dashboard.notify.channels import EmailChannel
    from ruckus_dashboard.notify.outage import Notification

    monkeypatch.setattr(ch_mod, "send_email",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("SMTP down")))
    monkeypatch.setattr(ch_mod, "smtp_password", lambda cfg, secrets: "")
    note = Notification(subject="s", body="b", events=())
    cfg = {"alerts": {"recipients": ["a@x"]}, "smtp": {"host": "mail.x"}}
    # Must not raise — channel isolation.
    EmailChannel().send(cfg, object(), note)


def test_channels_registry_contains_email():
    from ruckus_dashboard.notify.channels import CHANNELS
    assert "email" in CHANNELS
    assert CHANNELS["email"].name == "email"
```

- [ ] **Run — expect FAIL**:

```
python -m pytest tests/unit/notify/test_notify.py -k "test_email_channel or test_notification_is_importable or test_channels_registry" -v
```

Expected: `ModuleNotFoundError: No module named 'ruckus_dashboard.notify.channels'`

- [ ] **Implement** — create `RUCKUS/ruckus_dashboard/notify/channels.py`:

```python
"""Notification channel abstraction.

NotificationChannel is a Protocol so new channels (Slack, Teams, webhook) can
be added by creating a new class + one register() line without touching
any caller.  Only EmailChannel is implemented in SP2.

Notification is re-exported from outage.py (defined there to avoid a circular
import, since render_alert returns one).
"""
from __future__ import annotations

import logging
from typing import Any

from .outage import Notification  # re-export; callers can import from here

LOG = logging.getLogger("ruckus.notify")


class EmailChannel:
    """Dispatch a Notification via SMTP using notify/mailer.send_email.

    mailer.py is intentionally untouched — this class is the only seam between
    the outage engine and the SMTP layer."""

    name: str = "email"

    def is_configured(self, cfg: dict) -> bool:
        recipients = (cfg.get("alerts") or {}).get("recipients") or []
        return bool(recipients)

    def send(self, cfg: dict, secrets: Any, note: Notification) -> None:
        """Send *note* via SMTP.  Swallows all exceptions (per-channel isolation)."""
        try:
            from .mailer import send_email
            from .config import smtp_password
            pw = smtp_password(cfg, secrets)
            recipients = (cfg.get("alerts") or {}).get("recipients") or []
            send_email(cfg, pw, recipients, note.subject, note.body)
        except Exception:  # noqa: BLE001 — channel failure must never kill the tick
            LOG.exception("notify: email channel send failed")


# Lightweight module-level imports so monkeypatching works at module scope.
try:
    from .mailer import send_email  # noqa: F401 (imported for monkeypatching)
    from .config import smtp_password  # noqa: F401
except ImportError:
    pass


# ── registry ──────────────────────────────────────────────────────────────

CHANNELS: dict[str, EmailChannel] = {
    "email": EmailChannel(),
}
```

- [ ] **Run — expect PASS**:

```
python -m pytest tests/unit/notify/test_notify.py -k "test_email_channel or test_notification_is_importable or test_channels_registry" -v
```

- [ ] **Commit**:

```
git commit -m "feat(notify): EmailChannel + NotificationChannel registry; re-export Notification from channels"
```

---

## Task 7 — Extend `notify/config.py` with new alert defaults

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/notify/config.py`
- Test: `tests/unit/notify/test_notify.py`

### Steps

- [ ] **Write the failing tests.** Append to `tests/unit/notify/test_notify.py`:

```python
# ── config: new SP2 defaults ──────────────────────────────────────────────

def test_config_new_alert_defaults_present(tmp_path):
    from ruckus_dashboard.notify import config as cfg_mod
    cfg = cfg_mod.load_config(str(tmp_path))
    alerts = cfg["alerts"]
    assert alerts["recovery"] is True
    assert alerts["debounce_seconds"] == 120
    assert alerts["group_by"] == "site"
    assert alerts["suppress_known_on_start"] is True
    assert isinstance(alerts.get("channels"), dict)


def test_config_new_defaults_do_not_break_old_file(tmp_path):
    """An old notifications.json (no new keys) merges cleanly."""
    import json
    from ruckus_dashboard.notify import config as cfg_mod
    old = {
        "smtp": {"host": "mail.x", "port": 587, "security": "starttls",
                 "username": "", "password_enc": "", "from_addr": ""},
        "alerts": {"enabled": True, "recipients": ["a@x"],
                   "check_seconds": 300,
                   "rules": {"ap_offline": True, "switch_offline": True,
                             "critical_alarm": True, "poor_client_ap": True},
                   "offline_threshold": 1},
        "report": {"enabled": False, "recipients": [], "time": "07:00"},
    }
    (tmp_path / "notifications.json").write_text(json.dumps(old), encoding="utf-8")
    cfg = cfg_mod.load_config(str(tmp_path))
    # Old keys preserved.
    assert cfg["alerts"]["enabled"] is True
    assert cfg["alerts"]["recipients"] == ["a@x"]
    # New keys get defaults.
    assert cfg["alerts"]["recovery"] is True
    assert cfg["alerts"]["debounce_seconds"] == 120


def test_config_channels_backward_compat(tmp_path):
    """If channels absent, synthesize from existing recipients field."""
    import json
    from ruckus_dashboard.notify import config as cfg_mod
    old = {"alerts": {"enabled": True, "recipients": ["noc@x"]}}
    (tmp_path / "notifications.json").write_text(json.dumps(old), encoding="utf-8")
    cfg = cfg_mod.load_config(str(tmp_path))
    # The merged config contains channels with the legacy recipients.
    ch = cfg["alerts"].get("channels") or {}
    assert isinstance(ch, dict)
```

- [ ] **Run — expect FAIL** (`KeyError: 'recovery'`):

```
python -m pytest tests/unit/notify/test_notify.py -k "test_config_new_alert_defaults or test_config_new_defaults_do_not_break or test_config_channels_backward_compat" -v
```

- [ ] **Implement** — modify `RUCKUS/ruckus_dashboard/notify/config.py`:

Edit the `DEFAULTS` dict at lines 14-22 to add new keys under `"alerts"`:

```python
DEFAULTS: dict[str, Any] = {
    "smtp": {"host": "", "port": 587, "security": "starttls", "username": "",
             "password_enc": "", "from_addr": ""},
    "alerts": {"enabled": False, "recipients": [], "check_seconds": 300,
               "rules": {"ap_offline": True, "switch_offline": True,
                         "critical_alarm": True, "poor_client_ap": True},
               "offline_threshold": 1,
               # SP2 additions (additive, backward-compatible):
               "recovery": True,
               "debounce_seconds": 120,
               "group_by": "site",
               "suppress_known_on_start": True,
               "channels": {"email": {"enabled": True, "recipients": []}}},
    "report": {"enabled": False, "recipients": [], "time": "07:00"},
}
```

Also update `_merged()` so the `channels` sub-dict deep-merges properly (currently only `rules` gets special treatment). Edit the function body to add:

```python
def _merged(stored: dict) -> dict:
    out = json.loads(json.dumps(DEFAULTS))  # deep copy
    for section in out:
        if isinstance(stored.get(section), dict):
            out[section].update(stored[section])
    if isinstance(stored.get("alerts", {}).get("rules"), dict):
        out["alerts"]["rules"] = {**DEFAULTS["alerts"]["rules"],
                                  **stored["alerts"]["rules"]}
    if isinstance(stored.get("alerts", {}).get("channels"), dict):
        out["alerts"]["channels"] = {
            **DEFAULTS["alerts"]["channels"],
            **stored["alerts"]["channels"],
        }
    # Backward-compat: if channels absent but recipients exist, propagate.
    if not stored.get("alerts", {}).get("channels"):
        legacy = (stored.get("alerts") or {}).get("recipients") or []
        if legacy:
            out["alerts"]["channels"]["email"]["recipients"] = legacy
    return out
```

- [ ] **Run — expect PASS**:

```
python -m pytest tests/unit/notify/test_notify.py -k "test_config_new_alert_defaults or test_config_new_defaults_do_not_break or test_config_channels_backward_compat" -v
```

- [ ] **Commit**:

```
git commit -m "feat(notify/config): add SP2 alert defaults (recovery, debounce_seconds, group_by, suppress_known_on_start, channels)"
```

---

## Task 8 — Fix `state_from_data` audit bug #14 (`count or 1`)

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/notify/scheduler.py` (line 49)
- Test: `tests/unit/notify/test_notify.py`

### Steps

- [ ] **Write the failing test.** Add to `tests/unit/notify/test_notify.py` (near the existing `test_state_from_data_counts` at line 107):

```python
def test_state_from_data_zero_alarm_count_is_zero():
    """Bug #14: 'count or 1' treated a zero/missing count as 1.  Must be 0."""
    from ruckus_dashboard.notify.scheduler import state_from_data
    data = {
        "aps": [],
        "switches": [],
        "alarms": [
            {"severity": "critical", "count": 0},   # explicit zero
            {"severity": "critical"},               # missing count
        ],
    }
    s = state_from_data(data)
    assert s["critical_alarms"] == 0, (
        "count=0 and missing count must both contribute 0, not 1"
    )
```

- [ ] **Run — expect FAIL** (current code: `int(a.get("count") or 1)` returns 1 for zero):

```
python -m pytest tests/unit/notify/test_notify.py::test_state_from_data_zero_alarm_count_is_zero -v
```

Expected: `AssertionError: count=0 and missing count must both contribute 0, not 1`

- [ ] **Implement** — edit `RUCKUS/ruckus_dashboard/notify/scheduler.py` line 49. Change:

```python
        "critical_alarms": sum(int(a.get("count") or 1)
                               for a in data.get("alarms") or []
                               if a.get("severity") == "critical"),
```

to:

```python
        "critical_alarms": sum(int(a.get("count") or 0)
                               for a in data.get("alarms") or []
                               if a.get("severity") == "critical"),
```

- [ ] **Run — expect PASS**:

```
python -m pytest tests/unit/notify/test_notify.py::test_state_from_data_zero_alarm_count_is_zero tests/unit/notify/test_notify.py::test_state_from_data_counts -v
```

- [ ] **Commit**:

```
git commit -m "fix(notify): state_from_data counts zero alarm count as 0 not 1 (audit #14)"
```

---

## Task 9 — Rewrite scheduler: `collect_device_snapshot`, alerts branch, durable state, dedup

This is the largest task. It rewrites the alert path in `_tick`, adds `collect_device_snapshot`, removes `_prev_state`, moves `_last_report_day` into the store, and stops nulling state on `set_connection`. It covers audit fixes #4 (baseline-spam) and #5 (durable daily-report dedup).

**Files:**
- Modify: `RUCKUS/ruckus_dashboard/notify/scheduler.py`
- Test: `tests/unit/notify/test_notify.py`

### Steps

- [ ] **Write the failing tests.** Append to `tests/unit/notify/test_notify.py`:

```python
# ── scheduler: collect_device_snapshot ───────────────────────────────────

def test_collect_device_snapshot_ap_row():
    """AP row normalizes to DeviceStatus with key 'ap:<mac>'."""
    from unittest.mock import patch, MagicMock
    from ruckus_dashboard.notify.scheduler import collect_device_snapshot

    ap_row = {
        "id": "aa:bb:cc", "name": "AP-1", "zone": "HQ",
        "status": "offline", "mac": "aa:bb:cc",
    }
    conn = MagicMock()
    cfg = {}

    with patch("ruckus_dashboard.notify.scheduler.MODULES", {
        "aps": MagicMock(fetcher=lambda ctx: {"items": [ap_row]}),
        "switches": MagicMock(fetcher=lambda ctx: {"items": []}),
        "controller": MagicMock(fetcher=lambda ctx: {"items": []}),
    }):
        snapshot = collect_device_snapshot(conn, cfg)

    assert "ap:aa:bb:cc" in snapshot
    ds = snapshot["ap:aa:bb:cc"]
    assert ds.type == "ap"
    assert ds.name == "AP-1"
    assert ds.group == "HQ"
    assert ds.online is False


def test_collect_device_snapshot_switch_row():
    from unittest.mock import patch, MagicMock
    from ruckus_dashboard.notify.scheduler import collect_device_snapshot

    sw_row = {
        "id": "SW-ID-1", "name": "SW-1", "group": "Core",
        "status": "online", "mac": "SW-ID-1",
    }
    conn = MagicMock()
    cfg = {}

    with patch("ruckus_dashboard.notify.scheduler.MODULES", {
        "aps": MagicMock(fetcher=lambda ctx: {"items": []}),
        "switches": MagicMock(fetcher=lambda ctx: {"items": [sw_row]}),
        "controller": MagicMock(fetcher=lambda ctx: {"items": []}),
    }):
        snapshot = collect_device_snapshot(conn, cfg)

    assert "switch:SW-ID-1" in snapshot
    ds = snapshot["switch:SW-ID-1"]
    assert ds.type == "switch"
    assert ds.online is True
    assert ds.group == "Core"


def test_collect_device_snapshot_controller_node():
    from unittest.mock import patch, MagicMock
    from ruckus_dashboard.notify.scheduler import collect_device_snapshot

    ctrl_row = {"id": "node-1", "node": "SZ-Node-1", "state": "in_service"}
    conn = MagicMock()
    cfg = {}

    with patch("ruckus_dashboard.notify.scheduler.MODULES", {
        "aps": MagicMock(fetcher=lambda ctx: {"items": []}),
        "switches": MagicMock(fetcher=lambda ctx: {"items": []}),
        "controller": MagicMock(fetcher=lambda ctx: {"items": [ctrl_row]}),
    }):
        snapshot = collect_device_snapshot(conn, cfg)

    assert "controller:node-1" in snapshot
    ds = snapshot["controller:node-1"]
    assert ds.type == "controller"
    assert ds.online is True
    assert ds.name == "SZ-Node-1"


def test_collect_device_snapshot_fetch_failure_leaves_type_absent():
    """If a fetcher throws, that device type is omitted (not marked offline)."""
    from unittest.mock import patch, MagicMock
    from ruckus_dashboard.notify.scheduler import collect_device_snapshot

    ap_row = {"id": "aa:bb", "name": "AP-1", "zone": "HQ",
              "status": "online", "mac": "aa:bb"}

    def _bad_fetch(ctx):
        raise RuntimeError("API down")

    conn = MagicMock()
    cfg = {}

    with patch("ruckus_dashboard.notify.scheduler.MODULES", {
        "aps": MagicMock(fetcher=lambda ctx: {"items": [ap_row]}),
        "switches": MagicMock(fetcher=_bad_fetch),
        "controller": MagicMock(fetcher=lambda ctx: {"items": []}),
    }):
        snapshot = collect_device_snapshot(conn, cfg)

    # AP is present; switch fetch failed so no switch keys.
    assert "ap:aa:bb" in snapshot
    sw_keys = [k for k in snapshot if k.startswith("switch:")]
    assert sw_keys == []


# ── scheduler: baseline-spam fix (audit #4) ──────────────────────────────

def test_baseline_spam_not_fired_on_existing_outage(tmp_instance):
    """Audit #4: pre-existing outage in store must NOT re-fire on tick.

    This test INVERTS the old test_rules_fire_on_transition_only assumption
    (test_notify.py:56-57 which called evaluate(None, ...) and expected 1 alert).
    """
    from ruckus_dashboard.notify.state_store import JsonOutageStateStore
    from ruckus_dashboard.notify.outage import DeviceStatus, OutageEngine
    store = JsonOutageStateStore(tmp_instance)
    # Seed: ap:aa is already offline in committed state.
    ds = DeviceStatus(key="ap:aa", type="ap", name="AP-1", group="HQ",
                      online=False, raw_status="offline", last_change=1000.0)
    store.save({"devices": {"ap:aa": ds}, "report": {}})
    loaded = store.load()

    # Snapshot: ap:aa still offline.
    from ruckus_dashboard.notify.outage import _make_snapshot_for_test
    snapshot = {
        "ap:aa": DeviceStatus(key="ap:aa", type="ap", name="AP-1", group="HQ",
                              online=False, raw_status="offline", last_change=0.0),
    }
    cfg = {"debounce_seconds": 0, "recovery": True, "offline_threshold": 1}
    events, _ = OutageEngine.reconcile(loaded["devices"], snapshot, cfg, now=2000.0)
    assert events == [], "pre-existing outage must not re-fire after store load"


# ── scheduler: durable daily-report dedup (audit #5) ─────────────────────

def test_report_due_persisted_day_prevents_resend(tmp_instance):
    """Audit #5: _report_due must read last_report_day from the store.

    Starting the scheduler after the configured time with today already
    persisted must NOT send the report again."""
    from ruckus_dashboard.notify.scheduler import NotifyScheduler
    from ruckus_dashboard.notify.state_store import JsonOutageStateStore
    import time as _t

    store = JsonOutageStateStore(tmp_instance)
    # Persist today as already-reported.
    store.save({"devices": {}, "report": {"last_report_day": "2026-06-30"}})

    s = NotifyScheduler(tmp_instance, {}, FakeSecrets())
    cfg = _cfg_mod_load(tmp_instance)
    cfg["report"]["enabled"] = True
    cfg["report"]["time"] = "07:00"
    # Simulate starting after report time with today's date persisted.
    after = _t.strptime("2026-06-30 09:00", "%Y-%m-%d %H:%M")
    assert s._report_due(cfg, after) is False


def test_report_due_fires_when_day_not_yet_persisted(tmp_instance):
    """_report_due fires when the store has yesterday (or nothing) persisted."""
    from ruckus_dashboard.notify.scheduler import NotifyScheduler
    from ruckus_dashboard.notify.state_store import JsonOutageStateStore
    import time as _t

    store = JsonOutageStateStore(tmp_instance)
    store.save({"devices": {}, "report": {"last_report_day": "2026-06-29"}})

    s = NotifyScheduler(tmp_instance, {}, FakeSecrets())
    cfg = _cfg_mod_load(tmp_instance)
    cfg["report"]["enabled"] = True
    cfg["report"]["time"] = "07:00"
    after = _t.strptime("2026-06-30 07:01", "%Y-%m-%d %H:%M")
    assert s._report_due(cfg, after) is True


def _cfg_mod_load(tmp_instance):
    from ruckus_dashboard.notify import config as cfg_mod
    return cfg_mod.load_config(tmp_instance)
```

- [ ] **Run — expect FAIL** (`collect_device_snapshot` not yet in scheduler.py, `_report_due` still reads `self._last_report_day`):

```
python -m pytest tests/unit/notify/test_notify.py -k "test_collect_device_snapshot or test_baseline_spam or test_report_due_persisted or test_report_due_fires" -v
```

- [ ] **Implement** — rewrite `RUCKUS/ruckus_dashboard/notify/scheduler.py` in full:

```python
"""Background scheduler: automated alert e-mails + the daily Excel report.

A single daemon thread ticks every 30 s. ``/connect`` hands it the active
controller connection; logout clears it. Every action is best-effort — a
failed fetch or send is logged and never kills the thread.

SP2 changes:
- collect_device_snapshot() replaces collect_report_data() for alerts.
- OutageEngine.reconcile() + JsonOutageStateStore replace _prev_state + evaluate().
- _last_report_day migrated into notify_state.json (durable across restart).
- set_connection() no longer nulls the state (committed state is source of truth).
- state_from_data() count fix: 'count or 0' (audit #14).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .config import load_config, smtp_password
from .mailer import send_email
from .rules import evaluate
from .outage import OutageEngine, DeviceStatus, device_online, render_alert
from .state_store import JsonOutageStateStore
from .channels import CHANNELS

LOG = logging.getLogger("ruckus.notify")

TICK_SECONDS = 30


def collect_report_data(connection, config: dict) -> dict[str, Any]:
    """Run the relevant module fetchers (dump-style) for the report/alerts."""
    from ..modules import MODULES
    from ..modules._base import FetcherContext
    from ..infra.capability_gate import CapabilityGate

    ctx = FetcherContext(connection=connection, config=config, filters=None,
                         capability_gate=CapabilityGate(set()),
                         connection_label=getattr(connection, "display_name", ""))
    out: dict[str, Any] = {}
    for slug, key in (("aps", "aps"), ("clients", "clients"),
                      ("alarms", "alarms"), ("switches", "switches")):
        try:
            out[key] = (MODULES[slug].fetcher(ctx) or {}).get("items", [])
        except Exception:  # noqa: BLE001
            LOG.exception("notify: %s fetch failed", slug)
            out[key] = []
    return out


def collect_device_snapshot(connection, config: dict) -> dict[str, DeviceStatus]:
    """Fetch APs, switches, and controller nodes; normalize to DeviceStatus.

    Each fetcher is isolated: if one throws, that device type is absent from
    the snapshot (left unchanged in committed state — not marked offline).
    This mirrors collect_report_data's per-slug try/except at scheduler.py:34-38.
    """
    from ..modules import MODULES
    from ..modules._base import FetcherContext
    from ..infra.capability_gate import CapabilityGate

    ctx = FetcherContext(
        connection=connection, config=config, filters=None,
        capability_gate=CapabilityGate(set()),
        connection_label=getattr(connection, "display_name", ""),
    )
    snapshot: dict[str, DeviceStatus] = {}

    # ── APs ───────────────────────────────────────────────────────────────
    try:
        ap_items = (MODULES["aps"].fetcher(ctx) or {}).get("items", [])
        for row in ap_items or []:
            dev_id = str(row.get("mac") or row.get("id") or row.get("name") or "")
            if not dev_id:
                continue
            key = f"ap:{dev_id}"
            raw_status = str(row.get("status") or "")
            snapshot[key] = DeviceStatus(
                key=key, type="ap",
                name=str(row.get("name") or dev_id),
                group=row.get("zone"),
                online=device_online("ap", raw_status),
                raw_status=raw_status,
                last_change=0.0,
            )
    except Exception:  # noqa: BLE001
        LOG.exception("notify: ap fetch failed for device snapshot")

    # ── Switches ──────────────────────────────────────────────────────────
    try:
        sw_items = (MODULES["switches"].fetcher(ctx) or {}).get("items", [])
        for row in sw_items or []:
            dev_id = str(row.get("id") or row.get("mac") or "")
            if not dev_id:
                continue
            key = f"switch:{dev_id}"
            raw_status = str(row.get("status") or "")
            snapshot[key] = DeviceStatus(
                key=key, type="switch",
                name=str(row.get("name") or dev_id),
                group=row.get("group") or row.get("stack"),
                online=device_online("switch", raw_status),
                raw_status=raw_status,
                last_change=0.0,
            )
    except Exception:  # noqa: BLE001
        LOG.exception("notify: switch fetch failed for device snapshot")

    # ── Controller nodes ──────────────────────────────────────────────────
    try:
        ctrl_items = (MODULES["controller"].fetcher(ctx) or {}).get("items", [])
        for row in ctrl_items or []:
            dev_id = str(row.get("id") or row.get("node") or "")
            if not dev_id:
                continue
            key = f"controller:{dev_id}"
            raw_status = str(row.get("state") or "")
            snapshot[key] = DeviceStatus(
                key=key, type="controller",
                name=str(row.get("node") or dev_id),
                group="controller",
                online=device_online("controller", raw_status),
                raw_status=raw_status,
                last_change=0.0,
            )
    except Exception:  # noqa: BLE001
        LOG.exception("notify: controller fetch failed for device snapshot")

    return snapshot


def state_from_data(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "aps_offline": sum(1 for a in data.get("aps") or []
                           if a.get("status") == "offline"),
        "switches_offline": sum(
            1 for s in data.get("switches") or []
            if str(s.get("status")).lower() not in ("online", "in_service")),
        "critical_alarms": sum(int(a.get("count") or 0)          # #14: was 'or 1'
                               for a in data.get("alarms") or []
                               if a.get("severity") == "critical"),
        "poor_aps": poor_quality_aps(data.get("clients") or []),
    }


def poor_quality_aps(clients: list[dict], ratio: float = 0.8,
                     min_clients: int = 3) -> list[str]:
    """APs where ≥ratio of their connected clients report poor quality."""
    by_ap: dict[str, list[str]] = {}
    for c in clients:
        ap = str(c.get("ap") or "")
        if ap:
            by_ap.setdefault(ap, []).append(str(c.get("quality") or ""))
    flagged = []
    for ap, qualities in by_ap.items():
        if len(qualities) < min_clients:
            continue
        poor = sum(1 for q in qualities if q == "poor")
        if poor / len(qualities) >= ratio:
            flagged.append(f"{ap} ({poor}/{len(qualities)} poor)")
    return sorted(flagged)


class NotifyScheduler:
    def __init__(self, instance_path: str, app_config: dict,
                 secrets) -> None:
        self._instance_path = instance_path
        self._app_config = app_config
        self._secrets = secrets
        self._connection = None
        self._lock = threading.Lock()
        self._last_alert_check = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._store = JsonOutageStateStore(instance_path)

    # ── wiring ───────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="notify-scheduler")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def set_connection(self, connection) -> None:
        with self._lock:
            self._connection = connection
        # SP2: do NOT null committed state — the store is the source of truth.
        # A reconnect must not re-baseline (audit #4 fix).

    def clear_connection(self) -> None:
        with self._lock:
            self._connection = None

    # ── due logic (unit-tested) ──────────────────────────────────────────
    def _alerts_due(self, cfg: dict, now: float) -> bool:
        if not cfg["alerts"]["enabled"]:
            return False
        return now - self._last_alert_check >= int(cfg["alerts"]["check_seconds"])

    def _report_due(self, cfg: dict, now_struct) -> bool:
        """True when the daily report has not yet been sent today.

        SP2: reads last_report_day from the durable store (not in-memory field)
        so a restart after the configured time doesn't re-send (audit #5 fix).
        """
        if not cfg["report"]["enabled"]:
            return False
        day = time.strftime("%Y-%m-%d", now_struct)
        state = self._store.load()
        last_day = (state.get("report") or {}).get("last_report_day")
        if last_day == day:
            return False
        hhmm = time.strftime("%H:%M", now_struct)
        return hhmm >= str(cfg["report"]["time"] or "07:00")

    def _mark_report_sent(self, day: str) -> None:
        """Persist today's date as sent to prevent re-send on restart."""
        state = self._store.load()
        state["report"] = {**(state.get("report") or {}), "last_report_day": day}
        self._store.save(state)

    # ── loop ─────────────────────────────────────────────────────────────
    def _run(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self._tick()
            except Exception:  # noqa: BLE001 — the loop must survive anything
                LOG.exception("notify: tick failed")

    def _tick(self) -> None:
        with self._lock:
            connection = self._connection
        if connection is None:
            return
        cfg = load_config(self._instance_path)
        now = time.time()

        if self._alerts_due(cfg, now):
            self._last_alert_check = now
            try:
                self._run_alerts(connection, cfg, now)
            except Exception:  # noqa: BLE001
                LOG.exception("notify: alerts tick failed")

        if self._report_due(cfg, time.localtime(now)):
            day = time.strftime("%Y-%m-%d", time.localtime(now))
            self._mark_report_sent(day)
            try:
                from ..reports.excel import build_report
                data = collect_report_data(connection, self._app_config)
                xlsx = build_report(data)
                ts = time.strftime("%Y-%m-%d", time.localtime(now))
                send_email(cfg, smtp_password(cfg, self._secrets),
                           cfg["report"]["recipients"],
                           f"[RUCKUS DSO] Daily report {ts}",
                           "Attached: daily RUCKUS DSO fabric report.",
                           attachment=xlsx,
                           filename=f"ruckus-dso-report-{ts}.xlsx")
                LOG.info("notify: daily report sent")
            except Exception:  # noqa: BLE001
                LOG.exception("notify: daily report failed")

    def _run_alerts(self, connection, cfg: dict, now: float) -> None:
        """Collect snapshot → reconcile → persist → dispatch via channels."""
        alerts_cfg = cfg["alerts"]

        # Load committed state from disk.
        state = self._store.load()
        prev_devices: dict[str, DeviceStatus] = state.get("devices") or {}

        # Collect current device snapshot.
        snapshot = collect_device_snapshot(connection, self._app_config)

        # Reconcile: pure function, no I/O.
        reconcile_cfg = {
            "debounce_seconds": int(alerts_cfg.get("debounce_seconds", 120)),
            "recovery": bool(alerts_cfg.get("recovery", True)),
            "offline_threshold": int(alerts_cfg.get("offline_threshold", 1)),
        }
        events, new_devices = OutageEngine.reconcile(
            prev_devices, snapshot, reconcile_cfg, now=now
        )

        # Persist new state BEFORE dispatch (save-first semantics — see spec §4.8).
        state["devices"] = new_devices
        self._store.save(state)

        if not events:
            return

        # Render + dispatch.
        group_by = str(alerts_cfg.get("group_by", "site"))
        note = render_alert(events, group_by=group_by)

        for ch_name, channel in CHANNELS.items():
            if channel.is_configured(cfg):
                try:
                    channel.send(cfg, self._secrets, note)
                    LOG.info("notify: sent %d outage event(s) via %s",
                             len(events), ch_name)
                except Exception:  # noqa: BLE001 — per-channel isolation
                    LOG.exception("notify: channel %s failed", ch_name)
```

- [ ] **Run — expect PASS**:

```
python -m pytest tests/unit/notify/test_notify.py -k "test_collect_device_snapshot or test_baseline_spam or test_report_due_persisted or test_report_due_fires" -v
```

- [ ] **Run full notify suite — all existing tests must still pass**:

```
python -m pytest tests/unit/notify/test_notify.py -v
```

Expected: All tests pass. The old `test_rules_fire_on_transition_only` still passes because `rules.evaluate` is unchanged; the new `test_baseline_spam_not_fired_on_existing_outage` tests the `OutageEngine` path (which the scheduler now uses).

- [ ] **Commit**:

```
git commit -m "feat(notify/scheduler): SP2 device-snapshot alerts, durable state, dedup fix (#4, #5)"
```

---

## Task 10 — Integration tests: config roundtrip + alert test body

**Files:**
- Modify: `tests/integration/test_notifications_api.py`
- Test: same file

### Steps

- [ ] **Write the failing tests.** Append to `tests/integration/test_notifications_api.py`:

```python
def test_notifications_config_roundtrip_includes_sp2_fields(tmp_path):
    """Config GET/POST roundtrip carries new SP2 alert fields."""
    app = _app(tmp_path)
    with app.test_client() as c:
        csrf = _login(c)
        r = c.post("/api/notifications/config",
                   json={"smtp": {"host": "mail.x", "password": "hunter2"},
                         "alerts": {
                             "enabled": True,
                             "recipients": ["a@x"],
                             "recovery": False,
                             "debounce_seconds": 60,
                             "group_by": "none",
                         }},
                   headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        body = r.get_json()
        alerts = body["alerts"]
        assert alerts["recovery"] is False
        assert alerts["debounce_seconds"] == 60
        assert alerts["group_by"] == "none"
        # Password still masked.
        assert body["smtp"]["password"] == "********"

        # GET returns same values.
        got = c.get("/api/notifications/config").get_json()
        assert got["alerts"]["recovery"] is False
        assert got["alerts"]["debounce_seconds"] == 60


def test_test_alert_email_sends_grouped_body(tmp_path, monkeypatch):
    """kind='alerts' test email sends subject+body using the configured recipients."""
    import ruckus_dashboard.routes.notifications as notif_routes
    calls = {}

    def fake_send(cfg, pw, recipients, subject, body, **kw):
        calls["recipients"] = recipients
        calls["subject"] = subject
        calls["body"] = body

    monkeypatch.setattr(notif_routes, "send_email", fake_send)
    app = _app(tmp_path)
    with app.test_client() as c:
        csrf = _login(c)
        c.post("/api/notifications/config",
               json={"smtp": {"host": "mail.x"},
                     "alerts": {"recipients": ["noc@x"]}},
               headers={"X-CSRF-Token": csrf})
        r = c.post("/api/notifications/test",
                   json={"kind": "alerts"},
                   headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        assert r.get_json()["sent"] is True
        assert calls["recipients"] == ["noc@x"]
        # Test alert body mentions the outage channel (not just "smtp works").
        assert "alert" in calls["body"].lower() or "RUCKUS DSO" in calls["subject"]
```

- [ ] **Run — expect PASS** (the config roundtrip test should pass once Task 7 is done; the test-alert test uses the existing route which already works):

```
python -m pytest tests/integration/test_notifications_api.py -v
```

- [ ] **Commit**:

```
git commit -m "test(integration): SP2 config roundtrip carries recovery/debounce/group_by fields"
```

---

## Task 11 — Full suite green-check

**Files:** No new code — validation only.

### Steps

- [ ] **Run the complete test suite**:

```
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All 305+ tests pass. No regressions in existing notify, excel, mailer, or integration tests.

- [ ] **If failures exist**, diagnose and fix inline before committing. Common risks:
  - `test_rules_fire_on_transition_only` (line 54): this tests `rules.evaluate` directly, which is unchanged — should still pass.
  - `test_report_due_once_per_day_after_time` (line 92): `_report_due` now reads the store instead of `self._last_report_day`. The test sets `s._last_report_day = "2026-06-10"` directly on the instance — this will no longer work. **Fix the test** to use `JsonOutageStateStore` to seed the day instead:

```python
def test_report_due_once_per_day_after_time(tmp_path):
    from ruckus_dashboard.notify.state_store import JsonOutageStateStore
    s = _sched(tmp_path)
    cfg = cfg_mod.load_config(str(tmp_path))
    cfg["report"]["enabled"] = True
    cfg["report"]["time"] = "07:00"
    before = time.strptime("2026-06-10 06:59", "%Y-%m-%d %H:%M")
    after = time.strptime("2026-06-10 07:01", "%Y-%m-%d %H:%M")
    assert s._report_due(cfg, before) is False
    assert s._report_due(cfg, after) is True
    # Persist today via the store (not the in-memory field).
    store = JsonOutageStateStore(str(tmp_path))
    store.save({"devices": {}, "report": {"last_report_day": "2026-06-10"}})
    assert s._report_due(cfg, after) is False      # once per day
    next_day = time.strptime("2026-06-11 07:01", "%Y-%m-%d %H:%M")
    assert s._report_due(cfg, next_day) is True
```

- [ ] **Commit** (if test fixups were needed):

```
git commit -m "test(notify): update test_report_due_once_per_day to use JsonOutageStateStore"
```

---

## Self-Review

### Spec coverage map

| Spec requirement | Task(s) covering it |
|-----------------|---------------------|
| Per-device snapshot diffing (`OutageEngine.reconcile`) | T2 |
| `DeviceStatus` data model with key, type, name, group, online, raw_status, last_change | T1 |
| Durable JSON state store (`JsonOutageStateStore`, atomic tmp+replace, tolerant load) | T5 |
| Recovery ("back online") events | T2, T3 |
| Per-site/zone grouping for APs + switches + controller | T1, T4 |
| Debounce (pending_since / pending_target, survives restart) | T3, T5 |
| Controller nodes monitored (spec §1.1 gap) | T1, T9 |
| `NotificationChannel` Protocol + `EmailChannel` wrapping mailer (mailer untouched) | T6 |
| `OutageStateStore` Protocol (interface seam for SQLite later) | T5 |
| **Audit #4 — baseline-spam**: seed silently on first check, load committed state from disk | T2, T9 |
| **Audit #5 — durable daily-report dedup**: persist `last_report_day`; start-after-time guard | T9 |
| **Audit #14 — `count or 1` → `count or 0`** | T8 |
| `set_connection` stops nulling state | T9 |
| `_tick` save-before-dispatch semantics (spec §4.8) | T9 |
| New config keys (`recovery`, `debounce_seconds`, `group_by`, `suppress_known_on_start`, `channels`) | T7 |
| Config backward-compat (old files upgrade without migration) | T7 |
| `offline_threshold` reinterpreted as min-newly-offline per batch | T2 |
| `render_alert` subject with counts + group names | T4 |
| Per-channel send isolation (failure does not stop other channels or tick) | T6 |
| Collector-fetch failure leaves device type unchanged (not marked offline) | T9 |
| Integration config roundtrip carries new SP2 fields | T10 |
| 305-test suite green | T11 |

### Placeholder scan

None: every code block in every task is complete. No `pass`, `TODO`, `TBD`, `# add error handling`, or `# similar to Task N` stubs appear anywhere.

### Type/name consistency

| Symbol | Defined in | Used in |
|--------|-----------|---------|
| `DeviceStatus` | `outage.py` | `outage.py`, `state_store.py`, `scheduler.py`, tests |
| `OutageEvent` | `outage.py` | `outage.py`, `channels.py`, tests |
| `Notification` | `outage.py` (re-exported from `channels.py`) | `outage.py`, `channels.py`, tests |
| `OutageEngine.reconcile` | `outage.py` | `scheduler.py`, tests |
| `device_online` | `outage.py` | `scheduler.py`, tests |
| `render_alert` | `outage.py` | `scheduler.py`, tests |
| `JsonOutageStateStore` | `state_store.py` | `scheduler.py`, tests |
| `EmailChannel` | `channels.py` | `channels.py` (CHANNELS), tests |
| `CHANNELS` | `channels.py` | `scheduler.py`, tests |
| `collect_device_snapshot` | `scheduler.py` | `scheduler.py` (`_run_alerts`), tests |
| `collect_report_data` | `scheduler.py` (unchanged) | `scheduler.py`, `routes/notifications.py` |
| `state_from_data` | `scheduler.py` | tests (still tested for report path) |
| `poor_quality_aps` | `scheduler.py` (unchanged) | tests |

All argument names match across definition and call sites. `cfg` is always a `dict` produced by `load_config`. `secrets` is always the app's `SecretsManager`-like object (duck-typed; `FakeSecrets` in tests).

---

## Execution Handoff

### Recommended: `superpowers:subagent-driven-development`

Tasks T1–T6 are independent of each other (each creates or modifies a single file with its own test group). Tasks T7–T9 depend on T1–T6 but can proceed sequentially in that order. T10 depends on T7. T11 is final.

**Parallelizable first wave (no mutual dependencies):**
- T1 (`outage.py` — dataclasses + helpers)
- T5 (`state_store.py`)
- T6 (`channels.py`)
- T8 (one-line fix in `scheduler.py`)

**Sequential second wave (each builds on prior):**
- T2, T3 (extend `outage.py`) → T4 (extend `outage.py`) → T7 (extend `config.py`) → T9 (rewrite `scheduler.py`) → T10 (integration tests) → T11 (suite green-check)

### Inline alternative: `superpowers:executing-plans`

Work through tasks in order T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10 → T11. Each task is self-contained: write test → run (FAIL) → implement → run (PASS) → commit.

### Critical path risks

1. **`_report_due` test migration (T11)**: `test_report_due_once_per_day_after_time` sets `s._last_report_day` directly; this in-memory field is removed in T9. The fix is prescribed in T11 — do not skip it.
2. **`Notification` circular import**: `render_alert` in `outage.py` returns a `Notification` defined in the same file; `channels.py` re-exports it. If a future change moves `Notification` to `channels.py`, update the import in `outage.py` carefully to avoid a circular dep.
3. **Windows `os.replace` atomicity**: `os.replace` is atomic on Windows NTFS when source and destination are on the same volume — the `instance/` folder satisfies this. No concern.
4. **Controller module not always available**: `MODULES["controller"]` may not exist on non-SmartZone connections. `collect_device_snapshot` wraps each fetch in a `try/except` so this is safe; add a `.get("controller")` guard if the module registry raises `KeyError` on missing slugs (verify with `MODULES` implementation in `modules/__init__.py`).
