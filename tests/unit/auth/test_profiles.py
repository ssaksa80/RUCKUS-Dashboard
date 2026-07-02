"""ProfileStore — DB-backed + tenant-scoped (PB3).

Profiles now live in the ``profiles`` table (migrated off ``profiles.json``),
scoped by tenant. Secrets are still Fernet-encrypted via SecretsManager; the DB
holds ciphertext only. A profile from tenant A must never be visible to tenant
B (isolation).
"""
from __future__ import annotations

import pytest
from flask import Flask

from ruckus_dashboard import db as dbmod
from ruckus_dashboard.db.models import Tenant
from ruckus_dashboard.auth.secrets import SecretsManager
from ruckus_dashboard.auth.profiles import ProfileStore


@pytest.fixture
def app(tmp_instance):
    """Bare Flask app with an in-memory DB + two tenants (a=1 default, b=2)."""
    app = Flask(__name__)
    app.instance_path = tmp_instance
    app.config["RUCKUS_DATABASE_URL"] = "sqlite:///:memory:"
    dbmod.init_db(app)
    with dbmod.session_scope(app) as s:
        s.add_all([Tenant(name="default"), Tenant(name="other")])
    app.secrets_manager = SecretsManager(tmp_instance)
    return app


@pytest.fixture
def store(app):
    return ProfileStore(app, app.secrets_manager)


def test_save_list_delete(store, app):
    form = {"platform": "smartzone", "smartzone_host": "sz.example",
            "smartzone_username": "admin", "smartzone_password": "hunter2"}
    store.save("lab", form, tenant_id=1)
    items = store.list_masked(tenant_id=1)
    assert any(item["name"] == "lab" for item in items)
    lab = next(i for i in items if i["name"] == "lab")
    assert lab["smartzone_host"] == "sz.example"
    assert lab["has_secret"] is True
    assert lab["saved_at"]
    pw = store.resolve_secret("lab", "smartzone_password", tenant_id=1)
    if app.secrets_manager.available():
        assert pw == "hunter2"
    store.delete("lab", tenant_id=1)
    assert not any(item["name"] == "lab" for item in store.list_masked(tenant_id=1))


def test_save_requires_profile_name(store):
    with pytest.raises(ValueError):
        store.save("", {"platform": "smartzone"}, tenant_id=1)


def test_secret_not_stored_in_plaintext(store, app):
    if not app.secrets_manager.available():
        pytest.skip("Fernet unavailable in this environment")
    store.save("lab", {"platform": "smartzone", "smartzone_password": "topsecret"},
               tenant_id=1)
    from ruckus_dashboard.db.models import Profile
    with dbmod.session_scope(app) as s:
        row = s.query(Profile).filter_by(name="lab", tenant_id=1).one()
        enc = row.enc_secret_fields["_enc_smartzone_password"]
        assert "topsecret" not in enc  # ciphertext, never plaintext


def test_untouched_password_sentinel_preserves_secret(store, app):
    if not app.secrets_manager.available():
        pytest.skip("Fernet unavailable in this environment")
    store.save("lab", {"platform": "smartzone", "smartzone_password": "hunter2"},
               tenant_id=1)
    # Re-save with the sentinel (UI left the field unchanged) — must keep secret.
    store.save("lab", {"platform": "smartzone", "smartzone_host": "sz2",
                       "smartzone_password": "__profile_password__"}, tenant_id=1)
    assert store.resolve_secret("lab", "smartzone_password", tenant_id=1) == "hunter2"
    # And the plain field update took effect.
    lab = next(i for i in store.list_masked(tenant_id=1) if i["name"] == "lab")
    assert lab["smartzone_host"] == "sz2"


def test_count_is_per_tenant(store):
    store.save("a", {"platform": "smartzone"}, tenant_id=1)
    store.save("b", {"platform": "smartzone"}, tenant_id=1)
    store.save("a", {"platform": "smartzone"}, tenant_id=2)
    assert store.count(tenant_id=1) == 2
    assert store.count(tenant_id=2) == 1


# ── tenant isolation ───────────────────────────────────────────────────────

def test_tenant_a_cannot_list_tenant_b_profile(store):
    store.save("secret-b", {"platform": "smartzone",
                            "smartzone_host": "b.host"}, tenant_id=2)
    names_a = [i["name"] for i in store.list_masked(tenant_id=1)]
    assert "secret-b" not in names_a
    names_b = [i["name"] for i in store.list_masked(tenant_id=2)]
    assert "secret-b" in names_b


def test_tenant_a_cannot_resolve_tenant_b_secret(store, app):
    if not app.secrets_manager.available():
        pytest.skip("Fernet unavailable in this environment")
    store.save("prof", {"platform": "smartzone",
                        "smartzone_password": "b-secret"}, tenant_id=2)
    # Same profile name in tenant A does not exist -> empty secret.
    assert store.resolve_secret("prof", "smartzone_password", tenant_id=1) == ""
    # Tenant B still resolves its own.
    assert store.resolve_secret("prof", "smartzone_password", tenant_id=2) == "b-secret"


def test_tenant_a_delete_does_not_touch_tenant_b(store):
    store.save("shared", {"platform": "smartzone"}, tenant_id=1)
    store.save("shared", {"platform": "smartzone"}, tenant_id=2)
    store.delete("shared", tenant_id=1)
    assert store.count(tenant_id=1) == 0
    # Tenant B's same-named profile survives.
    assert any(i["name"] == "shared" for i in store.list_masked(tenant_id=2))


def test_same_name_two_tenants_independent_secrets(store, app):
    if not app.secrets_manager.available():
        pytest.skip("Fernet unavailable in this environment")
    store.save("lab", {"platform": "smartzone",
                       "smartzone_password": "aaa"}, tenant_id=1)
    store.save("lab", {"platform": "smartzone",
                       "smartzone_password": "bbb"}, tenant_id=2)
    assert store.resolve_secret("lab", "smartzone_password", tenant_id=1) == "aaa"
    assert store.resolve_secret("lab", "smartzone_password", tenant_id=2) == "bbb"
