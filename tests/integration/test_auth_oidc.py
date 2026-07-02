"""Integration: OIDC SSO login flow (PB2), mocking the IdP entirely.

No network. The Authlib client is registered (register() is lazy — it never
fetches discovery until used), then its ``authorize_redirect`` /
``authorize_access_token`` / ``userinfo`` methods are monkeypatched so the
callback runs against canned, "pre-validated" claims. The local break-glass
path (PB1) must stay unaffected — those tests live in test_auth_login.py.
"""
from __future__ import annotations

import pytest
from flask import redirect as flask_redirect
from flask import session as flask_session

from ruckus_dashboard.app import create_app
from ruckus_dashboard.auth import oidc as oidc_mod
from ruckus_dashboard.db import session_scope
from ruckus_dashboard.db.models import AuditLog, Role, User


OIDC_CFG = {
    "SECRET_KEY": "t",
    "RUCKUS_ENABLE_NEW_UI": True,
    "RUCKUS_AUTH_REQUIRED": True,
    "RUCKUS_OIDC_ISSUER": "https://idp.corp.local",
    "RUCKUS_OIDC_CLIENT_ID": "ruckus",
    "RUCKUS_OIDC_CLIENT_SECRET": "s3cret",
    "RUCKUS_OIDC_SCOPES": "openid email profile",
    "RUCKUS_OIDC_GROUPS_CLAIM": "groups",
    "RUCKUS_OIDC_GROUP_ROLES": "admins:admin,noc:operator",
    "RUCKUS_ADMIN_PASSWORD": "Admin-Seed-Pw-1",
}


@pytest.fixture
def oidc_app(tmp_path):
    """Auth-ON app with OIDC fully configured (temp-file SQLite)."""
    db_file = tmp_path / "ruckus.db"
    cfg = dict(OIDC_CFG)
    cfg["RUCKUS_DATABASE_URL"] = f"sqlite:///{db_file.as_posix()}"
    return create_app(cfg)


@pytest.fixture
def local_only_app(tmp_path):
    """Auth-ON app with OIDC NOT configured (local break-glass only)."""
    db_file = tmp_path / "ruckus.db"
    return create_app({
        "SECRET_KEY": "t",
        "RUCKUS_ENABLE_NEW_UI": True,
        "RUCKUS_AUTH_REQUIRED": True,
        "RUCKUS_DATABASE_URL": f"sqlite:///{db_file.as_posix()}",
        "RUCKUS_ADMIN_PASSWORD": "Admin-Seed-Pw-1",
    })


def _install_fake_idp(app, monkeypatch, claims, *, raise_on_callback=False):
    """Monkeypatch the registered Authlib client so no network happens.

    ``authorize_redirect`` stores a state and 302s to the fake authorize URL;
    ``authorize_access_token`` returns a token whose ``userinfo`` is ``claims``
    (already "validated") — or raises, to exercise the error path.
    """
    client = oidc_mod.get_oidc_client(app)
    assert client is not None, "OIDC client must be registered for this test"

    def fake_authorize_redirect(redirect_uri, **kwargs):
        # Mirror Authlib: stash state in the session, bounce to the IdP.
        flask_session["_fake_oidc_state"] = "state-abc"
        return flask_redirect(
            "https://idp.corp.local/authorize?state=state-abc"
            f"&redirect_uri={redirect_uri}"
        )

    def fake_authorize_access_token(**kwargs):
        if raise_on_callback:
            from authlib.integrations.base_client.errors import OAuthError
            raise OAuthError(error="access_denied", description="user said no")
        return {"access_token": "at-secret", "id_token": "idt", "userinfo": claims}

    monkeypatch.setattr(client, "authorize_redirect", fake_authorize_redirect)
    monkeypatch.setattr(client, "authorize_access_token", fake_authorize_access_token)
    # userinfo should not be needed (claims already carry groups+email), but
    # stub it so a stray call can't reach the network.
    monkeypatch.setattr(client, "userinfo", lambda **kw: dict(claims))
    return client


# ── enable-gate behaviour ─────────────────────────────────────────────────────

