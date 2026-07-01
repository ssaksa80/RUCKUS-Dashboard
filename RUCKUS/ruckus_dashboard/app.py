"""Flask app factory. Routes registered by their own files."""
from __future__ import annotations
import logging
import os
import secrets
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from flask import Flask, current_app, g, jsonify, redirect, request, session

from . import APP_NAME, APP_VERSION
from .config import build_config, load_secret_key
from .logging_setup import configure_logging
from .auth.session_store import ConnectionStore
from .auth.secrets import SecretsManager
from .auth.profiles import ProfileStore
from .net.allowlist import HostAllowList
from .infra.cache import ModuleResultCache
from .infra.inflight import InFlightDeduper

LOG = logging.getLogger("ruckus_dashboard")

# Ops probe paths are unauthenticated and must answer even when the app is
# misconfigured (e.g. no secret key), so before_request skips the session-backed
# CSRF token for them — touching the session would 500 without a secret key.
_OPS_PROBE_PATHS = frozenset({"/healthz", "/readyz"})

# Paths the Phase B app-user gate never blocks: the login pages themselves, the
# auth blueprint (login/logout/callback), and the ops probes. Static files and
# any /login/* (OIDC subpaths, PB2) are matched by prefix in the gate.
_AUTH_EXEMPT_PATHS = frozenset({"/login", "/healthz", "/readyz"})


def _is_auth_exempt(path: str, static_prefix: str) -> bool:
    """True if the app-user gate must let ``path`` through unauthenticated.

    Exempt: the login pages (/login and /login/* OIDC subpaths, PB2), the auth
    blueprint (/auth/*), the ops probes, and static assets.
    """
    if path in _AUTH_EXEMPT_PATHS:
        return True
    if path == "/login" or path.startswith("/login/"):
        return True
    if path.startswith("/auth/"):
        return True
    if static_prefix and path.startswith(static_prefix):
        return True
    return False


def _load_identity() -> None:
    """Populate g.user / g.tenant_id / g.role from session['user_id'].

    Sets everything to None when no app user is logged in. Kept lightweight — it
    reads the id from the signed session, then loads the row to confirm the user
    still exists and is active (a deactivated user is treated as logged out).
    """
    g.user = None
    g.user_id = None
    g.tenant_id = None
    g.role = None
    uid = session.get("user_id")
    if uid is None:
        return
    from .db import session_scope
    from .db.models import User
    try:
        with session_scope(current_app) as s:
            user = s.query(User).filter(User.id == uid).one_or_none()
            if user is not None and user.is_active:
                g.user = {"id": user.id, "email": user.email, "role": user.role,
                          "tenant_id": user.tenant_id}
                g.user_id = user.id
                g.tenant_id = user.tenant_id
                g.role = user.role
    except Exception:  # noqa: BLE001 - a DB hiccup must not 500 every request
        LOG.warning("identity load failed for user_id=%s", uid, exc_info=True)


