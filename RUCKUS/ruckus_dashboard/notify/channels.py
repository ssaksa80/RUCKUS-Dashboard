"""Notification channel abstraction.

NotificationChannel is a Protocol so new channels (Slack, Teams, webhook) can
be added by creating a new class + one register() line without touching
any caller.  Only EmailChannel is implemented in SP2.

Notification is re-exported from outage.py (defined there to avoid a circular
import, since render_alert returns one).
"""
from __future__ import annotations

import logging
from typing import Any

from .outage import Notification  # re-export; callers can import from here

# Module-level imports so tests can monkeypatch these names at module scope
# (EmailChannel.send references them via this module, not via a local import).
from .mailer import send_email
from .config import smtp_password

LOG = logging.getLogger("ruckus.notify")


class EmailChannel:
    """Dispatch a Notification via SMTP using notify/mailer.send_email.

    mailer.py is intentionally untouched — this class is the only seam between
    the outage engine and the SMTP layer."""

    name: str = "email"

    def is_configured(self, cfg: dict) -> bool:
        recipients = (cfg.get("alerts") or {}).get("recipients") or []
        return bool(recipients)

    def send(self, cfg: dict, secrets: Any, note: Notification) -> None:
        """Send *note* via SMTP.  Swallows all exceptions (per-channel isolation)."""
        try:
            pw = smtp_password(cfg, secrets)
            recipients = (cfg.get("alerts") or {}).get("recipients") or []
            send_email(cfg, pw, recipients, note.subject, note.body)
        except Exception:  # noqa: BLE001 — channel failure must never kill the tick
            LOG.exception("notify: email channel send failed")


# ── registry ──────────────────────────────────────────────────────────────

CHANNELS: dict[str, EmailChannel] = {
    "email": EmailChannel(),
}
