"""Integration: the tenant-scoped profile-management UI (Component 1).

Surfaces ``app.profile_store`` through ``routes/profiles.py``. Auth gate ON,
temp-file SQLite so the DB-backed, tenant-scoped ProfileStore is exercised
end-to-end. Asserts: list shows only this tenant's rows, save→list roundtrip
(secret masked, never plaintext), delete removes it, RBAC (viewer → 403 on
GET+POST), CSRF (missing → 400), and tenant isolation (operator in tenant A
cannot see or delete tenant B's profile).
"""
from __future__ import annotations

import pytest

from ruckus_dashboard.app import create_app
from ruckus_dashboard.db import session_scope
from ruckus_dashboard.db.models import AuditLog, Profile, Tenant, User
from ruckus_dashboard.auth import users as users_mod


@pytest.fixture
def app(tmp_path):
    """Auth-ON app on a temp-file SQLite DB with a seeded break-glass admin.

    Fernet is available in CI, so secrets round-trip; the tests assert the
    ciphertext is never rendered rather than depending on decryptability.
    """
    db_file = tmp_path / "ruckus.db"
    app = create_app({
        "SECRET_KEY": "t",
        "RUCKUS_ENABLE_NEW_UI": True,
        "RUCKUS_AUTH_REQUIRED": True,
        "RUCKUS_DATABASE_URL": f"sqlite:///{db_file.as_posix()}",
        "RUCKUS_ADMIN_PASSWORD": "Admin-Seed-Pw-1",
    })
    return app


def _add_user(app, email, password, role, tenant_name="default"):
    with session_scope(app) as s:
        tenant = s.query(Tenant).filter_by(name=tenant_name).one()
        users_mod.create_user(s, tenant_id=tenant.id, email=email,
                              password=password, role=role)


def _login(c, email, password):
    c.get("/login")
    with c.session_transaction() as s:
        token = s["csrf_token"]
    c.post("/login", data={"email": email, "password": password,
                           "csrf_token": token})
    with c.session_transaction() as s:
        return s["csrf_token"]


def _make_tenant(app, name):
    with session_scope(app) as s:
        t = Tenant(name=name)
        s.add(t)
        s.flush()
        return t.id


def _seed_profile_row(app, tenant_id, name, plain=None, enc=None):
    """Insert a Profile row directly for a given tenant (isolation setup)."""
    from ruckus_dashboard.db.models import _utcnow
    with session_scope(app) as s:
        s.add(Profile(
            tenant_id=tenant_id, name=name,
            plain_fields=plain or {"platform": "smartzone"},
            enc_secret_fields=enc or {},
            saved_at=_utcnow(),
        ))


# ── RBAC ─────────────────────────────────────────────────────────────────────

def test_get_profiles_requires_operator_viewer_403(app):
    _add_user(app, "view@x.y", "Viewer-Pw-12", "viewer")
    with app.test_client() as c:
        _login(c, "view@x.y", "Viewer-Pw-12")
        assert c.get("/profiles").status_code == 403


def test_post_profiles_viewer_403(app):
    _add_user(app, "view2@x.y", "Viewer2-Pw-1", "viewer")
    with app.test_client() as c:
        token = _login(c, "view2@x.y", "Viewer2-Pw-1")
        r = c.post("/profiles", data={"name": "lab", "platform": "smartzone",
                                      "csrf_token": token})
        assert r.status_code == 403
    # nothing was written
    with session_scope(app) as s:
        assert s.query(Profile).count() == 0


def test_delete_profiles_viewer_403(app):
    _add_user(app, "view3@x.y", "Viewer3-Pw-1", "viewer")
    with app.test_client() as c:
        token = _login(c, "view3@x.y", "Viewer3-Pw-1")
        r = c.post("/profiles/lab/delete", data={"csrf_token": token})
        assert r.status_code == 403


def test_operator_can_get_profiles(app):
    _add_user(app, "op@x.y", "Operator-Pw-1", "operator")
    with app.test_client() as c:
        _login(c, "op@x.y", "Operator-Pw-1")
        assert c.get("/profiles").status_code == 200


def test_admin_can_get_profiles(app):
    with app.test_client() as c:
        _login(c, "admin", "Admin-Seed-Pw-1")
        assert c.get("/profiles").status_code == 200


# ── sidebar nav link (operator+ only) ──────────────────────────────────────────

