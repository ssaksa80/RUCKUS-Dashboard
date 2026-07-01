"""auth.users.upsert_oidc_user — JIT provisioning for OIDC (PB2).

Drives the real app factory (in-memory SQLite, gate OFF) so the default tenant
+ break-glass admin are seeded exactly as in production, then exercises the
just-in-time upsert used by the OIDC callback.
"""
from __future__ import annotations

import pytest

from ruckus_dashboard.app import create_app
from ruckus_dashboard.db import session_scope
from ruckus_dashboard.auth import users as users_mod
from ruckus_dashboard.db.models import Role, Tenant, User


@pytest.fixture
def app():
    # In-memory DB, auth gate off (factory default). OIDC config not needed for
    # the store-level upsert.
    return create_app({"SECRET_KEY": "t"})


def _default_tenant_id(app) -> int:
    with session_scope(app) as s:
        return s.query(Tenant).filter_by(name="default").one().id


def test_upsert_creates_new_oidc_user_in_default_tenant(app):
    user = users_mod.upsert_oidc_user(
        app, subject="sub-123", email="alice@corp.local",
        display_name="Alice", role=Role.operator,
    )
    assert user.id is not None
    assert user.oidc_subject == "sub-123"
    assert user.email == "alice@corp.local"
    assert user.display_name == "Alice"
    assert user.role == Role.operator.name
    assert user.tenant_id == _default_tenant_id(app)
    # OIDC accounts never carry a local password.
    assert user.password_hash is None
    assert user.last_login_at is not None


def test_upsert_same_subject_updates_not_duplicates(app):
    first = users_mod.upsert_oidc_user(
        app, subject="sub-xyz", email="bob@corp.local",
        display_name="Bob", role=Role.viewer,
    )
    first_id = first.id
    second = users_mod.upsert_oidc_user(
        app, subject="sub-xyz", email="bob@corp.local",
        display_name="Bob Renamed", role=Role.admin,
    )
    assert second.id == first_id  # same row
    with session_scope(app) as s:
        assert s.query(User).filter_by(oidc_subject="sub-xyz").count() == 1
        row = s.query(User).filter_by(oidc_subject="sub-xyz").one()
        assert row.display_name == "Bob Renamed"
        # Role is refreshed from the IdP group mapping on each login.
        assert row.role == Role.admin.name


def test_upsert_attaches_subject_to_existing_local_user_by_email(app):
    # A local user pre-exists (e.g. the break-glass admin, or an admin-created
    # account). First OIDC login for the same email attaches the subject rather
    # than creating a duplicate.
    tid = _default_tenant_id(app)
    with session_scope(app) as s:
        users_mod.create_user(
            s, tenant_id=tid, email="carol@corp.local",
            password="Local-Pw-12345", role="viewer",
        )
    user = users_mod.upsert_oidc_user(
        app, subject="sub-carol", email="carol@corp.local",
        display_name="Carol", role=Role.operator,
    )
    with session_scope(app) as s:
        rows = s.query(User).filter(User.email == "carol@corp.local").all()
        assert len(rows) == 1  # no duplicate
        row = rows[0]
        assert row.oidc_subject == "sub-carol"
        # Existing local password is preserved (still a break-glass path).
        assert row.password_hash is not None
    assert user.oidc_subject == "sub-carol"


def test_upsert_returns_detached_usable_user(app):
    # The returned object must be usable after the internal scope closes
    # (attributes accessible for the caller to set the session identity).
    user = users_mod.upsert_oidc_user(
        app, subject="sub-detach", email="d@corp.local",
        display_name=None, role=Role.viewer,
    )
    # Access after commit/close — would raise DetachedInstanceError if expired.
    assert user.id is not None
    assert user.tenant_id is not None
    assert user.role == Role.viewer.name


def test_upsert_email_normalized(app):
    user = users_mod.upsert_oidc_user(
        app, subject="sub-norm", email="  MixedCase@Corp.Local  ",
        display_name="M", role=Role.viewer,
    )
    assert user.email == "mixedcase@corp.local"
