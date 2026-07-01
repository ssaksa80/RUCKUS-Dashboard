"""db.models + db engine/session factory (SQLite, in-memory).

PB1 foundation: Tenant / User / Role / AuditLog and a scoped-session factory
built on a per-test in-memory engine. No app, no service containers.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import inspect

from ruckus_dashboard import db as dbmod
from ruckus_dashboard.db.models import AuditLog, Base, Role, Tenant, User


@pytest.fixture
def session():
    """A fresh in-memory DB + session for one test (StaticPool = one shared conn)."""
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


def test_create_all_builds_expected_tables():
    engine = dbmod.make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"tenants", "users", "audit_log"} <= tables


def test_tenant_and_user_roundtrip(session):
    t = Tenant(name="default")
    session.add(t)
    session.flush()
    u = User(
        tenant_id=t.id,
        email="admin@example.com",
        display_name="Admin",
        password_hash="$argon2id$fake",
        role=Role.admin.value,
    )
    session.add(u)
    session.commit()

    fetched = session.query(User).filter_by(email="admin@example.com").one()
    assert fetched.tenant_id == t.id
    assert fetched.is_active is True  # server/default default
    assert fetched.role == Role.admin.value
    assert fetched.oidc_subject is None
    assert isinstance(fetched.created_at, dt.datetime)
    assert fetched.last_login_at is None


def test_user_email_is_unique(session):
    t = Tenant(name="default")
    session.add(t)
    session.flush()
    session.add(User(tenant_id=t.id, email="dup@example.com", role=Role.viewer.value))
    session.commit()
    session.add(User(tenant_id=t.id, email="dup@example.com", role=Role.viewer.value))
    with pytest.raises(Exception):  # IntegrityError (unique constraint)
        session.commit()
    session.rollback()


def test_role_ordering_is_viewer_lt_operator_lt_admin():
    assert Role.viewer < Role.operator < Role.admin
    assert Role.admin > Role.viewer
    # int-backed so it can be stored/compared cheaply
    assert int(Role.viewer) < int(Role.admin)


def test_role_from_name_and_coerce():
    assert Role.coerce("admin") is Role.admin
    assert Role.coerce(Role.operator) is Role.operator
    assert Role.coerce("viewer") is Role.viewer
    with pytest.raises((KeyError, ValueError)):
        Role.coerce("wizard")


def test_auditlog_stores_json_detail(session):
    t = Tenant(name="default")
    session.add(t)
    session.flush()
    row = AuditLog(
        tenant_id=t.id,
        user_id=None,
        action="login_failure",
        detail={"email": "x@y.z", "reason": "bad_password"},
        ip="203.0.113.7",
    )
    session.add(row)
    session.commit()

    got = session.query(AuditLog).one()
    assert got.action == "login_failure"
    assert got.detail == {"email": "x@y.z", "reason": "bad_password"}
    assert got.ip == "203.0.113.7"
    assert isinstance(got.ts, dt.datetime)