def _instance_writable(instance_path: str) -> bool:
    """True if we can create + remove a file in the instance dir.

    Readiness depends on the instance dir being writable (secret_key, certs,
    profiles, notify state all live there). Module-level so tests can patch it.
    """
    p = Path(instance_path)
    p.mkdir(parents=True, exist_ok=True)
    probe = p / f".readyz-{uuid.uuid4().hex}"
    probe.write_text("ok", encoding="utf-8")
    os.remove(probe)
    return True


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True,
                template_folder="templates", static_folder="static")
    app.config.from_mapping(build_config(app.instance_path))
    if test_config is not None:
        # Test defaults (preserve the pre-PhaseB suite): unless a test opts in,
        # the app-user gate is OFF and the identity DB is in-memory so no real
        # ruckus.db is written and no real state is polluted. New PB1 tests set
        # these explicitly to exercise the gate. copy() so we don't mutate the
        # caller's dict.
        merged = dict(test_config)
        merged.setdefault("RUCKUS_AUTH_REQUIRED", False)
        merged.setdefault("RUCKUS_DATABASE_URL", "sqlite:///:memory:")
        app.config.update(merged)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = load_secret_key(app.instance_path)

    configure_logging(app.instance_path, bool(app.config.get("RUCKUS_SHOW_DEBUG")))

    # Capability discovery populates this per-connection on connect; modules
    # consult it via CapabilityGate keyed by the session's connection ids. A
    # registry (not a process-global set) so concurrent operators on different
    # controllers don't leak ops into — or wipe gating from — each other.
    # Created before the connection store so TTL-eviction can clear the matching
    # capability entry (on_evict) instead of leaking it.
    from .infra.capability_registry import CapabilityRegistry
    app.capability_registry = CapabilityRegistry()
    app.connection_store = ConnectionStore(
        ttl_seconds=app.config["CREDENTIAL_TTL_SECONDS"],
        on_evict=app.capability_registry.clear,
    )
    app.secrets_manager = SecretsManager(app.instance_path)
    app.profile_store = ProfileStore(app.instance_path, app.secrets_manager)

    # ── Phase B (PB1): identity persistence + break-glass admin ──────────────
    # DB engine/scoped-session onto the app, schema via create_all, then seed a
    # default tenant + break-glass admin. In-memory URL under test (see above).
    from .db import init_db
    from .routes.auth import seed_identity
    from .auth.ratelimit import LoginRateLimiter
    init_db(app)
    seed_identity(app)
    app.login_rate_limiter = LoginRateLimiter()
    app.config["RUCKUS_HOST_ALLOWLIST"] = HostAllowList(app.config.get("RUCKUS_ALLOWED_HOSTS", ""))
    app.module_cache = ModuleResultCache()
    app.warmup_scheduler = None

    from .notify.scheduler import NotifyScheduler
    app.notify_scheduler = NotifyScheduler(app.instance_path,
                                           dict(app.config),
                                           app.secrets_manager)
    app.notify_scheduler.start()
    app.inflight = InFlightDeduper()

    from .routes.modules import bp as modules_bp
    app.register_blueprint(modules_bp)

    from .routes.pages import bp as pages_bp
    app.register_blueprint(pages_bp)

    from .routes.connect import bp as connect_bp
    app.register_blueprint(connect_bp)

    from .routes.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from .routes.warmup import bp as warmup_bp
    app.register_blueprint(warmup_bp)
    from .routes.topology_layout import bp as topology_layout_bp
    app.register_blueprint(topology_layout_bp)
    from .routes.notifications import bp as notifications_bp
    app.register_blueprint(notifications_bp)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        response.headers.setdefault("Cache-Control", "no-store")
        # 'unsafe-inline' covers style *attributes* only (legend swatches,
        # warmup bar widths); scripts are restricted to same-origin files.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'",
        )
        return response

    static_prefix = f"{app.static_url_path.rstrip('/')}/" if app.static_url_path else ""

    @app.before_request
    def before_request():
        g.request_id = uuid.uuid4().hex[:8]
        # Ops probes must not depend on the session (no secret key ⇒ 500); they
        # are unauthenticated liveness/readiness checks with no CSRF surface.
        if request.path in _OPS_PROBE_PATHS:
            return
        session.setdefault("csrf_token", secrets.token_urlsafe(32))

        # Phase B Layer 1: load the app-user identity (None if not logged in).
        _load_identity()

        # App-user gate (default ON in prod, OFF under test). Denies
        # unauthenticated requests to non-exempt paths. Runs IN FRONT OF the
        # existing controller session["auth"] gate, which is left intact
        # beneath it (enforced per-route as before).
        if app.config.get("RUCKUS_AUTH_REQUIRED") and g.user is None:
            if not _is_auth_exempt(request.path, static_prefix):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Authentication required."}), 401
                nxt = urlencode({"next": request.full_path})
                return redirect(f"/login?{nxt}")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return exc
        ref = getattr(g, "request_id", "-")
        LOG.error(f"unhandled error: {exc}", extra={"request_id": ref}, exc_info=True)
        return jsonify({"error": "Internal server error.", "reference": ref}), 500

    @app.get("/healthz")
    def healthz():
        # Liveness: the process is up and answering. Always 200 — a live-but-
        # not-ready app must not be killed by an orchestrator's liveness probe.
        return jsonify({"ok": True, "app": APP_NAME, "version": APP_VERSION})

    @app.get("/readyz")
    def readyz():
        # Readiness: can we actually serve? Needs a session-signing key AND a
        # writable instance dir (secrets/certs/profiles/notify state live there).
        # 503 tells a load balancer to stop routing traffic until we recover.
        if not app.config.get("SECRET_KEY"):
            return jsonify({"ready": False, "reason": "SECRET_KEY not set"}), 503
        try:
            _instance_writable(app.instance_path)
        except OSError as exc:
            return jsonify(
                {"ready": False, "reason": f"instance dir not writable: {exc}"}
            ), 503
        return jsonify({"ready": True, "app": APP_NAME, "version": APP_VERSION}), 200

    return app
