"""OIDC SSO client for the Phase B app-user layer (PB2).

One provider — ``"oidc"`` — registered with Authlib from env/config against an
on-prem, air-gapped IdP, **alongside** the local break-glass login (PB1). OIDC
is enabled only when the issuer, client id and client secret are all set; a
partial config leaves it disabled (local-only) — it never half-enables.

Authlib owns the security-sensitive parts of the flow:

* ``begin_login`` → ``client.authorize_redirect(redirect_uri, nonce=…)`` builds
  the authorize URL and stores the CSRF ``state`` + ``nonce`` in the session.
* ``complete_login`` → ``client.authorize_access_token()`` validates ``state``,
  exchanges the code for tokens, and validates the ``id_token``
  (issuer / audience / signature / expiry / nonce), returning the verified
  claims. We do **not** hand-roll any JWT checks.

The trust anchor is the operator-configured issuer; Authlib fetches its
discovery document, JWKS, token and userinfo endpoints from it (expected on an
air-gapped on-prem deployment).
"""
from __future__ import annotations

import logging
import secrets
from typing import Any, Optional

from authlib.integrations.flask_client import OAuth

from ..db.models import Role

LOG = logging.getLogger("ruckus_dashboard.auth.oidc")

# The single provider name we register with Authlib.
PROVIDER_NAME = "oidc"

# Session key for the id_token nonce (Authlib stores state itself; we also keep
# the nonce so complete_login can hand it back for id_token validation).
_NONCE_SESSION_KEY = "oidc_nonce"


# ── enable-gate + client access ───────────────────────────────────────────────

def _required_config(app) -> tuple[str, str, str]:
    return (
        (app.config.get("RUCKUS_OIDC_ISSUER") or "").strip(),
        (app.config.get("RUCKUS_OIDC_CLIENT_ID") or "").strip(),
        (app.config.get("RUCKUS_OIDC_CLIENT_SECRET") or "").strip(),
    )


def oidc_enabled(app) -> bool:
    """True iff issuer + client id + secret are all configured.

    A partial configuration returns False — the app stays local-only rather
    than exposing a broken SSO button (never half-enabled).
    """
    issuer, client_id, client_secret = _required_config(app)
    return bool(issuer and client_id and client_secret)


def init_oidc(app) -> None:
    """Attach an Authlib :class:`OAuth` to ``app`` and register the provider.

    No-op registration when OIDC is not fully configured (leaves
    ``get_oidc_client`` returning ``None``). Idempotent per app. Always safe to
    call from ``create_app`` — an unconfigured/air-gapped install simply gets a
    local-only app.
    """
    oauth = OAuth(app)
    app.oidc_oauth = oauth

    if not oidc_enabled(app):
        LOG.info("OIDC disabled (issuer/client not fully configured); local-only")
        return

    issuer, client_id, client_secret = _required_config(app)
    scopes = (app.config.get("RUCKUS_OIDC_SCOPES") or "openid email profile").strip()
    # Authlib derives every endpoint (authorize/token/jwks/userinfo) from the
    # issuer's discovery document; nonce/state/iss/aud/signature validation is
    # handled internally on the callback.
    oauth.register(
        name=PROVIDER_NAME,
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=f"{issuer.rstrip('/')}/.well-known/openid-configuration",
        client_kwargs={"scope": scopes},
    )
    LOG.info("OIDC enabled (issuer=%s)", issuer)


def get_oidc_client(app):
    """Return the registered Authlib client for the provider, or ``None``."""
    oauth = getattr(app, "oidc_oauth", None)
    if oauth is None:
        return None
    return getattr(oauth, PROVIDER_NAME, None)


# ── authorize / callback helpers ──────────────────────────────────────────────

def begin_login(app, redirect_uri: str):
    """Build the IdP authorize redirect, storing state + nonce in the session.

    Authlib stashes the ``state`` (CSRF) in the session and includes the nonce
    in the id_token request; we also keep the nonce under our own key as a
    belt-and-braces record. Returns a Flask redirect ``Response``.
    """
    client = get_oidc_client(app)
    if client is None:  # pragma: no cover - callers gate on oidc_enabled first
        raise RuntimeError("OIDC is not enabled")
    from flask import session

    nonce = secrets.token_urlsafe(24)
    session[_NONCE_SESSION_KEY] = nonce
    return client.authorize_redirect(redirect_uri, nonce=nonce)


