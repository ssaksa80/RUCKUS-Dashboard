"""SMTP delivery for alerts and reports.

Ported from the proven networker-dashboard SMTP block: tri-mode security
(starttls/ssl/none) with SMTP_SSL, EHLO before/after STARTTLS, staged
diagnostics, and precise SMTP exception decoding so failures say exactly
what the server rejected."""
from __future__ import annotations

import email.utils
import smtplib
import socket
import ssl
from email.message import EmailMessage


class SmtpDeliveryError(RuntimeError):
    def __init__(self, stage: str, detail: str) -> None:
        super().__init__(f"SMTP failed at {stage}: {detail}")
        self.stage = stage
        self.detail = detail


def smtp_exception_detail(exc: BaseException) -> str:
    def _text(v):
        return v.decode("utf-8", errors="replace") if isinstance(v, bytes) else v

    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (f"authentication rejected by SMTP server: "
                f"code={exc.smtp_code} response={_text(exc.smtp_error)}")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return f"all recipients were refused by SMTP server: {exc.recipients}"
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return (f"sender was refused by SMTP server: code={exc.smtp_code} "
                f"sender={exc.sender} response={_text(exc.smtp_error)}")
    if isinstance(exc, smtplib.SMTPDataError):
        return (f"SMTP data command failed: code={exc.smtp_code} "
                f"response={_text(exc.smtp_error)}")
    if isinstance(exc, smtplib.SMTPConnectError):
        return (f"SMTP connection rejected: code={exc.smtp_code} "
                f"response={_text(exc.smtp_error)}")
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return f"SMTP server disconnected: {exc}"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "SMTP connection timed out."
    if isinstance(exc, ssl.SSLError):
        return f"TLS/SSL error: {exc}"
    if isinstance(exc, OSError):
        return f"network error: {exc}"
    return str(exc) or exc.__class__.__name__


def _security(smtp_cfg: dict) -> str:
    sec = str(smtp_cfg.get("security") or "").strip().lower()
    if sec in ("starttls", "ssl", "none"):
        return sec
    # Backward compat with the earlier boolean flag.
    return "starttls" if smtp_cfg.get("use_tls", True) else "none"


def send_email(cfg: dict, password: str, recipients: list[str],
               subject: str, body: str,
               attachment: bytes | None = None,
               filename: str = "report.xlsx") -> dict:
    """Send via the configured SMTP server. Raises SmtpDeliveryError with the
    failing stage + decoded server response on any failure."""
    smtp_cfg = cfg.get("smtp") or {}
    host = (smtp_cfg.get("host") or "").strip()
    if not host:
        raise ValueError("SMTP host is not configured.")
    to = [r.strip() for r in recipients if r and r.strip()]
    if not to:
        raise ValueError("No recipients configured.")
    port = int(smtp_cfg.get("port") or 587)
    security = _security(smtp_cfg)
    username = (smtp_cfg.get("username") or "").strip()

    stage = "prepare_message"
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = smtp_cfg.get("from_addr") or username or "ruckus-dashboard"
        msg["To"] = ", ".join(to)
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg.set_content(body)
        if attachment is not None:
            msg.add_attachment(
                attachment, maintype="application",
                subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=filename)

        if security == "ssl":
            stage = "connect_ssl"
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                if username and password:
                    stage = "login"
                    smtp.login(username, password)
                stage = "send_message"
                smtp.send_message(msg)
        else:
            stage = "connect"
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                stage = "ehlo"
                smtp.ehlo()
                if security == "starttls":
                    stage = "starttls"
                    smtp.starttls()
                    stage = "ehlo_after_starttls"
                    smtp.ehlo()
                if username and password:
                    stage = "login"
                    smtp.login(username, password)
                stage = "send_message"
                smtp.send_message(msg)
        return {"stage": "sent", "host": host, "port": port,
                "security": security, "recipients": to}
    except (smtplib.SMTPException, TimeoutError, socket.timeout,
            OSError, ssl.SSLError) as exc:
        raise SmtpDeliveryError(stage, smtp_exception_detail(exc)) from exc