def test_local_only_login_oidc_redirects_to_login(local_only_app):
    assert oidc_mod.oidc_enabled(local_only_app) is False
    with local_only_app.test_client() as c:
        r = c.get("/login/oidc")
        assert r.status_code in (302, 303)
        assert "/login" in r.headers["Location"]
        # Did NOT bounce to any IdP.
        assert "idp" not in r.headers["Location"]


def test_local_only_login_still_works(local_only_app):
    """Break-glass unaffected when OIDC is off."""
    with local_only_app.test_client() as c:
        c.get("/login")
        with c.session_transaction() as s:
            token = s["csrf_token"]
        c.post("/login", data={"email": "admin", "password": "Admin-Seed-Pw-1",
                               "csrf_token": token})
        with c.session_transaction() as s:
            assert s.get("user_id") is not None
            assert s.get("role") == Role.admin.name


def test_login_page_hides_sso_button_when_disabled(local_only_app):
    with local_only_app.test_client() as c:
        html = c.get("/login").get_data(as_text=True)
        assert "/login/oidc" not in html


def test_login_page_shows_sso_button_when_enabled(oidc_app):
    with oidc_app.test_client() as c:
        html = c.get("/login").get_data(as_text=True)
        assert "/login/oidc" in html


# ── authorize redirect ────────────────────────────────────────────────────────

def test_login_oidc_redirects_to_idp_and_stores_state(oidc_app, monkeypatch):
    _install_fake_idp(oidc_app, monkeypatch, claims={})
    with oidc_app.test_client() as c:
        r = c.get("/login/oidc")
        assert r.status_code in (302, 303)
        assert r.headers["Location"].startswith("https://idp.corp.local/authorize")
        with c.session_transaction() as s:
            assert s.get("_fake_oidc_state") == "state-abc"


def test_login_oidc_preserves_next(oidc_app, monkeypatch):
    _install_fake_idp(oidc_app, monkeypatch, claims={})
    with oidc_app.test_client() as c:
        c.get("/login/oidc?next=/m/aps")
        with c.session_transaction() as s:
            assert s.get("next") == "/m/aps"


# ── callback: JIT user + role + session + audit ───────────────────────────────

_CLAIMS_ADMIN = {
    "sub": "idp-sub-001",
    "email": "sso-admin@corp.local",
    "name": "SSO Admin",
    "groups": ["admins"],
}


def test_callback_jit_creates_admin_user(oidc_app, monkeypatch):
    _install_fake_idp(oidc_app, monkeypatch, claims=_CLAIMS_ADMIN)
    with oidc_app.test_client() as c:
        r = c.get("/auth/callback?state=state-abc&code=xyz")
        assert r.status_code in (302, 303)
        with c.session_transaction() as s:
            assert s.get("user_id") is not None
            assert s.get("role") == Role.admin.name
            assert s.get("tenant_id") is not None
    with session_scope(oidc_app) as s:
        u = s.query(User).filter_by(oidc_subject="idp-sub-001").one()
        assert u.email == "sso-admin@corp.local"
        assert u.role == Role.admin.name
        assert u.password_hash is None  # OIDC-only, no local password
        actions = [a.action for a in s.query(AuditLog).all()]
        assert "login_success" in actions
        # method=oidc recorded in the detail.
        success = [a for a in s.query(AuditLog).filter_by(action="login_success")]
        assert any((a.detail or {}).get("method") == "oidc" for a in success)


def test_callback_maps_noc_group_to_operator(oidc_app, monkeypatch):
    claims = {"sub": "idp-noc", "email": "noc@corp.local", "groups": ["noc"]}
    _install_fake_idp(oidc_app, monkeypatch, claims=claims)
    with oidc_app.test_client() as c:
        c.get("/auth/callback?state=state-abc&code=xyz")
    with session_scope(oidc_app) as s:
        u = s.query(User).filter_by(oidc_subject="idp-noc").one()
        assert u.role == Role.operator.name


def test_callback_unmapped_group_defaults_viewer(oidc_app, monkeypatch):
    claims = {"sub": "idp-rand", "email": "rand@corp.local", "groups": ["random"]}
    _install_fake_idp(oidc_app, monkeypatch, claims=claims)
    with oidc_app.test_client() as c:
        c.get("/auth/callback?state=state-abc&code=xyz")
    with session_scope(oidc_app) as s:
        u = s.query(User).filter_by(oidc_subject="idp-rand").one()
        assert u.role == Role.viewer.name