def complete_login(app) -> dict[str, Any]:
    """Exchange the callback code and return **validated** id_token claims.

    Delegates state/nonce/iss/aud/signature/expiry validation entirely to
    Authlib (``authorize_access_token`` → internal ``parse_id_token``). If the
    id_token claims lack a groups entry (some IdPs only surface groups at the
    userinfo endpoint), we additionally fetch userinfo and merge it in. Raises
    on any validation failure — the caller turns that into a generic login
    failure without leaking token/exception detail.
    """
    client = get_oidc_client(app)
    if client is None:  # pragma: no cover - callers gate on oidc_enabled first
        raise RuntimeError("OIDC is not enabled")
    from flask import session

    token = client.authorize_access_token()  # validates state + id_token
    claims: dict[str, Any] = dict(token.get("userinfo") or {})

    groups_claim = (app.config.get("RUCKUS_OIDC_GROUPS_CLAIM") or "groups").strip()
    # Supplement from the userinfo endpoint when the id_token omitted groups or
    # email (common with minimal id_tokens). Best-effort: a userinfo hiccup must
    # not sink an otherwise-valid login.
    if groups_claim not in claims or "email" not in claims:
        try:
            userinfo = client.userinfo(token=token)
            if userinfo:
                for key, value in dict(userinfo).items():
                    claims.setdefault(key, value)
        except Exception:  # noqa: BLE001 - userinfo is a best-effort supplement
            LOG.debug("userinfo supplement failed; using id_token claims only")

    session.pop(_NONCE_SESSION_KEY, None)
    return claims


def extract_claims(app, claims: dict[str, Any]) -> tuple[str, str, Optional[str], list]:
    """Pull ``(subject, email, display_name, groups)`` from validated claims.

    ``subject`` (``sub``) is required — its absence means the id_token was not a
    proper OIDC token; raise ``ValueError``. ``display_name`` falls back through
    ``name`` → ``preferred_username`` → the email local-part. ``groups`` comes
    from the configured claim (default ``groups``), coerced to a list; a scalar
    becomes a one-element list, a missing claim becomes ``[]``.
    """
    sub = claims.get("sub")
    if not sub:
        raise ValueError("id_token missing required 'sub' claim")

    email = (claims.get("email") or "").strip()

    groups_claim = (app.config.get("RUCKUS_OIDC_GROUPS_CLAIM") or "groups").strip()
    raw_groups = claims.get(groups_claim)
    if raw_groups is None:
        groups: list = []
    elif isinstance(raw_groups, (list, tuple, set)):
        groups = list(raw_groups)
    else:
        groups = [raw_groups]

    display_name = claims.get("name") or claims.get("preferred_username")
    if not display_name:
        display_name = email.split("@", 1)[0] if email else None

    return str(sub), email, display_name, groups


# ── group → role mapping ──────────────────────────────────────────────────────

def parse_group_roles(config_value: str) -> dict[str, Role]:
    """Parse ``"grp:role,grp2:role2"`` → ``{group_name: Role}``.

    Malformed entries (missing ``:``, blank group, unknown role) are skipped
    with a debug log rather than raising — a typo in the operator's map must not
    break every SSO login. Group names are matched case-sensitively as the IdP
    sends them; role names are the ``Role`` enum names.
    """
    mapping: dict[str, Role] = {}
    for chunk in (config_value or "").split(","):
        entry = chunk.strip()
        if not entry or ":" not in entry:
            if entry:
                LOG.debug("ignoring malformed OIDC group-role entry: %r", entry)
            continue
        group, _, role_name = entry.partition(":")
        group = group.strip()
        role_name = role_name.strip()
        if not group or not role_name:
            LOG.debug("ignoring incomplete OIDC group-role entry: %r", entry)
            continue
        try:
            mapping[group] = Role.coerce(role_name)
        except (KeyError, ValueError):
            LOG.debug("ignoring unknown role in OIDC group-role map: %r", role_name)
    return mapping


def map_groups_to_role(groups, config: dict) -> Role:
    """Resolve the highest role the user's ``groups`` grant (default viewer).

    ``config`` is the app config (or any mapping) carrying
    ``RUCKUS_OIDC_GROUP_ROLES``. Users in no mapped group — or with no groups —
    get :attr:`Role.viewer`. When a user is in several mapped groups the highest
    role wins (viewer < operator < admin).
    """
    mapping = parse_group_roles(config.get("RUCKUS_OIDC_GROUP_ROLES", "") or "")
    best = Role.viewer
    for grp in groups or []:
        if not isinstance(grp, str):
            continue
        role = mapping.get(grp)
        if role is not None and role > best:
            best = role
    return best
