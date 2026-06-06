"""Warmup observability endpoints (SSE + sync status)."""
from __future__ import annotations
import json
from flask import Blueprint, Response, current_app, jsonify, session, stream_with_context

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


@bp.get("/api/warmup")
def stream():
    if not session.get("auth"):
        return jsonify({"error": "Not authenticated.", "reauth": True}), 401

    scheduler = getattr(current_app, "warmup_scheduler", None)

    @stream_with_context
    def gen():
        if scheduler is None:
            yield "event: complete\ndata: {}\n\n"
            return

        listener = scheduler.add_listener()
        seen_states: dict[str, str] = {}
        try:
            for slug, st in scheduler.snapshot().items():
                if st.status in ("done", "failed", "disabled", "timed_out", "skipped"):
                    payload = json.dumps(_serialise_status(st))
                    yield f"event: module-ready\ndata: {payload}\n\n"
                    seen_states[slug] = st.status

            while not scheduler.is_complete():
                listener.wait(timeout=2.0)
                listener.clear()
                for slug, st in scheduler.snapshot().items():
                    if seen_states.get(slug) != st.status and st.status in (
                        "done", "failed", "disabled", "timed_out", "skipped"
                    ):
                        payload = json.dumps(_serialise_status(st))
                        yield f"event: module-ready\ndata: {payload}\n\n"
                        seen_states[slug] = st.status

            yield "event: complete\ndata: {}\n\n"
        finally:
            scheduler.remove_listener(listener)

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


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