def test_callback_second_login_updates_not_duplicates(oidc_app, monkeypatch):
    _install_fake_idp(oidc_app, monkeypatch, claims=_CLAIMS_ADMIN)
    with oidc_app.test_client() as c:
        c.get("/auth/callback?state=state-abc&code=xyz")
    # Second login, same sub, display name changed.
    claims2 = dict(_CLAIMS_ADMIN, name="Renamed Admin")
    _install_fake_idp(oidc_app, monkeypatch, claims=claims2)
    with oidc_app.test_client() as c:
        c.get("/auth/callback?state=state-abc&code=xyz")
    with session_scope(oidc_app) as s:
        rows = s.query(User).filter_by(oidc_subject="idp-sub-001").all()
        assert len(rows) == 1
        assert rows[0].display_name == "Renamed Admin"


def test_callback_rotates_session_fixation_guard(oidc_app, monkeypatch):
    _install_fake_idp(oidc_app, monkeypatch, claims=_CLAIMS_ADMIN)
    with oidc_app.test_client() as c:
        with c.session_transaction() as s:
            s["planted"] = "attacker"
        c.get("/auth/callback?state=state-abc&code=xyz")
        with c.session_transaction() as s:
            assert "planted" not in s  # session.clear() ran
            assert s.get("user_id") is not None


def test_callback_honors_next_redirect(oidc_app, monkeypatch):
    _install_fake_idp(oidc_app, monkeypatch, claims=_CLAIMS_ADMIN)
    with oidc_app.test_client() as c:
        # Seed the stored next as the /login/oidc handler would.
        with c.session_transaction() as s:
            s["next"] = "/m/aps"
        r = c.get("/auth/callback?state=state-abc&code=xyz")
        assert r.headers["Location"].endswith("/m/aps")


def test_callback_then_access_protected_page(oidc_app, monkeypatch):
    _install_fake_idp(oidc_app, monkeypatch, claims=_CLAIMS_ADMIN)
    with oidc_app.test_client() as c:
        c.get("/auth/callback?state=state-abc&code=xyz")
        assert c.get("/").status_code == 200  # gate satisfied


# ── callback: email-claim account linking is REFUSED (hijack prevention) ──────

def test_callback_refuses_to_hijack_local_admin_via_email_claim(oidc_app, monkeypatch):
    # SECURITY: the break-glass admin is seeded locally with email "admin". An
    # attacker with any IdP account presenting email="admin" (an attacker-
    # influenceable claim — Authlib does NOT verify email ownership) must be
    # refused: the callback rejects the login with the generic OIDC error, and
    # the local admin row is left completely untouched (no subject bound, role
    # unchanged), so the break-glass account cannot be rewritten or taken over.
    claims = {"sub": "idp-attacker", "email": "admin",
              "name": "Not The Admin", "groups": ["admins"]}
    _install_fake_idp(oidc_app, monkeypatch, claims=claims)
    with oidc_app.test_client() as c:
        r = c.get("/auth/callback?state=state-abc&code=xyz")
        assert r.status_code in (302, 303)
        assert "/login" in r.headers["Location"]
        assert r.status_code != 500
        with c.session_transaction() as s:
            assert s.get("user_id") is None  # NOT logged in
    with session_scope(oidc_app) as s:
        rows = s.query(User).filter_by(email="admin").all()
        assert len(rows) == 1  # no duplicate admin
        admin = rows[0]
        assert admin.oidc_subject is None  # subject NOT bound — no hijack
        assert admin.role == Role.admin.name  # role unchanged
        assert admin.password_hash is not None  # break-glass password kept
        # The attacker subject was never persisted.
        assert s.query(User).filter_by(oidc_subject="idp-attacker").count() == 0
        # A generic login_failure with the email_conflict reason was audited;
        # no login_success, and no email detail leaked.
        actions = [a.action for a in s.query(AuditLog).all()]
        assert "login_failure" in actions
        assert "login_success" not in actions
        failures = list(s.query(AuditLog).filter_by(action="login_failure"))
        assert any(
            (a.detail or {}).get("method") == "oidc"
            and (a.detail or {}).get("reason") == "email_conflict"
            for a in failures
        )
        for a in failures:
            # The conflicting email must not be revealed in the audit detail.
            assert "admin" not in str((a.detail or {}).get("email", ""))


