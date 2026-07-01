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