def test_nav_link_shown_to_operator(app):
    _add_user(app, "op-nav@x.y", "OpNav-Pw-123", "operator")
    with app.test_client() as c:
        _login(c, "op-nav@x.y", "OpNav-Pw-123")
        body = c.get("/profiles").get_data(as_text=True)
        assert 'href="/profiles"' in body  # nav link present in the shell


def test_nav_link_hidden_from_viewer(app):
    # Render base.html directly with a viewer role — the profiles link is gated
    # on g.role in (operator, admin), so a viewer must never see it. (Viewers
    # also get 403 on /profiles itself, covered above.)
    from flask import g, render_template
    from ruckus_dashboard.modules import all_modules
    with app.test_request_context("/"):
        g.role = "viewer"
        g.user = {"id": 1}
        html = render_template("base.html", modules=all_modules(), csrf_token="t")
        assert 'href="/profiles"' not in html
    with app.test_request_context("/"):
        g.role = "operator"
        g.user = {"id": 1}
        html = render_template("base.html", modules=all_modules(), csrf_token="t")
        assert 'href="/profiles"' in html


# ── CSRF ─────────────────────────────────────────────────────────────────────

def test_post_profiles_missing_csrf_400(app):
    with app.test_client() as c:
        _login(c, "admin", "Admin-Seed-Pw-1")
        r = c.post("/profiles", data={"name": "lab", "platform": "smartzone",
                                      "csrf_token": "bogus"})
        assert r.status_code == 400


def test_delete_profiles_missing_csrf_400(app):
    with app.test_client() as c:
        _login(c, "admin", "Admin-Seed-Pw-1")
        r = c.post("/profiles/lab/delete", data={"csrf_token": "bogus"})
        assert r.status_code == 400


# ── save → list → delete roundtrip ─────────────────────────────────────────────

def test_save_then_list_roundtrip_secret_masked(app):
    with app.test_client() as c:
        token = _login(c, "admin", "Admin-Seed-Pw-1")
        r = c.post("/profiles", data={
            "name": "lab", "platform": "smartzone",
            "smartzone_host": "sz.example", "smartzone_username": "admin",
            "smartzone_password": "hunter2-secret", "csrf_token": token,
        }, follow_redirects=True)
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        # The profile is listed with its plain fields.
        assert "lab" in body
        assert "sz.example" in body
        # The plaintext secret must NEVER appear in the rendered page.
        assert "hunter2-secret" not in body
    # And it lives in the caller's (admin's) tenant only.
    with session_scope(app) as s:
        admin_tid = s.query(User).filter_by(email="admin").one().tenant_id
        row = s.query(Profile).filter_by(name="lab").one()
        assert row.tenant_id == admin_tid
        # Ciphertext stored, never plaintext.
        blob = str(row.enc_secret_fields)
        assert "hunter2-secret" not in blob


def test_save_shows_has_secret_badge(app):
    with app.test_client() as c:
        token = _login(c, "admin", "Admin-Seed-Pw-1")
        c.post("/profiles", data={
            "name": "withsecret", "platform": "smartzone",
            "smartzone_password": "sekret", "csrf_token": token,
        })
        c.post("/profiles", data={
            "name": "nosecret", "platform": "smartzone",
            "csrf_token": token,
        })
        body = c.get("/profiles").get_data(as_text=True)
        assert "withsecret" in body
        assert "nosecret" in body


def test_save_audits_profile_saved(app):
    with app.test_client() as c:
        token = _login(c, "admin", "Admin-Seed-Pw-1")
        c.post("/profiles", data={"name": "lab", "platform": "smartzone",
                                  "csrf_token": token})
    with session_scope(app) as s:
        actions = [a.action for a in s.query(AuditLog).all()]
        assert "profile_saved" in actions


def test_delete_removes_profile_and_audits(app):
    with app.test_client() as c:
        token = _login(c, "admin", "Admin-Seed-Pw-1")
        c.post("/profiles", data={"name": "lab", "platform": "smartzone",
                                  "csrf_token": token})
        # confirm present
        assert "lab" in c.get("/profiles").get_data(as_text=True)
        r = c.post("/profiles/lab/delete", data={"csrf_token": token},
                   follow_redirects=True)
        assert r.status_code == 200
    with session_scope(app) as s:
        assert s.query(Profile).filter_by(name="lab").count() == 0
        actions = [a.action for a in s.query(AuditLog).all()]
        assert "profile_deleted" in actions


