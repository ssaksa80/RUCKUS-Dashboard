"""Config builder + env parsers. Lifted from the monolith; new flags added."""
from __future__ import annotations
import os
import secrets
from datetime import timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DEFAULT_DASHBOARD_PORT = 8444
DEFAULT_SMARTZONE_API_PORT = 8443


def build_config(instance_path: str) -> dict:
    return {
        # ─── ports + bind ────────────────────────────────────────
        "APP_HOST": os.getenv("RUCKUS_DASHBOARD_HOST", "127.0.0.1"),
        "APP_PORT": _int_env("RUCKUS_DASHBOARD_PORT", DEFAULT_DASHBOARD_PORT),
        "APP_AUTO_PORT": _bool_env("RUCKUS_AUTO_PORT", True),
        "APP_PORT_SCAN_LIMIT": _int_env("RUCKUS_PORT_SCAN_LIMIT", 50),
        "APP_OPEN_BROWSER": _bool_env("RUCKUS_OPEN_BROWSER", True),
        # ─── upstream API ────────────────────────────────────────
        "RUCKUS_SMARTZONE_PORT": _int_env("RUCKUS_SMARTZONE_PORT", DEFAULT_SMARTZONE_API_PORT),
        "RUCKUS_PAGE_LIMIT": _int_env("RUCKUS_PAGE_LIMIT", 500),
        "RUCKUS_TIMEOUT_SECONDS": _float_env("RUCKUS_TIMEOUT_SECONDS", 20.0),
        "RUCKUS_DEBUG_BYTES": _int_env("RUCKUS_DEBUG_BYTES", 2000),
        "RUCKUS_SHOW_DEBUG": _bool_env("RUCKUS_SHOW_DEBUG", False),
        "RUCKUS_VERIFY_TLS": _tls_verify_env("RUCKUS_VERIFY_TLS", True),
        "RUCKUS_FETCH_AP_DETAILS": _bool_env("RUCKUS_FETCH_AP_DETAILS", False),
        "RUCKUS_MAX_DETAIL_REQUESTS": _int_env("RUCKUS_MAX_DETAIL_REQUESTS", 300),
        "RUCKUS_CAPABILITY_DISCOVERY": _bool_env("RUCKUS_CAPABILITY_DISCOVERY", True),
        "RUCKUS_OPERATIONAL_DATA": _bool_env("RUCKUS_OPERATIONAL_DATA", True),
        "RUCKUS_FETCH_SWITCH_HEALTH": _bool_env("RUCKUS_FETCH_SWITCH_HEALTH", True),
        # ─── security ────────────────────────────────────────────
        "RUCKUS_SECURITY_LOOKUPS": _bool_env("RUCKUS_SECURITY_LOOKUPS", True),
        "RUCKUS_MAX_SECURITY_LOOKUPS": _int_env("RUCKUS_MAX_SECURITY_LOOKUPS", 12),
        "RUCKUS_NVD_RESULTS": _int_env("RUCKUS_NVD_RESULTS", 5),
        "RUCKUS_SECURITY_CACHE_SECONDS": _int_env("RUCKUS_SECURITY_CACHE_SECONDS", 21600),
        "RUCKUS_ALLOWED_HOSTS": os.getenv("RUCKUS_ALLOWED_HOSTS", ""),
        # ─── session ─────────────────────────────────────────────
        "CREDENTIAL_TTL_SECONDS": _int_env("RUCKUS_CREDENTIAL_TTL_SECONDS", 43200),
        "PERMANENT_SESSION_LIFETIME": timedelta(seconds=_int_env("RUCKUS_CREDENTIAL_TTL_SECONDS", 43200)),
        "SECRET_KEY": os.getenv("FLASK_SECRET_KEY"),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SECURE": True,
        "SESSION_COOKIE_SAMESITE": "Strict",
        # ─── Phase B identity/RBAC (PB1) ─────────────────────────
        # Empty -> resolved to sqlite:///<instance>/ruckus.db by db.init_db.
        "RUCKUS_DATABASE_URL": os.getenv("RUCKUS_DATABASE_URL", ""),
        # Break-glass admin seed password (first boot only). If empty, a random
        # one is generated and logged once by bootstrap_admin.
        "RUCKUS_ADMIN_PASSWORD": os.getenv("RUCKUS_ADMIN_PASSWORD", ""),
        # App-user login gate. Default ON (enforce app-login). A single-operator
        # site can set RUCKUS_AUTH_REQUIRED=0 to preserve pre-PhaseB behavior;
        # the test app factory also defaults it OFF (see create_app).
        "RUCKUS_AUTH_REQUIRED": _bool_env("RUCKUS_AUTH_REQUIRED", True),
        # ─── Phase B OIDC SSO (PB2) ──────────────────────────────
        # OIDC against an on-prem/air-gapped IdP, alongside the local break-glass
        # login. OIDC is enabled ONLY when issuer + client id + secret are all
        # set (see auth.oidc.oidc_enabled); otherwise the app stays local-only —
        # it never half-enables. ISSUER is the base URL; Authlib discovers via
        # ``{issuer}/.well-known/openid-configuration``.
        "RUCKUS_OIDC_ISSUER": os.getenv("RUCKUS_OIDC_ISSUER", ""),
        "RUCKUS_OIDC_CLIENT_ID": os.getenv("RUCKUS_OIDC_CLIENT_ID", ""),
        "RUCKUS_OIDC_CLIENT_SECRET": os.getenv("RUCKUS_OIDC_CLIENT_SECRET", ""),
        "RUCKUS_OIDC_SCOPES": os.getenv("RUCKUS_OIDC_SCOPES", "openid email profile"),
        # Which id_token/userinfo claim carries the user's groups.
        "RUCKUS_OIDC_GROUPS_CLAIM": os.getenv("RUCKUS_OIDC_GROUPS_CLAIM", "groups"),
        # Group→role map, e.g. "admins:admin,noc:operator". Unmapped / no-group
        # users default to viewer (see auth.oidc.map_groups_to_role).
        "RUCKUS_OIDC_GROUP_ROLES": os.getenv("RUCKUS_OIDC_GROUP_ROLES", ""),
        # ─── NEW UI shell ────────────────────────────────────────
        "RUCKUS_ENABLE_NEW_UI": _bool_env("RUCKUS_ENABLE_NEW_UI", False),
        # Front-end refresh (design-token/theme layer + modernized Overview).
        # Purely presentational and flag-gated: OFF (default) renders exactly
        # as today; ON adds body[data-ui="modern"] so the modern skin activates.
        "RUCKUS_MODERN_UI": _bool_env("RUCKUS_MODERN_UI", False),
        "RUCKUS_MAX_INFLIGHT_PER_MODULE": _int_env("RUCKUS_MAX_INFLIGHT_PER_MODULE", 1),
        "RUCKUS_WARMUP_WORKERS": _int_env("RUCKUS_WARMUP_WORKERS", 4),
        "RUCKUS_WARMUP_TIMEOUT": _float_env("RUCKUS_WARMUP_TIMEOUT", 30.0),
        # ─── production WSGI (opt-in waitress behind a TLS proxy) ─
        "RUCKUS_WSGI_THREADS": _int_env("RUCKUS_WSGI_THREADS", 4),
    }


def load_secret_key(instance_path: str) -> str:
    secret_path = Path(instance_path) / "secret_key"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(48)
    secret_path.write_text(secret, encoding="utf-8")
    try:
        secret_path.chmod(0o600)
    except OSError:
        pass
    return secret


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _tls_verify_env(name: str, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return value
