"""POST /connect + POST /logout.

Ported from the monolith ``RUCKUS/ruckus_dashboard.py`` (connect ~3000-3052,
logout ~3054-3065). Notable shape changes:

* Capabilities are wired here: on a successful SmartZone connect we run
  ``capabilities.discover_capabilities`` and store its ``available_ops`` set
  in ``current_app.capability_registry`` keyed by the new connection id, so
  module routes can capability-gate per session (not via a shared global).
  Discovery failures (timeouts, 404s) flash a warning but don't block login.
* No profile-save / multi-controller "add mode" yet — those are out of scope
  for the foundation login flow. The monolith semantics will be revisited
  when profile UI lands.
"""
from __future__ import annotations

import logging
import secrets

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    request,
    session,
    url_for,
)

from ..auth.csrf import validate_csrf
from ..clients import authenticate_connection
from ..clients.base import RuckusClientError
from ..clients.smartzone import disconnect_smartzone

LOG = logging.getLogger("ruckus_dashboard.connect")

bp = Blueprint("connect", __name__)


@bp.post("/connect")
def connect():
    validate_csrf()
    form = request.form.to_dict()

    try:
        connection = authenticate_connection(form, current_app.config)
    except RuckusClientError as exc:
        flash(exc.message, "error")
        if current_app.config.get("RUCKUS_SHOW_DEBUG") and exc.debug:
            flash(str(exc.debug), "debug")
        return redirect(url_for("pages.index"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("pages.index"))

    new_id = current_app.connection_store.put(connection)

    csrf_token = session.get("csrf_token", secrets.token_urlsafe(32))
    session.clear()
    session["csrf_token"] = csrf_token
    session["connection_ids"] = [new_id]
    session["auth"] = True
    session.permanent = True

    # Capability discovery (SmartZone only). Failures must not block login —
    # the dashboard still works with an empty ops set, modules just render
    # the disabled envelope until a controller surfaces the OpenAPI doc.
    _refresh_available_ops(connection, new_id)

    from ..infra.warmup import WarmupScheduler
    from ..modules import MODULES

    if getattr(current_app, "warmup_scheduler", None) is not None:
        current_app.warmup_scheduler.cancel()

    scheduler = WarmupScheduler(
        connection=connection,
        config=dict(current_app.config),
        modules=dict(MODULES),
        available_ops=current_app.capability_registry.get_for([new_id]),
        max_workers=int(current_app.config.get("RUCKUS_WARMUP_WORKERS", 4)),
        timeout=float(current_app.config.get("RUCKUS_WARMUP_TIMEOUT", 30.0)),
    )
    current_app.warmup_scheduler = scheduler
    scheduler.run_in_thread()

    if getattr(current_app, "notify_scheduler", None) is not None:
        current_app.notify_scheduler.set_connection(connection)
        # The daily scheduled report runs without a request/session, so seed its
        # ops here (mirrors the per-request capability gate) or gated modules
        # render disabled in the unattended run.
        current_app.notify_scheduler.set_available_ops(
            current_app.capability_registry.get_for([new_id]))

    return redirect(url_for("pages.index"))


@bp.post("/logout")
def logout():
    validate_csrf()
    for cid in list(session.get("connection_ids", [])):
        conn = current_app.connection_store.get(cid)
        if conn is not None:
            try:
                disconnect_smartzone(conn, current_app.config)
            except Exception:  # noqa: BLE001 — best-effort logout
                LOG.warning("smartzone logout cleanup failed", exc_info=True)
        current_app.connection_store.remove(cid)
        # Drop only this connection's capabilities; a concurrent operator on a
        # different controller keeps their own gating intact.
        current_app.capability_registry.clear(cid)

    if getattr(current_app, "warmup_scheduler", None) is not None:
        current_app.warmup_scheduler.cancel()
        current_app.warmup_scheduler = None
    if getattr(current_app, "notify_scheduler", None) is not None:
        current_app.notify_scheduler.clear_connection()

    csrf_token = session.get("csrf_token", secrets.token_urlsafe(32))
    session.clear()
    session["csrf_token"] = csrf_token
    return redirect(url_for("pages.index"))


def _refresh_available_ops(connection, connection_id: str) -> None:
    """Store the new connection's OpenAPI ops in the capability registry.

    Keyed by ``connection_id`` so each session sees only its own controllers'
    capabilities. RUCKUS One has no public OpenAPI surface, so we skip discovery
    there and leave that connection's contribution empty — module specs gated on
    SmartZone capabilities will render the disabled envelope when only
    RUCKUS One is connected, which is correct.
    """
    if connection.platform != "smartzone":
        return
    from ..clients.capabilities import discover_capabilities

    try:
        caps = discover_capabilities(connection, dict(current_app.config))
    except Exception as exc:  # noqa: BLE001 — discovery is best-effort
        LOG.warning("capability discovery failed: %s", exc, exc_info=True)
        flash(
            "Connected, but controller capability discovery failed. "
            "Some dashboards may show as unavailable until reconnect.",
            "warning",
        )
        return
    ops = caps.get("available_ops") or set()
    current_app.capability_registry.set_for(connection_id, set(ops))
