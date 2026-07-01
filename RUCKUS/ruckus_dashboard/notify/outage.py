"""Per-device outage detection: snapshot diffing, debounce, event rendering.

Pure functions only (no I/O). The scheduler owns the store; this module owns
the logic so it stays fully unit-testable without any disk access."""
from __future__ import annotations

import time  # noqa: F401 — used by OutageEngine.reconcile (Task 2)
from dataclasses import dataclass, field
from typing import Any  # noqa: F401 — used by OutageEngine.reconcile (Task 2)

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
