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
