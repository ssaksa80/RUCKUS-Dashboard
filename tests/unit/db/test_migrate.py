"""PB3 import-on-boot: file-based state → DB (idempotent).

profiles.json / notifications.json are imported under the default tenant the
first time; a second import (a re-boot) must NOT duplicate. Encrypted secret
fields carry over verbatim (already Fernet ciphertext).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask import Flask

from ruckus_dashboard import db as dbmod
from ruckus_dashboard.db import migrate
from ruckus_dashboard.db.models import NotificationConfig, Profile, Tenant


@pytest.fixture
def app(tmp_instance):
    app = Flask(__name__)
    app.instance_path = tmp_instance
    app.config["RUCKUS_DATABASE_URL"] = "sqlite:///:memory:"
    dbmod.init_db(app)
    with dbmod.session_scope(app) as s:
        s.add(Tenant(name="default"))
    return app


def _write_profiles(instance_path: str) -> None:
    data = {
        "lab": {
            "platform": "smartzone",
            "smartzone_host": "sz.example",
            "smartzone_username": "admin",
            "_enc_smartzone_password": "gAAAA-already-ciphertext",
            "saved_at": "2026-06-01 00:00:00 UTC",
        },
        "prod": {"platform": "ruckus_one", "client_id": "cid"},
    }
    Path(instance_path, "profiles.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


# ── profiles ────────────────────────────────────────────────────────────────

def test_import_profiles_populates_table(app):
    _write_profiles(app.instance_path)
    n = migrate.import_profiles(app, 1)
    assert n == 2
    with dbmod.session_scope(app) as s:
        rows = {p.name: p for p in s.query(Profile).all()}
        assert set(rows) == {"lab", "prod"}
        assert rows["lab"].tenant_id == 1
        assert rows["lab"].plain_fields["smartzone_host"] == "sz.example"
        # ciphertext carried over verbatim into enc_secret_fields
        assert (rows["lab"].enc_secret_fields["_enc_smartzone_password"]
                == "gAAAA-already-ciphertext")
        # a saved_at was set
        assert rows["lab"].saved_at is not None


def test_import_profiles_is_idempotent(app):
    _write_profiles(app.instance_path)
    assert migrate.import_profiles(app, 1) == 2
    # Second boot: file still present, but table non-empty -> no re-import.
    assert migrate.import_profiles(app, 1) == 0
    with dbmod.session_scope(app) as s:
        assert s.query(Profile).count() == 2


def test_import_profiles_missing_file_is_noop(app):
    assert migrate.import_profiles(app, 1) == 0
    with dbmod.session_scope(app) as s:
        assert s.query(Profile).count() == 0


# ── notification config ──────────────────────────────────────────────────────

def test_import_notification_config_populates_row(app):
    stored = {
        "smtp": {"host": "mail.x", "port": 25, "password_enc": "enc:secret"},
        "alerts": {"enabled": True, "recipients": ["a@x"]},
    }
    Path(app.instance_path, "notifications.json").write_text(
        json.dumps(stored), encoding="utf-8"
    )
    assert migrate.import_notification_config(app, 1) is True
    with dbmod.session_scope(app) as s:
        row = s.query(NotificationConfig).filter_by(tenant_id=1).one()
        # merged through defaults: host preserved, defaults filled in
        assert row.config["smtp"]["host"] == "mail.x"
        assert row.config["smtp"]["port"] == 25
        # ciphertext carried over verbatim
        assert row.config["smtp"]["password_enc"] == "enc:secret"
        # SP2 default keys present after the defaults merge
        assert row.config["alerts"]["debounce_seconds"] == 120


def test_import_notification_config_is_idempotent(app):
    Path(app.instance_path, "notifications.json").write_text(
        json.dumps({"smtp": {"host": "mail.x"}}), encoding="utf-8"
    )
    assert migrate.import_notification_config(app, 1) is True
    # Second boot: row exists -> no overwrite.
    assert migrate.import_notification_config(app, 1) is False
    with dbmod.session_scope(app) as s:
        assert s.query(NotificationConfig).count() == 1


def test_import_notification_config_missing_file_is_noop(app):
    assert migrate.import_notification_config(app, 1) is False
    with dbmod.session_scope(app) as s:
        assert s.query(NotificationConfig).count() == 0


def test_import_file_state_runs_both(app):
    _write_profiles(app.instance_path)
    Path(app.instance_path, "notifications.json").write_text(
        json.dumps({"smtp": {"host": "mail.x"}}), encoding="utf-8"
    )
    migrate.import_file_state(app, 1)
    with dbmod.session_scope(app) as s:
        assert s.query(Profile).count() == 2
        assert s.query(NotificationConfig).count() == 1
