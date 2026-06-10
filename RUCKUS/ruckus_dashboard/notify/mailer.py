"""SMTP delivery for alerts and reports."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any


def send_email(cfg: dict, password: str, recipients: list[str],
               subject: str, body: str,
               attachment: bytes | None = None,
               filename: str = "report.xlsx") -> None:
    """Send via the configured SMTP server. Raises on any failure."""
    smtp = cfg.get("smtp") or {}
    host = (smtp.get("host") or "").strip()
    if not host:
        raise ValueError("SMTP host is not configured.")
    to = [r.strip() for r in recipients if r and r.strip()]
    if not to:
        raise ValueError("No recipients configured.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp.get("from_addr") or smtp.get("username") or "ruckus-dashboard"
    msg["To"] = ", ".join(to)
    msg.set_content(body)
    if attachment is not None:
        msg.add_attachment(
            attachment, maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=filename)

    port = int(smtp.get("port") or 587)
    with smtplib.SMTP(host, port, timeout=20) as server:
        if smtp.get("use_tls", True):
            server.starttls()
        username = (smtp.get("username") or "").strip()
        if username and password:
            server.login(username, password)
        server.send_message(msg)
