"""Module list + per-module data endpoints."""
from __future__ import annotations
from flask import Blueprint, abort, current_app, jsonify, request, session

from ..modules import MODULES, all_modules
from ..modules._base import FetcherContext
from ..infra.envelope import build_envelope
from ..infra.capability_gate import CapabilityGate
import ruckus_dashboard.modules._registry  # noqa: F401  side-effect: registers stubs

bp = Blueprint("modules", __name__)


@bp.get("/api/modules")
def list_modules():
    return jsonify({
        "modules": [
            {"slug": m.slug, "title": m.title, "group": m.group, "icon": m.icon,
             "poll_seconds": m.poll_seconds, "requires_platforms": list(m.requires_platforms),
             "requires_capabilities": [list(c) for c in m.requires_capabilities],
             "supports_views": list(m.supports_views)}
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

    gate = CapabilityGate(available=getattr(current_app, "available_ops", set()))
    if not gate.satisfied(spec.requires_capabilities):
        env = build_envelope(
            data={"items": [], "disabled": True,
                  "missing_capabilities": gate.missing(spec.requires_capabilities)},
            summary={"count": 0, "disabled": True},
            errors=[],
        )
        return jsonify(env)

    filters = request.args.to_dict()
    data_per_conn = []
    for _, conn in pairs:
        ctx = FetcherContext(connection=conn, config=dict(current_app.config),
                             filters=filters, capability_gate=gate,
                             connection_label=conn.display_name)
        data_per_conn.append(spec.fetcher(ctx))

    items = []
    for d in data_per_conn:
        items.extend(d.get("items", []))
    merged = {"items": items}
    summary = spec.summary_fn(merged)
    env = build_envelope(data=merged, summary=summary, errors=[])
    return jsonify(env)
