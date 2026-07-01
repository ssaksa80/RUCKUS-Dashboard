"""Notification/report configuration API + the settings page."""
from __future__ import annotations

import io
import time

from flask import (Blueprint, current_app, jsonify, render_template, request,
                   send_file, session)

from ..auth.csrf import validate_csrf
from ..infra.capability_gate import CapabilityGate
from ..modules import MODULES, all_modules
from ..notify.config import (display_config, load_config, save_config,
                             smtp_password)
from ..notify.mailer import send_email
from ..reports.collect import collect_report_model
from ..reports.excel import build_report

bp = Blueprint("notifications", __name__)


def _unauth():
    return jsonify({"error": "Not authenticated.", "reauth": True}), 401


@bp.get("/notifications")
def page():
    if not session.get("auth"):
        return render_template("login.html",
                               csrf_token=session.get("csrf_token", ""))
    return render_template("notifications.html",
                           modules=all_modules(),
                           csrf_token=session.get("csrf_token", ""))


@bp.get("/api/notifications/config")
def get_config():
    if not session.get("auth"):
        return _unauth()
    cfg = load_config(current_app.instance_path)
    return jsonify(display_config(cfg))


@bp.post("/api/notifications/config")
def post_config():
    if not session.get("auth"):
        return _unauth()
    validate_csrf()
    incoming = request.get_json(silent=True)
    if not isinstance(incoming, dict):
        return jsonify({"error": "Invalid payload."}), 400
    cfg = save_config(current_app.instance_path, incoming,
                      current_app.secrets_manager)
    return jsonify(display_config(cfg))


@bp.post("/api/notifications/test")
def test_email():
    if not session.get("auth"):
        return _unauth()
    validate_csrf()
    cfg = load_config(current_app.instance_path)
    kind = str((request.get_json(silent=True) or {}).get("kind") or "smtp")
    if kind == "alerts":
        recipients = cfg["alerts"]["recipients"]
        subject = "[RUCKUS DSO] Test alert notification"
        body = ("This is a test of the automated alert channel. Real alerts "
                "fire on AP/switch offline transitions, critical alarms and "
                "poor-signal APs. — RUCKUS DSO Dashboard")
    elif kind == "report":
        recipients = cfg["report"]["recipients"]
        subject = "[RUCKUS DSO] Test report notification"
        body = ("This is a test of the daily report channel (without the "
                "attachment — use 'E-mail report now' for a full run). "
                "— RUCKUS DSO Dashboard")
    else:
        recipients = (cfg["alerts"]["recipients"] or cfg["report"]["recipients"])
        subject = "[RUCKUS DSO] Test e-mail"
        body = "SMTP configuration works. — RUCKUS DSO Dashboard"
    try:
        send_email(cfg, smtp_password(cfg, current_app.secrets_manager),
                   recipients, subject, body)
        return jsonify({"sent": True, "recipients": recipients})
    except Exception as exc:  # noqa: BLE001 — surface the reason to the UI
        return jsonify({"sent": False, "error": str(exc)}), 502


@bp.post("/api/reports/test")
def email_report_now():
    """Build the Excel report from live data and e-mail it immediately."""
    if not session.get("auth"):
        return _unauth()
    validate_csrf()
    conn = None
    for cid in session.get("connection_ids", []):
        conn = current_app.connection_store.get(cid)
        if conn is not None:
            break
    if conn is None:
        return jsonify({"error": "Connection expired.", "reauth": True}), 401
    cfg = load_config(current_app.instance_path)
    try:
        model = collect_report_model(
            conn, dict(current_app.config),
            available_ops=current_app.capability_registry.get_for(
            session.get("connection_ids", [])))
        xlsx = build_report(model)
        ts = time.strftime("%Y-%m-%d", time.gmtime())
        send_email(cfg, smtp_password(cfg, current_app.secrets_manager),
                   cfg["report"]["recipients"],
                   f"[RUCKUS DSO] Daily report {ts} (manual run)",
                   "Attached: RUCKUS DSO fabric report (manual run).",
                   attachment=xlsx,
                   filename=f"ruckus-dso-report-{ts}.xlsx")
        return jsonify({"sent": True, "recipients": cfg["report"]["recipients"]})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"sent": False, "error": str(exc)}), 502


