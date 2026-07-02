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
from ruckus_dashboard.db.models import AuditLog, Role, Tenant, User


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


def test_upsert_refuses_to_attach_subject_by_email_claim(app):
    # SECURITY: an inbound OIDC identity whose email matches an existing LOCAL
    # account must NOT attach/hijack that account (email is an attacker-
    # influenceable IdP claim; Authlib validates iss/aud/exp/nonce/signature,
    # NOT email ownership). The upsert must refuse with OidcEmailConflict and
    # leave the existing account untouched — no subject bound, role unchanged.
    tid = _default_tenant_id(app)
    with session_scope(app) as s:
        users_mod.create_user(
            s, tenant_id=tid, email="carol@corp.local",
            password="Local-Pw-12345", role="viewer",
        )
    with pytest.raises(users_mod.OidcEmailConflict) as exc:
        users_mod.upsert_oidc_user(
            app, subject="sub-attacker", email="carol@corp.local",
            display_name="Carol", role=Role.admin,
        )
    assert exc.value.email == "carol@corp.local"
    with session_scope(app) as s:
        rows = s.query(User).filter(User.email == "carol@corp.local").all()
        assert len(rows) == 1  # no duplicate created
        row = rows[0]
        assert row.oidc_subject is None  # subject NOT bound — no hijack
        assert row.role == Role.viewer.name  # role NOT escalated
        # No attacker subject leaked onto any row.
        assert s.query(User).filter_by(oidc_subject="sub-attacker").count() == 0


def test_upsert_break_glass_admin_cannot_be_hijacked_by_email(app):
    # The seeded break-glass admin has email "admin". An OIDC identity claiming
    # email="admin" must be refused, never rewriting the admin row.
    with pytest.raises(users_mod.OidcEmailConflict) as exc:
        users_mod.upsert_oidc_user(
            app, subject="sub-attacker-admin", email="admin",
            display_name="Not The Admin", role=Role.admin,
        )
    assert exc.value.email == "admin"
    with session_scope(app) as s:
        admin = s.query(User).filter_by(email="admin").one()
        assert admin.oidc_subject is None  # break-glass subject untouched
        assert admin.role == Role.admin.name
        assert admin.password_hash is not None  # local break-glass password kept
        assert s.query(User).filter_by(oidc_subject="sub-attacker-admin").count() == 0


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


# ── role_changed audit (only on change) ──────────────────────────────────────

def _role_changed_rows(app):
    with session_scope(app) as s:
        return [
            {"user_id": a.user_id, "tenant_id": a.tenant_id,
             "detail": dict(a.detail or {})}
            for a in s.query(AuditLog).filter_by(action="role_changed").all()
        ]


def test_upsert_role_change_writes_one_audit(app):
    first = users_mod.upsert_oidc_user(
        app, subject="sub-rc", email="rc@corp.local",
        display_name="RC", role=Role.viewer,
    )
    uid, tid = first.id, first.tenant_id
    # Second login, same subject, higher role mapped from the IdP groups.
    users_mod.upsert_oidc_user(
        app, subject="sub-rc", email="rc@corp.local",
        display_name="RC", role=Role.operator,
    )
    rows = _role_changed_rows(app)
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == uid
    assert row["tenant_id"] == tid
    assert row["detail"] == {
        "method": "oidc", "from": Role.viewer.name, "to": Role.operator.name,
    }


def test_upsert_same_role_writes_no_audit(app):
    users_mod.upsert_oidc_user(
        app, subject="sub-same", email="same@corp.local",
        display_name="S", role=Role.operator,
    )
    # Re-login with the identical role — nothing changed, no audit.
    users_mod.upsert_oidc_user(
        app, subject="sub-same", email="same@corp.local",
        display_name="S", role=Role.operator,
    )
    assert _role_changed_rows(app) == []


def test_upsert_new_user_writes_no_role_changed_audit(app):
    # A brand-new JIT user is not a "change" from an existing role.
    users_mod.upsert_oidc_user(
        app, subject="sub-new-rc", email="newrc@corp.local",
        display_name="N", role=Role.admin,
    )
    assert _role_changed_rows(app) == []


def test_upsert_role_change_records_correct_direction(app):
    # Downgrades are audited too (operator -> viewer), with from/to correct.
    users_mod.upsert_oidc_user(
        app, subject="sub-down", email="down@corp.local",
        display_name="D", role=Role.operator,
    )
    users_mod.upsert_oidc_user(
        app, subject="sub-down", email="down@corp.local",
        display_name="D", role=Role.viewer,
    )
    rows = _role_changed_rows(app)
    assert len(rows) == 1
    assert rows[0]["detail"]["from"] == Role.operator.name
    assert rows[0]["detail"]["to"] == Role.viewer.name
