"""NotificationConfigStore — DB-backed, per-tenant (PB3).

Preserves the exact config shape + SP2/SP7 behaviour (DEFAULTS, deep
section-merge, password masking / password_enc, channels, outage defaults) that
the file-based load_config/save_config have, but persists one JSON blob per
tenant in the notification_config table. Tenant A and B keep independent config.
"""
from __future__ import annotations

import pytest
from flask import Flask

from ruckus_dashboard import db as dbmod
from ruckus_dashboard.db.models import NotificationConfig, Tenant
from ruckus_dashboard.notify import config as cfg_mod
from ruckus_dashboard.notify.config import NotificationConfigStore


class FakeSecrets:
    def encrypt(self, s):
        return f"enc:{s}"

    def decrypt(self, s):
        assert s.startswith("enc:")
        return s[4:]


@pytest.fixture
def app(tmp_instance):
    app = Flask(__name__)
    app.instance_path = tmp_instance
    app.config["RUCKUS_DATABASE_URL"] = "sqlite:///:memory:"
    dbmod.init_db(app)
    with dbmod.session_scope(app) as s:
        s.add_all([Tenant(name="default"), Tenant(name="other")])
    app.secrets_manager = FakeSecrets()
    return app


@pytest.fixture
def store(app):
    return NotificationConfigStore(app, default_tenant_id=1)


def test_defaults_when_missing(store):
    cfg = store.load_config(tenant_id=1)
    assert cfg["smtp"]["port"] == 587
    assert cfg["alerts"]["rules"]["critical_alarm"] is True
    assert cfg["report"]["time"] == "07:00"
    # SP2 defaults present
    assert cfg["alerts"]["recovery"] is True
    assert cfg["alerts"]["debounce_seconds"] == 120
    assert cfg["alerts"]["group_by"] == "site"
    assert isinstance(cfg["alerts"]["channels"], dict)


def test_password_encrypted_masked_and_preserved(store, app):
    saved = store.save_config(
        {"smtp": {"host": "mail.x", "password": "hunter2"},
         "alerts": {"enabled": True, "recipients": ["a@x"]}},
        app.secrets_manager, tenant_id=1,
    )
    # encrypted at rest in the DB, never plaintext
    with dbmod.session_scope(app) as s:
        row = s.query(NotificationConfig).filter_by(tenant_id=1).one()
        assert row.config["smtp"]["password_enc"] == "enc:hunter2"
        assert "password" not in row.config["smtp"]
    # masked for display
    disp = cfg_mod.display_config(saved)
    assert disp["smtp"]["password"] == cfg_mod.PASSWORD_MASK
    # posting the mask back preserves the stored secret
    saved2 = store.save_config(
        {"smtp": {"host": "mail.x", "password": cfg_mod.PASSWORD_MASK}},
        app.secrets_manager, tenant_id=1,
    )
    assert store.smtp_password(saved2, app.secrets_manager) == "hunter2"


def test_partial_post_preserves_other_subkeys(store, app):
    store.save_config(
        {"report": {"enabled": True, "recipients": ["a@x"], "time": "06:00"}},
        app.secrets_manager, tenant_id=1,
    )
    store.save_config(
        {"report": {"enabled": False}}, app.secrets_manager, tenant_id=1
    )
    cfg = store.load_config(tenant_id=1)
    assert cfg["report"]["enabled"] is False
    assert cfg["report"]["recipients"] == ["a@x"]
    assert cfg["report"]["time"] == "06:00"


def test_channels_and_rules_deep_merge(store, app):
    store.save_config(
        {"alerts": {"rules": {"ap_offline": False}}},
        app.secrets_manager, tenant_id=1,
    )
    cfg = store.load_config(tenant_id=1)
    # overridden rule flipped, other rules keep their defaults
    assert cfg["alerts"]["rules"]["ap_offline"] is False
    assert cfg["alerts"]["rules"]["switch_offline"] is True
    assert isinstance(cfg["alerts"]["channels"], dict)
    assert "email" in cfg["alerts"]["channels"]


# ── per-tenant isolation ─────────────────────────────────────────────────────

def test_config_is_per_tenant(store, app):
    store.save_config(
        {"smtp": {"host": "tenant1.mail"}, "alerts": {"recipients": ["one@x"]}},
        app.secrets_manager, tenant_id=1,
    )
    store.save_config(
        {"smtp": {"host": "tenant2.mail"}, "alerts": {"recipients": ["two@x"]}},
        app.secrets_manager, tenant_id=2,
    )
    c1 = store.load_config(tenant_id=1)
    c2 = store.load_config(tenant_id=2)
    assert c1["smtp"]["host"] == "tenant1.mail"
    assert c2["smtp"]["host"] == "tenant2.mail"
    assert c1["alerts"]["recipients"] == ["one@x"]
    assert c2["alerts"]["recipients"] == ["two@x"]


def test_tenant_b_password_isolated(store, app):
    store.save_config(
        {"smtp": {"host": "m", "password": "secret-1"}},
        app.secrets_manager, tenant_id=1,
    )
    # Tenant 2 has no config yet -> empty password, cannot read tenant 1's.
    c2 = store.load_config(tenant_id=2)
    assert store.smtp_password(c2, app.secrets_manager) == ""


def test_default_tenant_when_unspecified(store, app):
    # No explicit tenant_id -> default tenant (1).
    store.save_config({"smtp": {"host": "def.mail"}}, app.secrets_manager)
    cfg = store.load_config()
    assert cfg["smtp"]["host"] == "def.mail"
    with dbmod.session_scope(app) as s:
        assert s.query(NotificationConfig).filter_by(tenant_id=1).count() == 1
