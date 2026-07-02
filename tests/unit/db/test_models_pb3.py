"""PB3 models: Profile + NotificationConfig (tenant-scoped, SQLite in-memory).

Profile stores plain fields and Fernet-ciphertext secret fields as JSON;
NotificationConfig is one JSON blob per tenant (tenant_id is its PK).
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import inspect

from ruckus_dashboard import db as dbmod
from ruckus_dashboard.db.models import (
    Base,
    NotificationConfig,
    Profile,
    Tenant,
)


@pytest.fixture
def session():
    engine = dbmod.make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = dbmod.make_session_factory(engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        Session.remove()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_create_all_builds_pb3_tables():
    engine = dbmod.make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"profiles", "notification_config"} <= tables


def test_profile_roundtrip(session):
    t = Tenant(name="default")
    session.add(t)
    session.flush()
    p = Profile(
        tenant_id=t.id,
        name="lab",
        plain_fields={"platform": "smartzone", "smartzone_host": "sz.x"},
        enc_secret_fields={"_enc_smartzone_password": "gAAAA-ciphertext"},
    )
    session.add(p)
    session.commit()

    got = session.query(Profile).filter_by(name="lab").one()
    assert got.tenant_id == t.id
    assert got.plain_fields["smartzone_host"] == "sz.x"
    assert got.enc_secret_fields["_enc_smartzone_password"] == "gAAAA-ciphertext"
    assert isinstance(got.saved_at, dt.datetime)


def test_profile_name_unique_per_tenant(session):
    t = Tenant(name="default")
    session.add(t)
    session.flush()
    session.add(Profile(tenant_id=t.id, name="dup", plain_fields={},
                        enc_secret_fields={}))
    session.commit()
    session.add(Profile(tenant_id=t.id, name="dup", plain_fields={},
                        enc_secret_fields={}))
    with pytest.raises(Exception):  # IntegrityError (unique tenant_id+name)
        session.commit()
    session.rollback()


def test_profile_same_name_different_tenant_ok(session):
    a = Tenant(name="a")
    b = Tenant(name="b")
    session.add_all([a, b])
    session.flush()
    session.add(Profile(tenant_id=a.id, name="lab", plain_fields={},
                        enc_secret_fields={}))
    session.add(Profile(tenant_id=b.id, name="lab", plain_fields={},
                        enc_secret_fields={}))
    session.commit()  # must NOT raise — unique is (tenant_id, name)
    assert session.query(Profile).count() == 2


def test_notification_config_tenant_pk_roundtrip(session):
    t = Tenant(name="default")
    session.add(t)
    session.flush()
    nc = NotificationConfig(tenant_id=t.id, config={"smtp": {"host": "mail.x"}})
    session.add(nc)
    session.commit()

    got = session.query(NotificationConfig).filter_by(tenant_id=t.id).one()
    assert got.config["smtp"]["host"] == "mail.x"


def test_notification_config_one_row_per_tenant(session):
    t = Tenant(name="default")
    session.add(t)
    session.flush()
    session.add(NotificationConfig(tenant_id=t.id, config={}))
    session.commit()
    session.add(NotificationConfig(tenant_id=t.id, config={"x": 1}))
    with pytest.raises(Exception):  # tenant_id is the PK — duplicate rejected
        session.commit()
    session.rollback()
