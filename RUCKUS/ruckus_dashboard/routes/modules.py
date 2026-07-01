"""Module list + per-module data endpoints."""
from __future__ import annotations
import logging
from flask import Blueprint, abort, current_app, jsonify, request, session

from ..modules import MODULES, all_modules
from ..modules._base import FetcherContext
from ..infra.envelope import ControllerError, build_envelope
from ..infra.capability_gate import CapabilityGate
from ..clients.base import RuckusClientError
import ruckus_dashboard.modules._registry  # noqa: F401  side-effect: registers stubs

LOG = logging.getLogger("ruckus_dashboard")

bp = Blueprint("modules", __name__)


def _default_merge(results: list[dict]) -> dict:
    """Concatenate items across controllers when a module declares no merge()."""
    items: list = []
    raw = 0
    for d in results:
        items.extend(d.get("items", []))
        raw += int(d.get("raw_count", 0) or 0)
    return {"items": items, "raw_count": raw}


def _upstream_message(exc: RuckusClientError) -> str:
    """Error text for the UI. Appends the controller's raw response body only
    when debug output is enabled, so 4xx validation details reach the operator
    without leaking internals by default."""
    message = exc.message
    if current_app.config.get("RUCKUS_SHOW_DEBUG") and isinstance(exc.debug, dict):
        raw = exc.debug.get("raw")
        if raw:
            message = f"{message} :: {raw}"
    return message


def _log_upstream(slug: str, label: str, exc: RuckusClientError) -> None:
    """Always log the controller's raw error body server-side (truncated), so
    the failing payload can be diagnosed even when UI debug is off."""
    raw = ""
    if isinstance(exc.debug, dict):
        raw = str(exc.debug.get("raw", ""))[:500]
    LOG.warning("module '%s' upstream error on %s: HTTP %s %s",
                slug, label, exc.status_code, raw)


@bp.get("/api/modules")
def list_modules():
    return jsonify({
        "modules": [
            {"slug": m.slug, "title": m.title, "group": m.group, "icon": m.icon,
             "poll_seconds": m.poll_seconds, "requires_platforms": list(m.requires_platforms),
             "requires_capabilities": [list(c) for c in m.requires_capabilities],
             "supports_views": list(m.supports_views),
             "columns": [{"label": c.label, "key": c.key, "kind": c.kind} for c in m.columns],
             "filters": [{"key": f.key, "label": f.label, "kind": f.kind,
                          "server_filter": f.server_filter} for f in m.resolved_filters],
             "drill_tabs": [{"slug": t.slug, "title": t.title} for t in m.drill_tabs],
             "has_drill": m.drill_fetcher is not None}
            for m in all_modules()
        ]
    })


@bp.get("/api/modules/<slug>")
def module_data(slug: str):
    spec = MODULES.get(slug)
    if spec is None:
        abort(404, description=f"unknown module: {slug}")
    if not session.get("auth"):
        return jsonify({"error": "Connection expired. Please reconnect.", "reauth": True}), 401

    conn_ids = tuple(session.get("connection_ids", []))
    pairs = [(cid, current_app.connection_store.get(cid)) for cid in conn_ids]
    pairs = [(cid, c) for cid, c in pairs if c is not None]
    if not pairs:
        return jsonify({"error": "Connection expired. Please reconnect.", "reauth": True}), 401

    gate = CapabilityGate(available=current_app.capability_registry.get_for(conn_ids))
    if not gate.satisfied(spec.requires_capabilities):
        env = build_envelope(
            data={"items": [], "disabled": True,
                  "missing_capabilities": gate.missing(spec.requires_capabilities)},
            summary={"count": 0, "disabled": True},
            errors=[],
        )
        return jsonify(env)

    filters = request.args.to_dict()
    results: list[dict] = []
    errors: list[ControllerError] = []
    for _, conn in pairs:
        ctx = FetcherContext(connection=conn, config=dict(current_app.config),
                             filters=filters, capability_gate=gate,
                             connection_label=conn.display_name)
        # A single controller's failure must never 500 the whole module. Collect
        # it as a ControllerError so the page renders partial data + an error pill.
        try:
            results.append(spec.fetcher(ctx))
        except RuckusClientError as exc:
            _log_upstream(slug, conn.display_name, exc)
            errors.append(ControllerError(
                connection=conn.display_name, endpoint=slug,
                message=_upstream_message(exc), status=exc.status_code))
        except Exception as exc:  # noqa: BLE001 — defensive: never 500 the page
            LOG.exception("module '%s' fetcher crashed on %s", slug, conn.display_name)
            errors.append(ControllerError(
                connection=conn.display_name, endpoint=slug,
                message=str(exc), status=502))

    if not results:
        # Every controller failed → error envelope (HTTP 200; UI shows error pill).
        return jsonify(build_envelope(data=None, summary={}, errors=errors))

    merge_fn = spec.merge or _default_merge
    merged = merge_fn(results)
    summary = spec.summary_fn(merged)
    return jsonify(build_envelope(data=merged, summary=summary, errors=errors))


