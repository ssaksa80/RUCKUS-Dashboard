"""Persist user-arranged topology node positions per controller.

Positions are a flat ``{nodeId: {x, y}}`` JSON stored in the app instance
folder, keyed by the first connection's controller host so every DSO screen
pointed at the same controller shares the arrangement."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, current_app, jsonify, request, session

from ..auth.csrf import validate_csrf

bp = Blueprint("topology_layout", __name__)

_MAX_BODY = 256 * 1024
_MAX_NODES = 2000


def _layout_path() -> Path:
    host = "default"
    for cid in session.get("connection_ids", []):
        conn = current_app.connection_store.get(cid)
        if conn is not None:
            host = re.sub(r"[^a-zA-Z0-9._-]", "_",
                          urlparse(conn.api_base).netloc or "default")
            break
    return Path(current_app.instance_path) / f"topology-layout-{host}.json"


@bp.get("/api/topology/layout")
def get_layout():
    if not session.get("auth"):
        return jsonify({"error": "Not authenticated.", "reauth": True}), 401
    try:
        positions = json.loads(_layout_path().read_text(encoding="utf-8"))
        if not isinstance(positions, dict):
            positions = {}
    except (OSError, ValueError):
        positions = {}
    return jsonify({"positions": positions})


@bp.post("/api/topology/layout")
def save_layout():
    if not session.get("auth"):
        return jsonify({"error": "Not authenticated.", "reauth": True}), 401
    validate_csrf()
    raw = request.get_data(as_text=True)
    if len(raw) > _MAX_BODY:
        return jsonify({"error": "Layout too large."}), 400
    try:
        body = json.loads(raw)
        positions = body["positions"]
        if not isinstance(positions, dict) or len(positions) > _MAX_NODES:
            raise ValueError("bad positions")
        clean = {str(k): {"x": float(v["x"]), "y": float(v["y"])}
                 for k, v in positions.items()}
    except Exception:  # noqa: BLE001 — any malformed body → 400
        return jsonify({"error": "Invalid layout payload."}), 400
    path = _layout_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean), encoding="utf-8")
    return jsonify({"saved": len(clean)})


@bp.delete("/api/topology/layout")
def reset_layout():
    if not session.get("auth"):
        return jsonify({"error": "Not authenticated.", "reauth": True}), 401
    validate_csrf()
    try:
        _layout_path().unlink(missing_ok=True)
    except OSError:
        pass
    return jsonify({"reset": True})