def test_callback_refuses_to_hijack_existing_oidc_user_by_email(oidc_app, monkeypatch):
    # A privileged OIDC user already exists (subject idp-sub-001, email
    # sso-admin@corp.local). A DIFFERENT attacker subject claiming the same
    # email must be refused rather than rebinding or duplicating the account.
    _install_fake_idp(oidc_app, monkeypatch, claims=_CLAIMS_ADMIN)
    with oidc_app.test_client() as c:
        c.get("/auth/callback?state=state-abc&code=xyz")  # provision the victim

    attacker = dict(_CLAIMS_ADMIN, sub="idp-sub-attacker", name="Attacker")
    _install_fake_idp(oidc_app, monkeypatch, claims=attacker)
    with oidc_app.test_client() as c:
        r = c.get("/auth/callback?state=state-abc&code=xyz")
        assert "/login" in r.headers["Location"]
        with c.session_transaction() as s:
            assert s.get("user_id") is None
    with session_scope(oidc_app) as s:
        rows = s.query(User).filter_by(email="sso-admin@corp.local").all()
        assert len(rows) == 1  # still exactly the victim, no duplicate
        assert rows[0].oidc_subject == "idp-sub-001"  # unchanged
        assert s.query(User).filter_by(oidc_subject="idp-sub-attacker").count() == 0


def test_callback_new_subject_free_email_creates_viewer(oidc_app, monkeypatch):
    # JIT happy path still works: a brand-new subject with an unused email and
    # no mapped group is provisioned as a fresh viewer OIDC user.
    claims = {"sub": "idp-fresh", "email": "fresh@corp.local",
              "name": "Fresh User", "groups": ["random-unmapped"]}
    _install_fake_idp(oidc_app, monkeypatch, claims=claims)
    with oidc_app.test_client() as c:
        r = c.get("/auth/callback?state=state-abc&code=xyz")
        assert r.status_code in (302, 303)
        with c.session_transaction() as s:
            assert s.get("user_id") is not None
            assert s.get("role") == Role.viewer.name
    with session_scope(oidc_app) as s:
        u = s.query(User).filter_by(oidc_subject="idp-fresh").one()
        assert u.email == "fresh@corp.local"
        assert u.role == Role.viewer.name
        assert u.password_hash is None  # OIDC-only, no local password


def test_callback_known_subject_relogs_and_remaps_role(oidc_app, monkeypatch):
    # A known subject logs in again and its role is re-mapped from the current
    # IdP group membership (viewer → operator here), reusing the same row.
    first = {"sub": "idp-remap", "email": "remap@corp.local",
             "name": "Remap", "groups": ["random-unmapped"]}
    _install_fake_idp(oidc_app, monkeypatch, claims=first)
    with oidc_app.test_client() as c:
        c.get("/auth/callback?state=state-abc&code=xyz")
    with session_scope(oidc_app) as s:
        assert s.query(User).filter_by(oidc_subject="idp-remap").one().role \
            == Role.viewer.name

    second = dict(first, groups=["noc"])  # noc → operator per OIDC_CFG
    _install_fake_idp(oidc_app, monkeypatch, claims=second)
    with oidc_app.test_client() as c:
        c.get("/auth/callback?state=state-abc&code=xyz")
        with c.session_transaction() as sess:
            assert sess.get("user_id") is not None
            assert sess.get("role") == Role.operator.name
    with session_scope(oidc_app) as s:
        rows = s.query(User).filter_by(oidc_subject="idp-remap").all()
        assert len(rows) == 1  # same row, no duplicate
        assert rows[0].role == Role.operator.name


# ── callback: role_changed audit (PB2 hardening) ──────────────────────────────

