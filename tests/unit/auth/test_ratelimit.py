"""auth.ratelimit.LoginRateLimiter — sliding-window lockout logic."""
from __future__ import annotations

from ruckus_dashboard.auth.ratelimit import LoginRateLimiter


def test_not_locked_below_threshold():
    rl = LoginRateLimiter(max_failures=3, window_seconds=300)
    rl.register_failure("k")
    rl.register_failure("k")
    assert rl.is_locked("k") is False


def test_locks_at_threshold():
    rl = LoginRateLimiter(max_failures=3, window_seconds=300)
    for _ in range(3):
        rl.register_failure("k")
    assert rl.is_locked("k") is True


def test_reset_clears_lock():
    rl = LoginRateLimiter(max_failures=2, window_seconds=300)
    rl.register_failure("k")
    rl.register_failure("k")
    assert rl.is_locked("k") is True
    rl.reset("k")
    assert rl.is_locked("k") is False


def test_keys_are_independent():
    rl = LoginRateLimiter(max_failures=1, window_seconds=300)
    rl.register_failure("a")
    assert rl.is_locked("a") is True
    assert rl.is_locked("b") is False


def test_window_expiry_prunes_old_failures(monkeypatch):
    import ruckus_dashboard.auth.ratelimit as mod

    clock = {"t": 1000.0}
    monkeypatch.setattr(mod.time, "time", lambda: clock["t"])
    rl = mod.LoginRateLimiter(max_failures=2, window_seconds=100)
    rl.register_failure("k")
    rl.register_failure("k")
    assert rl.is_locked("k") is True
    clock["t"] += 101  # both failures now outside the window
    assert rl.is_locked("k") is False