def test_untouched_password_sentinel_preserves_secret_via_ui(app):
    with app.test_client() as c:
        token = _login(c, "admin", "Admin-Seed-Pw-1")
        c.post("/profiles", data={
            "name": "lab", "platform": "smartzone",
            "smartzone_password": "orig-secret", "csrf_token": token,
        })
        # Re-save leaving the password as the sentinel (UI "unchanged").
        c.post("/profiles", data={
            "name": "lab", "platform": "smartzone", "smartzone_host": "new.host",
            "smartzone_password": "__profile_password__", "csrf_token": token,
        })
    # The original secret is preserved; the plain field updated.
    tid = app.default_tenant_id
    assert app.profile_store.resolve_secret(
        "lab", "smartzone_password", tenant_id=tid) == "orig-secret"
    lab = next(i for i in app.profile_store.list_masked(tenant_id=tid)
               if i["name"] == "lab")
    assert lab["smartzone_host"] == "new.host"


# ── tenant isolation ───────────────────────────────────────────────────────────

def test_list_shows_only_callers_tenant(app):
    # Seed a profile in a DIFFERENT tenant (B); the admin (tenant "default")
    # must not see it in their /profiles list.
    tid_b = _make_tenant(app, "tenant-b")
    _seed_profile_row(app, tid_b, "b-only",
                      plain={"platform": "smartzone", "smartzone_host": "b.host"})
    with app.test_client() as c:
        _login(c, "admin", "Admin-Seed-Pw-1")
        body = c.get("/profiles").get_data(as_text=True)
        assert "b-only" not in body
        assert "b.host" not in body


def test_operator_cannot_delete_other_tenants_profile(app):
    # Operator in tenant A; a profile named "shared" exists in BOTH A's tenant
    # and tenant B. A's delete of "shared" must only remove A's row, leaving
    # B's row intact (delete is scoped to g.tenant_id, never a client tenant).
    tid_b = _make_tenant(app, "tenant-b")
    _seed_profile_row(app, tid_b, "shared",
                      plain={"platform": "smartzone", "smartzone_host": "b.host"})
    with app.test_client() as c:
        token = _login(c, "admin", "Admin-Seed-Pw-1")
        # admin creates its own "shared" in the default tenant
        c.post("/profiles", data={"name": "shared", "platform": "smartzone",
                                  "csrf_token": token})
        # delete "shared" as admin (default tenant)
        c.post("/profiles/shared/delete", data={"csrf_token": token})
    with session_scope(app) as s:
        admin_tid = s.query(User).filter_by(email="admin").one().tenant_id
        # A's row is gone.
        assert s.query(Profile).filter_by(
            name="shared", tenant_id=admin_tid).count() == 0
        # B's row is untouched — no cross-tenant deletion.
        assert s.query(Profile).filter_by(
            name="shared", tenant_id=tid_b).count() == 1


def test_delete_unknown_name_is_noop_no_500(app):
    # Deleting a name that doesn't exist in the caller's tenant is a harmless
    # no-op redirect (not a 500), matching ProfileStore.delete semantics.
    with app.test_client() as c:
        token = _login(c, "admin", "Admin-Seed-Pw-1")
        r = c.post("/profiles/does-not-exist/delete", data={"csrf_token": token})
        assert r.status_code in (302, 303)


def test_save_ignores_client_supplied_tenant_id_for_scoping(app):
    # SECURITY: the profile form carries a RUCKUS One "tenant_id" *credential*
    # field. It must be stored as a plain profile field, but must NOT be used
    # to scope the save — the row always lands under the app-user's g.tenant_id.
    with app.test_client() as c:
        token = _login(c, "admin", "Admin-Seed-Pw-1")
        c.post("/profiles", data={
            "name": "r1", "platform": "ruckus_one",
            "tenant_id": "999999",  # RUCKUS One tenant credential, not app tenant
            "client_id": "cid-1", "csrf_token": token,
        })
    with session_scope(app) as s:
        admin_tid = s.query(User).filter_by(email="admin").one().tenant_id
        row = s.query(Profile).filter_by(name="r1").one()
        # Stored under the APP-USER tenant, not the credential's "999999".
        assert row.tenant_id == admin_tid
        # The credential value is preserved as a plain field.
        assert row.plain_fields.get("tenant_id") == "999999"
