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
