"""Warmup observability endpoints (SSE + sync status)."""
from __future__ import annotations
from flask import Blueprint, current_app, jsonify, session

bp = Blueprint("warmup", __name__)


@bp.get("/api/warmup/status")
def status():
    if not session.get("auth"):
        return jsonify({"error": "Not authenticated.", "reauth": True}), 401

    scheduler = getattr(current_app, "warmup_scheduler", None)
    if scheduler is None:
        return jsonify({"complete": True, "states": {}})

    snap = scheduler.snapshot()
    states = {slug: _serialise_status(st) for slug, st in snap.items()}
    return jsonify({"complete": scheduler.is_complete(), "states": states})


def _serialise_status(st) -> dict:
    return {
        "slug": st.slug,
        "status": st.status,
        "summary": st.summary,
        "error_message": st.error_message,
        "started_at": st.started_at,
        "completed_at": st.completed_at,
        "missing_capabilities": [list(c) for c in st.missing_capabilities],
    }
