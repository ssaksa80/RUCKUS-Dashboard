"""auth.users — user store over the db (argon2id, bootstrap, login record).

In-memory SQLite; no app, no controllers.
"""
from __future__ import annotations

import datetime as dt

import pytest

from ruckus_dashboard import db as dbmod
from ruckus_dashboard.auth import users
from ruckus_dashboard.db.models import AuditLog, Base, Role, Tenant, User


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
        engine.dispose()


@pytest.fixture
def tenant(session):
    t = Tenant(name="default")
    session.add(t)
    session.commit()
    return t


# ── password hashing ────────────────────────────────────────────────────────

def test_create_user_hashes_password_not_plaintext(session, tenant):
    u = users.create_user(
        session, tenant_id=tenant.id, email="a@b.c",
        password="s3cret-pass", role="operator",
    )
    session.commit()
    assert u.password_hash is not None
    assert u.password_hash != "s3cret-pass"
    assert "s3cret-pass" not in u.password_hash
    assert u.password_hash.startswith("$argon2")


def test_verify_password_roundtrip(session, tenant):
    u = users.create_user(session, tenant_id=tenant.id, email="a@b.c",
                          password="hunter2aaa", role="viewer")
    session.commit()
    assert users.verify_password(u, "hunter2aaa") is True
    assert users.verify_password(u, "wrong") is False


def test_verify_password_false_when_no_hash(session, tenant):
    # OIDC-only user (PB2) has password_hash=None -> local verify must fail.
    u = users.create_user(session, tenant_id=tenant.id, email="oidc@b.c",
                          password=None, role="viewer")
    session.commit()
    assert u.password_hash is None
    assert users.verify_password(u, "anything") is False
    assert users.verify_password(u, "") is False


def test_set_password_updates_hash(session, tenant):
    u = users.create_user(session, tenant_id=tenant.id, email="a@b.c",
                          password="orig-pass-aa", role="viewer")
    session.commit()
    old = u.password_hash
    users.set_password(u, "new-pass-bbb")
    session.commit()
    assert u.password_hash != old
    assert users.verify_password(u, "new-pass-bbb") is True
    assert users.verify_password(u, "orig-pass-aa") is False


def test_get_by_email_is_case_insensitive_and_none_missing(session, tenant):
    users.create_user(session, tenant_id=tenant.id, email="Mixed@Case.Com",
                      password="pw-aaaaaa", role="viewer")
    session.commit()
    assert users.get_by_email(session, "mixed@case.com") is not None
    assert users.get_by_email(session, "MIXED@CASE.COM") is not None
    assert users.get_by_email(session, "absent@x.y") is None


def test_email_stored_normalized_lowercase(session, tenant):
    u = users.create_user(session, tenant_id=tenant.id, email="  UP@X.Y  ",
                          password="pw-aaaaaa", role="viewer")
    session.commit()
    assert u.email == "up@x.y"


# ── bootstrap_admin (break-glass) ────────────────────────────────────────────

def test_bootstrap_admin_seeds_one_admin_from_env_password(session, tenant):
    created, pw = users.bootstrap_admin(session, tenant_id=tenant.id,
                                        password="Env-Provided-1")
    session.commit()
    assert created is not None
    assert created.role == Role.admin.name
    assert pw is None  # not randomly generated -> nothing to surface
    assert users.verify_password(created, "Env-Provided-1") is True
    admins = session.query(User).filter_by(role=Role.admin.name).all()
    assert len(admins) == 1


def test_bootstrap_admin_generates_random_when_no_password(session, tenant):
    created, pw = users.bootstrap_admin(session, tenant_id=tenant.id, password=None)
    session.commit()
    assert created is not None
    assert pw is not None and len(pw) >= 16  # surfaced once by caller
    assert users.verify_password(created, pw) is True


def test_bootstrap_admin_is_idempotent(session, tenant):
    users.bootstrap_admin(session, tenant_id=tenant.id, password="First-Pass-1")
    session.commit()
    created2, pw2 = users.bootstrap_admin(session, tenant_id=tenant.id,
                                         password="Second-Pass-2")
    session.commit()
    # No second user seeded; existing admin untouched.
    assert created2 is None
    assert pw2 is None
    assert session.query(User).count() == 1
    existing = session.query(User).one()
    assert users.verify_password(existing, "First-Pass-1") is True
    assert users.verify_password(existing, "Second-Pass-2") is False


def test_bootstrap_admin_skips_when_any_user_exists(session, tenant):
    users.create_user(session, tenant_id=tenant.id, email="someone@x.y",
                      password="pw-aaaaaa", role="viewer")
    session.commit()
    created, pw = users.bootstrap_admin(session, tenant_id=tenant.id, password="X-1")
    session.commit()
    assert created is None
    assert session.query(User).filter_by(role=Role.admin.name).count() == 0


# ── record_login ─────────────────────────────────────────────────────────────

def test_record_login_sets_last_login_at(session, tenant):
    u = users.create_user(session, tenant_id=tenant.id, email="a@b.c",
                          password="pw-aaaaaa", role="viewer")
    session.commit()
    assert u.last_login_at is None
    users.record_login(session, u)
    session.commit()
    assert isinstance(u.last_login_at, dt.datetime)


def test_create_user_rejects_invalid_role(session, tenant):
    with pytest.raises((KeyError, ValueError)):
        users.create_user(session, tenant_id=tenant.id, email="a@b.c",
                          password="pw-aaaaaa", role="superhero")
