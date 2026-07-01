"""In-memory login rate limiter for the break-glass local login (PB1).

Single-node, no Redis: a process-local sliding-window counter keyed by
``(client-ip, email)``. After ``max_failures`` failures inside ``window_seconds``
the key is locked out until the window clears; a successful login resets it.
Thread-safe via an ``RLock``. This is a brute-force speed bump, not a
distributed quota.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import RLock


class LoginRateLimiter:
    def __init__(self, max_failures: int = 5, window_seconds: int = 300) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = RLock()

    def _prune(self, key: str, now: float) -> None:
        dq = self._fails[key]
        cutoff = now - self.window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()
        if not dq:
            self._fails.pop(key, None)

    def is_locked(self, key: str) -> bool:
        """True if ``key`` currently has >= max_failures within the window."""
        now = time.time()
        with self._lock:
            self._prune(key, now)
            return len(self._fails.get(key, ())) >= self.max_failures

    def register_failure(self, key: str) -> None:
        now = time.time()
        with self._lock:
            self._prune(key, now)
            self._fails[key].append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
