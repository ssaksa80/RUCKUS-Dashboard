"""The test-app default: RUCKUS_AUTH_REQUIRED is OFF unless a test opts in.

This is the mechanism that keeps the pre-PhaseB suite green: create_app called
with a test_config dict that doesn't mention RUCKUS_AUTH_REQUIRED must NOT gate
requests behind app-login. Production (test_config=None) defaults it ON.
"""
from __future__ import annotations

from ruckus_dashboard.app import create_app


def test_test_config_defaults_auth_off():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    assert app.config["RUCKUS_AUTH_REQUIRED"] is False


def test_test_config_can_opt_into_auth():
    app = create_app({"SECRET_KEY": "t", "RUCKUS_AUTH_REQUIRED": True,
                      "RUCKUS_DATABASE_URL": "sqlite:///:memory:"})
    assert app.config["RUCKUS_AUTH_REQUIRED"] is True


def test_auth_off_app_does_not_gate_index():
    # With auth off, the index behaves exactly as before PhaseB (controller
    # login gate only) — the app-user gate must be inert.
    app = create_app({"SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True})
    with app.test_client() as c:
        r = c.get("/")
        assert r.status_code == 200  # not a 302 app-login bounce


def test_auth_off_uses_memory_db_by_default():
    # Tests must not write a real ruckus.db; the resolved URL is in-memory.
    app = create_app({"SECRET_KEY": "t"})
    assert ":memory:" in app.config["RUCKUS_DATABASE_URL"]


def test_rate_limit_locks_out_after_repeated_failures():
    app = create_app({
        "SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True,
        "RUCKUS_AUTH_REQUIRED": True, "RUCKUS_DATABASE_URL": "sqlite:///:memory:",
        "RUCKUS_ADMIN_PASSWORD": "Rate-Limit-Pw-1",
    })
    with app.test_client() as c:
        c.get("/login")
        with c.session_transaction() as s:
            token = s["csrf_token"]
        # Hammer wrong passwords; after the threshold the endpoint returns 429.
        statuses = []
        for _ in range(12):
            r = c.post("/login", data={"email": "admin", "password": "nope",
                                      "csrf_token": token})
            statuses.append(r.status_code)
        assert 429 in statuses, f"expected a 429 lockout, got {statuses}"