@bp.get("/api/reports/generate")
def generate_report():
    if not session.get("auth"):
        return _unauth()
    conn = None
    for cid in session.get("connection_ids", []):
        conn = current_app.connection_store.get(cid)
        if conn is not None:
            break
    if conn is None:
        return jsonify({"error": "Connection expired.", "reauth": True}), 401
    model = collect_report_model(
        conn, dict(current_app.config),
        available_ops=current_app.capability_registry.get_for(
            session.get("connection_ids", [])))
    xlsx = build_report(model)
    ts = time.strftime("%Y%m%d-%H%M", time.gmtime())
    return send_file(io.BytesIO(xlsx),
                     mimetype=("application/vnd.openxmlformats-officedocument"
                               ".spreadsheetml.sheet"),
                     as_attachment=True,
                     download_name=f"ruckus-dso-report-{ts}.xlsx")


def _valid_filters(spec, raw) -> dict:
    """Keep only filters whose key the module exposes, mirroring the SP1 client
    predicate (``dashboard.js:_applyFilters``).

    Allowed keys: any resolved filter key (derived from the module's columns via
    ``resolved_filters``), plus the free-text ``__search`` and the per-column
    ``search:<col>`` / ``range:<col>`` forms. Scalar values are coerced to str;
    ``range:`` dicts (``{min,max}``) and multi-select lists pass through as-is so
    the in-model ``apply_filter`` sees the same shapes the browser sent."""
    if not isinstance(raw, dict):
        return {}
    col_keys = {c.key for c in spec.columns}
    resolved_keys = {f.key for f in spec.resolved_filters}
    out: dict = {}
    for key, val in raw.items():
        key = str(key)
        if key == "__search":
            allowed = True
        elif key.startswith("search:") or key.startswith("range:"):
            allowed = key.split(":", 1)[1] in col_keys
        else:
            allowed = key in resolved_keys
        if not allowed:
            continue
        if isinstance(val, (list, dict)):
            out[key] = val
        elif isinstance(val, (str, int, float)) and str(val) != "":
            out[key] = str(val)
    return out


@bp.post("/api/reports/tab")
def email_report_tab():
    """E-mail the current tab (one module's sheet), honoring active filters."""
    if not session.get("auth"):
        return _unauth()
    validate_csrf()
    payload = request.get_json(silent=True) or {}
    slug = str(payload.get("slug") or "")
    spec = MODULES.get(slug)
    if spec is None:
        return jsonify({"error": f"unknown module: {slug}"}), 404

    conn = None
    for cid in session.get("connection_ids", []):
        conn = current_app.connection_store.get(cid)
        if conn is not None:
            break
    if conn is None:
        return jsonify({"error": "Connection expired.", "reauth": True}), 401

    gate = CapabilityGate(available=current_app.capability_registry.get_for(
        session.get("connection_ids", [])))
    if not gate.satisfied(spec.requires_capabilities):
        return jsonify({"sent": False,
                        "error": "module unavailable on this controller"}), 422

    filters = _valid_filters(spec, payload.get("filters"))
    cfg = load_config(current_app.instance_path)
    recipients = payload.get("recipients")
    if not (isinstance(recipients, list) and
            [r for r in recipients if isinstance(r, str) and r.strip()]):
        recipients = cfg["report"]["recipients"]
    if not [r for r in (recipients or []) if r and str(r).strip()]:
        return jsonify({"sent": False, "error": "No recipients configured."}), 400

    try:
        model = collect_report_model(
            conn, dict(current_app.config),
            available_ops=current_app.capability_registry.get_for(
                session.get("connection_ids", [])),
            slugs=(slug,), filters_by_slug={slug: filters})
        xlsx = build_report(model)
        ts = time.strftime("%Y%m%d-%H%M", time.gmtime())
        send_email(cfg, smtp_password(cfg, current_app.secrets_manager),
                   recipients,
                   f"[RUCKUS DSO] {spec.title} report {ts}",
                   f"Attached: {spec.title} tab report"
                   + (" (filtered)." if filters else "."),
                   attachment=xlsx,
                   filename=f"ruckus-{slug}-{ts}.xlsx")
        rep = model.by_slug(slug)
        return jsonify({"sent": True, "recipients": recipients, "slug": slug,
                        "rows": len(rep.rows) if rep else 0,
                        "filtered": bool(filters)})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"sent": False, "error": str(exc)}), 502
