"""Audit-log helper for the Phase B identity layer (PB1).

Writes an :class:`AuditLog` row for auth/config events. Best-effort: an audit
failure must never break the user-facing action (it is logged and swallowed).
The client IP is taken from the request when one is active.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from flask import has_request_context, request

from ..db import session_scope
from ..db.models import AuditLog

LOG = logging.getLogger("ruckus_dashboard.auth.audit")


def _client_ip() -> Optional[str]:
    if not has_request_context():
        return None
    # Single-node behind a trusted reverse proxy; prefer the leftmost XFF hop
    # if present, else the peer address. (No proxy = remote_addr.)
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr


def record_audit(
    app,
    *,
    action: str,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    detail: Optional[dict[str, Any]] = None,
    ip: Optional[str] = None,
) -> None:
    """Persist one audit row in its own transaction. Never raises."""
    try:
        with session_scope(app) as s:
            s.add(
                AuditLog(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    action=action,
                    detail=detail,
                    ip=ip if ip is not None else _client_ip(),
                )
            )
    except Exception:  # noqa: BLE001 - auditing must not break the request
        LOG.warning("failed to write audit row action=%s", action, exc_info=True)
