"""Flask app factory. Routes registered by their own files."""
from __future__ import annotations
import logging
import secrets
import uuid
from typing import Any

from flask import Flask, g, jsonify, session

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


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True,
                template_folder="templates", static_folder="static")
    app.config.from_mapping(build_config(app.instance_path))
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = load_secret_key(app.instance_path)

    configure_logging(app.instance_path, bool(app.config.get("RUCKUS_SHOW_DEBUG")))

    app.connection_store = ConnectionStore(ttl_seconds=app.config["CREDENTIAL_TTL_SECONDS"])
    app.secrets_manager = SecretsManager(app.instance_path)
    app.profile_store = ProfileStore(app.instance_path, app.secrets_manager)
    app.config["RUCKUS_HOST_ALLOWLIST"] = HostAllowList(app.config.get("RUCKUS_ALLOWED_HOSTS", ""))
    app.module_cache = ModuleResultCache()
    app.inflight = InFlightDeduper()
    # Capability discovery populates this set on connect; modules consult it
    # via CapabilityGate. Initialised empty so unauthenticated requests don't
    # AttributeError before any controller is reachable.
    app.available_ops = set()

    from .routes.modules import bp as modules_bp
    app.register_blueprint(modules_bp)

    from .routes.pages import bp as pages_bp
    app.register_blueprint(pages_bp)

    from .routes.connect import bp as connect_bp
    app.register_blueprint(connect_bp)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.before_request
    def before_request() -> None:
        g.request_id = uuid.uuid4().hex[:8]
        session.setdefault("csrf_token", secrets.token_urlsafe(32))

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
        return jsonify({"ok": True, "app": APP_NAME, "version": APP_VERSION})

    return app
