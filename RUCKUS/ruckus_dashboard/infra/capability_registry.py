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