def test_callback_role_change_audits_once_from_to(oidc_app, monkeypatch):
    # A second OIDC login that remaps the user's role (viewer → operator) writes
    # exactly one role_changed audit row carrying from/to and method=oidc.
    first = {"sub": "idp-rc", "email": "rc@corp.local",
             "name": "RC", "groups": ["random-unmapped"]}  # → viewer
    _install_fake_idp(oidc_app, monkeypatch, claims=first)
    with oidc_app.test_client() as c:
        c.get("/auth/callback?state=state-abc&code=xyz")
    with session_scope(oidc_app) as s:
        uid = s.query(User).filter_by(oidc_subject="idp-rc").one().id
        assert s.query(AuditLog).filter_by(action="role_changed").count() == 0

    second = dict(first, groups=["noc"])  # → operator
    _install_fake_idp(oidc_app, monkeypatch, claims=second)
    with oidc_app.test_client() as c:
        c.get("/auth/callback?state=state-abc&code=xyz")
    with session_scope(oidc_app) as s:
        rows = list(s.query(AuditLog).filter_by(action="role_changed"))
        assert len(rows) == 1
        assert rows[0].user_id == uid
        assert rows[0].tenant_id is not None
        assert (rows[0].detail or {}) == {
            "method": "oidc", "from": Role.viewer.name, "to": Role.operator.name,
        }


def test_callback_same_role_relogin_writes_no_role_changed(oidc_app, monkeypatch):
    # Logging in twice with the same mapped role writes no role_changed row.
    _install_fake_idp(oidc_app, monkeypatch, claims=_CLAIMS_ADMIN)  # admins → admin
    with oidc_app.test_client() as c:
        c.get("/auth/callback?state=state-abc&code=xyz")
    _install_fake_idp(oidc_app, monkeypatch, claims=_CLAIMS_ADMIN)
    with oidc_app.test_client() as c:
        c.get("/auth/callback?state=state-abc&code=xyz")
    with session_scope(oidc_app) as s:
        assert s.query(AuditLog).filter_by(action="role_changed").count() == 0


# ── callback: error path (no leak) ────────────────────────────────────────────

def test_callback_error_audits_failure_and_redirects(oidc_app, monkeypatch):
    _install_fake_idp(oidc_app, monkeypatch, claims={}, raise_on_callback=True)
    with oidc_app.test_client() as c:
        r = c.get("/auth/callback?state=state-abc&code=xyz")
        assert r.status_code in (302, 303)
        assert "/login" in r.headers["Location"]
        assert r.status_code != 500
        with c.session_transaction() as s:
            assert s.get("user_id") is None  # not logged in
    with session_scope(oidc_app) as s:
        actions = [a.action for a in s.query(AuditLog).all()]
        assert "login_failure" in actions
        # No token/exception detail leaked into the audit detail.
        for a in s.query(AuditLog).filter_by(action="login_failure"):
            blob = str(a.detail or {})
            assert "at-secret" not in blob
            assert "user said no" not in blob


def test_callback_missing_sub_is_failure(oidc_app, monkeypatch):
    # A token with no 'sub' claim must be rejected as a failure, not a 500.
    claims = {"email": "nosub@corp.local", "groups": ["admins"]}
    _install_fake_idp(oidc_app, monkeypatch, claims=claims)
    with oidc_app.test_client() as c:
        r = c.get("/auth/callback?state=state-abc&code=xyz")
        assert r.status_code in (302, 303)
        assert "/login" in r.headers["Location"]
        with c.session_transaction() as s:
            assert s.get("user_id") is None
    with session_scope(oidc_app) as s:
        actions = [a.action for a in s.query(AuditLog).all()]
        assert "login_failure" in actions
        assert "login_success" not in actions


def test_callback_generic_flash_no_token_leak(oidc_app, monkeypatch):
    _install_fake_idp(oidc_app, monkeypatch, claims={}, raise_on_callback=True)
    with oidc_app.test_client() as c:
        r = c.get("/auth/callback?state=state-abc&code=xyz", follow_redirects=True)
        body = r.get_data(as_text=True)
        assert "at-secret" not in body
        assert "user said no" not in body  # raw exception message not surfaced
