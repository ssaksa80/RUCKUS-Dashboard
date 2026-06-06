"""POST /connect + POST /logout.

Ported from the monolith ``RUCKUS/ruckus_dashboard.py`` (connect ~3000-3052,
logout ~3054-3065). Notable shape changes:

* ``available_ops`` is wired here: on a successful SmartZone connect we run
  ``capabilities.discover_capabilities`` and union its ``available_ops`` set
  into ``current_app.available_ops`` so module routes can capability-gate.
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
    _refresh_available_ops(connection)

    from ..infra.warmup import WarmupScheduler
    from ..modules import MODULES

    if getattr(current_app, "warmup_scheduler", None) is not None:
        current_app.warmup_scheduler.cancel()

    scheduler = WarmupScheduler(
        connection=connection,
        config=dict(current_app.config),
        modules=dict(MODULES),
        available_ops=set(current_app.available_ops),
        max_workers=int(current_app.config.get("RUCKUS_WARMUP_WORKERS", 4)),
        timeout=float(current_app.config.get("RUCKUS_WARMUP_TIMEOUT", 30.0)),
    )
    current_app.warmup_scheduler = scheduler
    scheduler.run_in_thread()

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

    if getattr(current_app, "warmup_scheduler", None) is not None:
        current_app.warmup_scheduler.cancel()
        current_app.warmup_scheduler = None

    csrf_token = session.get("csrf_token", secrets.token_urlsafe(32))
    session.clear()
    session["csrf_token"] = csrf_token
    current_app.available_ops = set()
    return redirect(url_for("pages.index"))


def _refresh_available_ops(connection) -> None:
    """Merge the new connection's OpenAPI ops into ``current_app.available_ops``.

    RUCKUS One has no public OpenAPI surface, so we skip discovery there and
    leave that connection's contribution empty — module specs gated on
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
    if not hasattr(current_app, "available_ops") or current_app.available_ops is None:
        current_app.available_ops = set()
    current_app.available_ops = set(current_app.available_ops) | set(ops)