@bp.get("/api/modules/<slug>/<entity_id>")
def module_drill(slug: str, entity_id: str):
    spec = MODULES.get(slug)
    if spec is None:
        abort(404, description=f"unknown module: {slug}")
    if not session.get("auth"):
        return jsonify({"error": "Connection expired. Please reconnect.", "reauth": True}), 401
    if spec.drill_fetcher is None:
        return jsonify({"error": "Module has no drill-in.", "slug": slug}), 404

    conn_ids = tuple(session.get("connection_ids", []))
    pairs = [(cid, current_app.connection_store.get(cid)) for cid in conn_ids]
    pairs = [(cid, c) for cid, c in pairs if c is not None]
    if not pairs:
        return jsonify({"error": "Connection expired.", "reauth": True}), 401

    gate = CapabilityGate(available=current_app.capability_registry.get_for(conn_ids))
    filters = request.args.to_dict()
    _, conn = pairs[0]
    ctx = FetcherContext(connection=conn, config=dict(current_app.config),
                         filters=filters, capability_gate=gate,
                         connection_label=conn.display_name)
    try:
        data = spec.drill_fetcher(ctx, entity_id)
    except RuckusClientError as exc:
        return jsonify({"error": _upstream_message(exc), "slug": slug, "entity_id": entity_id}), exc.status_code
    except Exception as exc:  # noqa: BLE001
        LOG.exception("drill '%s' crashed on %s", slug, entity_id)
        msg = str(exc) if current_app.config.get("RUCKUS_SHOW_DEBUG") else "Drill-in failed."
        return jsonify({"error": msg, "slug": slug, "entity_id": entity_id}), 502
    env = build_envelope(data=data, summary={}, errors=[])
    return jsonify(env)


@bp.get("/api/modules/<slug>/<entity_id>/<tab_slug>")
def module_drill_tab(slug: str, entity_id: str, tab_slug: str):
    spec = MODULES.get(slug)
    if spec is None:
        abort(404, description=f"unknown module: {slug}")
    tab = next((t for t in spec.drill_tabs if t.slug == tab_slug), None)
    if tab is None:
        return jsonify({"error": "unknown tab", "slug": slug, "tab": tab_slug}), 404
    if not session.get("auth"):
        return jsonify({"error": "Connection expired. Please reconnect.", "reauth": True}), 401

    conn_ids = tuple(session.get("connection_ids", []))
    pairs = [(cid, current_app.connection_store.get(cid)) for cid in conn_ids]
    pairs = [(cid, c) for cid, c in pairs if c is not None]
    if not pairs:
        return jsonify({"error": "Connection expired.", "reauth": True}), 401

    gate = CapabilityGate(available=current_app.capability_registry.get_for(conn_ids))
    filters = request.args.to_dict()
    _, conn = pairs[0]
    ctx = FetcherContext(connection=conn, config=dict(current_app.config),
                         filters=filters, capability_gate=gate,
                         connection_label=conn.display_name)
    # A tab-specific fetcher takes precedence; otherwise fall back to the
    # module's full drill payload and let the client pick the relevant section.
    fetcher = tab.fetcher or spec.drill_fetcher
    if fetcher is None:
        return jsonify({"error": "Module has no drill-in.", "slug": slug}), 404
    try:
        data = fetcher(ctx, entity_id)
    except RuckusClientError as exc:
        return jsonify({"error": _upstream_message(exc), "slug": slug,
                        "entity_id": entity_id, "tab": tab_slug}), exc.status_code
    except Exception as exc:  # noqa: BLE001
        LOG.exception("drill '%s' crashed on %s", slug, entity_id)
        msg = str(exc) if current_app.config.get("RUCKUS_SHOW_DEBUG") else "Drill-in failed."
        return jsonify({"error": msg, "slug": slug,
                        "entity_id": entity_id, "tab": tab_slug}), 502
    return jsonify(build_envelope(data=data, summary={}, errors=[]))
