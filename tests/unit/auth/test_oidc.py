"""auth.oidc — OIDC client registration, enable-gate, group→role map, claims.

No network: the Authlib client is registered but never called here (the
callback wiring + monkeypatched client are exercised in the integration test).
These are pure-unit checks of the helpers.
"""
from __future__ import annotations

import pytest
from flask import Flask

from ruckus_dashboard.auth import oidc
from ruckus_dashboard.db.models import Role


# ── map_groups_to_role ────────────────────────────────────────────────────────

def _cfg(group_roles: str) -> dict:
    return {"RUCKUS_OIDC_GROUP_ROLES": group_roles}


def test_map_groups_admin():
    cfg = _cfg("admins:admin,noc:operator")
    assert oidc.map_groups_to_role(["admins"], cfg) is Role.admin


def test_map_groups_operator():
    cfg = _cfg("admins:admin,noc:operator")
    assert oidc.map_groups_to_role(["noc"], cfg) is Role.operator


def test_map_groups_unmapped_defaults_viewer():
    cfg = _cfg("admins:admin,noc:operator")
    assert oidc.map_groups_to_role(["random"], cfg) is Role.viewer


def test_map_groups_empty_defaults_viewer():
    cfg = _cfg("admins:admin,noc:operator")
    assert oidc.map_groups_to_role([], cfg) is Role.viewer
    assert oidc.map_groups_to_role(None, cfg) is Role.viewer


def test_map_groups_highest_wins():
    cfg = _cfg("admins:admin,noc:operator")
    # Member of both -> the higher role (admin) wins regardless of order.
    assert oidc.map_groups_to_role(["noc", "admins"], cfg) is Role.admin
    assert oidc.map_groups_to_role(["admins", "noc"], cfg) is Role.admin


def test_map_groups_empty_config_all_viewer():
    cfg = _cfg("")
    assert oidc.map_groups_to_role(["admins"], cfg) is Role.viewer


def test_map_groups_ignores_malformed_entries():
    # Missing role, unknown role, blank entries, stray whitespace -> skipped;
    # valid ones still apply.
    cfg = _cfg(" admins : admin , broken , bad:notarole , :orphan , noc:operator ")
    assert oidc.map_groups_to_role(["admins"], cfg) is Role.admin
    assert oidc.map_groups_to_role(["noc"], cfg) is Role.operator
    assert oidc.map_groups_to_role(["broken"], cfg) is Role.viewer
    assert oidc.map_groups_to_role(["bad"], cfg) is Role.viewer


def test_map_groups_non_string_group_values_ignored():
    cfg = _cfg("admins:admin")
    # Defensive: an IdP could send non-string entries; they must not crash.
    assert oidc.map_groups_to_role([None, 123, "admins"], cfg) is Role.admin


# ── oidc_enabled / init_oidc ──────────────────────────────────────────────────

def _app(**cfg) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "t"
    app.config.setdefault("RUCKUS_OIDC_ISSUER", "")
    app.config.setdefault("RUCKUS_OIDC_CLIENT_ID", "")
    app.config.setdefault("RUCKUS_OIDC_CLIENT_SECRET", "")
    app.config.setdefault("RUCKUS_OIDC_SCOPES", "openid email profile")
    app.config.setdefault("RUCKUS_OIDC_GROUPS_CLAIM", "groups")
    app.config.update(cfg)
    return app


def test_oidc_disabled_when_unconfigured():
    app = _app()
    oidc.init_oidc(app)
    assert oidc.oidc_enabled(app) is False


def test_oidc_disabled_when_partial_config():
    # Issuer set but no client id/secret -> stays disabled (never half-enabled).
    app = _app(RUCKUS_OIDC_ISSUER="https://idp.local")
    oidc.init_oidc(app)
    assert oidc.oidc_enabled(app) is False

    app2 = _app(RUCKUS_OIDC_ISSUER="https://idp.local",
                RUCKUS_OIDC_CLIENT_ID="ruckus")
    oidc.init_oidc(app2)
    assert oidc.oidc_enabled(app2) is False


def test_oidc_enabled_when_fully_configured():
    app = _app(
        RUCKUS_OIDC_ISSUER="https://idp.local",
        RUCKUS_OIDC_CLIENT_ID="ruckus",
        RUCKUS_OIDC_CLIENT_SECRET="s3cret",
    )
    oidc.init_oidc(app)
    assert oidc.oidc_enabled(app) is True
    # The named client is registered and retrievable.
    assert oidc.get_oidc_client(app) is not None


def test_init_oidc_unconfigured_registers_no_client():
    app = _app()
    oidc.init_oidc(app)
    assert oidc.get_oidc_client(app) is None


# ── extract_claims ────────────────────────────────────────────────────────────

def test_extract_claims_reads_sub_email_name_groups():
    app = _app(RUCKUS_OIDC_GROUPS_CLAIM="groups")
    claims = {
        "sub": "abc-123",
        "email": "u@corp.local",
        "name": "Full Name",
        "groups": ["admins", "noc"],
    }
    sub, email, name, groups = oidc.extract_claims(app, claims)
    assert sub == "abc-123"
    assert email == "u@corp.local"
    assert name == "Full Name"
    assert groups == ["admins", "noc"]


def test_extract_claims_custom_groups_claim():
    app = _app(RUCKUS_OIDC_GROUPS_CLAIM="roles")
    claims = {"sub": "s", "email": "e@x.y", "roles": ["admins"]}
    sub, email, name, groups = oidc.extract_claims(app, claims)
    assert groups == ["admins"]


def test_extract_claims_scalar_group_coerced_to_list():
    app = _app(RUCKUS_OIDC_GROUPS_CLAIM="groups")
    claims = {"sub": "s", "email": "e@x.y", "groups": "admins"}
    _, _, _, groups = oidc.extract_claims(app, claims)
    assert groups == ["admins"]


def test_extract_claims_missing_groups_is_empty():
    app = _app()
    claims = {"sub": "s", "email": "e@x.y"}
    _, _, _, groups = oidc.extract_claims(app, claims)
    assert groups == []


def test_extract_claims_display_name_falls_back():
    app = _app()
    # No "name" -> fall back through preferred_username -> email local part.
    c1 = {"sub": "s", "email": "e@x.y", "preferred_username": "puser"}
    assert oidc.extract_claims(app, c1)[2] == "puser"
    c2 = {"sub": "s", "email": "local@x.y"}
    assert oidc.extract_claims(app, c2)[2] == "local"


def test_extract_claims_missing_sub_raises():
    app = _app()
    with pytest.raises(ValueError):
        oidc.extract_claims(app, {"email": "e@x.y"})
