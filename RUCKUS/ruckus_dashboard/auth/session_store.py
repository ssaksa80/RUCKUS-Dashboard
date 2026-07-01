"""In-memory connection session store with TTL-based eviction.

Holds authenticated controller connections (SmartZone/Unleashed/vSZ) keyed by
opaque session tokens. Idle connections older than ``ttl_seconds`` are evicted
on access. Thread-safe via an internal ``RLock``.
"""

from dataclasses import dataclass
import secrets
import time
from threading import RLock
from typing import Callable


@dataclass
class ConnectionConfig:
    platform: str
    api_base: str
    display_name: str
    auth_token: str
    verify_tls: bool | str = True
    api_version: str = ""
    controller_version: str = ""
    tenant_id: str = ""
    token_expires_at: float = 0
    created_at: float = 0
    last_used_at: float = 0


class ConnectionStore:
    def __init__(
        self,
        ttl_seconds: int,
        on_evict: Callable[[str], None] | None = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self._connections: dict[str, ConnectionConfig] = {}
        self._lock = RLock()
        # Invoked once per TTL-evicted token, OUTSIDE the store's lock, so the
        # callback (e.g. CapabilityRegistry.clear, which takes its own lock)
        # cannot deadlock or nest under ours.
        self._on_evict = on_evict

    def put(self, connection: ConnectionConfig) -> str:
        now = time.time()
        connection.created_at = now
        connection.last_used_at = now
        token = secrets.token_urlsafe(32)
        with self._lock:
            evicted = self._cleanup_locked(now)
            self._connections[token] = connection
        self._notify_evicted(evicted)
        return token

    def get(self, token: str) -> ConnectionConfig | None:
        now = time.time()
        with self._lock:
            evicted = self._cleanup_locked(now)
            connection = self._connections.get(token)
            if connection is not None:
                connection.last_used_at = now
        self._notify_evicted(evicted)
        return connection

    def remove(self, token: str) -> None:
        with self._lock:
            self._connections.pop(token, None)

    def count(self) -> int:
        with self._lock:
            return len(self._connections)

    def _cleanup_locked(self, now: float) -> list[str]:
        """Drop expired tokens and return them (caller notifies outside lock)."""
        expired = [
            token
            for token, connection in self._connections.items()
            if now - connection.last_used_at > self.ttl_seconds
        ]
        for token in expired:
            self._connections.pop(token, None)
        return expired

    def _notify_evicted(self, tokens: list[str]) -> None:
        if not self._on_evict:
            return
        for token in tokens:
            self._on_evict(token)
