"""HTTP client primitives shared by all controller clients.

Ported from the monolith (RUCKUS/ruckus_dashboard.py):

* ``RuckusClientError`` dataclass exception (lines 857-865)
* ``request_json`` (originally ``_request_json`` lines 1767-1832; renamed to
  public for re-use across client modules)
* Redaction / URL safety helpers ``_redact`` (2338-2355), ``_safe_url``
  (2295-2299), ``_maybe_disable_tls_warnings`` (2300-2304)
* Generic utility helpers used widely by client + module code:
  ``_extract_items``, ``_first_value``, ``_nested_value``, ``_first_present``,
  ``_nested_first``, ``_as_list``, ``_coerce_int``, ``_safe_port``,
  ``_format_host``, ``_host_label``, ``_format_time``, ``_parse_datetime``,
  ``_format_now`` (lines 2170-2333 and 728-729).

These helpers are kept underscore-prefixed because they remain *internal* to
the package; only ``request_json`` and ``RuckusClientError`` are part of the
public client surface. The host allow-list check is deferred to
``..net.allowlist.assert_host_allowed`` inside the function body to avoid a
circular import (allowlist raises ``RuckusClientError``).
"""

from __future__ import annotations

import json  # noqa: F401  (kept for parity with monolith / future use)
import logging  # noqa: F401  (clients may add module-level logging)
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests
import urllib3
from requests import exceptions as requests_exceptions


# ─────────────────────────────────────────────────────────────────────────────
# Exception
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RuckusClientError(Exception):
    message: str
    status_code: int = 502
    debug: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


# ─────────────────────────────────────────────────────────────────────────────
# URL / TLS helpers
# ─────────────────────────────────────────────────────────────────────────────
def _safe_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _maybe_disable_tls_warnings(verify_tls: bool | str) -> None:
    if verify_tls is False:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ─────────────────────────────────────────────────────────────────────────────
# Redaction
# ─────────────────────────────────────────────────────────────────────────────
def _redact(data: Any) -> Any:
    if isinstance(data, dict):
        redacted: dict[str, Any] = {}
        for key, value in data.items():
            lowered = key.lower()
            if any(secret in lowered for secret in ("password", "secret", "token", "ticket")):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact(value)
        return redacted
    if isinstance(data, list):
        return [_redact(item) for item in data]
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Generic dict / list / value utilities
# ─────────────────────────────────────────────────────────────────────────────
def _extract_items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("list", "data", "items", "results", "content", "records"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _first_value(data: Any, names: list[str]) -> Any:
    if not isinstance(data, dict):
        return None
    for name in names:
        value = data.get(name)
        if value is not None and value != "":
            return value
    return None


def _nested_value(data: Any, path: list[str]) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_present(data: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        value = _nested_value(data, name.split("."))
        if value is not None and value != "":
            return value
    return None


def _nested_first(data: dict[str, Any], paths: list[list[str]]) -> Any:
    for path in paths:
        current: Any = data
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if current is not None and current != "":
            return current
    return None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_port(parsed: Any, default_port: int) -> int:
    try:
        port = parsed.port or default_port
    except ValueError as exc:
        raise ValueError("Endpoint port is invalid.") from exc
    if port <= 0 or port > 65535:
        raise ValueError("Endpoint port is invalid.")
    return port


def _format_host(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def _host_label(url: str) -> str:
    parsed = urlparse(url)
    return parsed.hostname or url


# ─────────────────────────────────────────────────────────────────────────────
# Datetime helpers
# ─────────────────────────────────────────────────────────────────────────────
def _format_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


def _parse_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_time(value: Any) -> str:
    if value is None or value == "" or value == 0:
        return ""
    if isinstance(value, (int, float)) or str(value).isdigit():
        number = float(value)
        if number > 10_000_000_000:
            number = number / 1000
        return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(number))
    parsed = _parse_datetime(str(value))
    if parsed:
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(value)


# ─────────────────────────────────────────────────────────────────────────────
# Core HTTP entry point
# ─────────────────────────────────────────────────────────────────────────────
def request_json(
    method: str,
    url: str,
    config: dict[str, Any],
    *,
    debug_label: str,
    expected_status: set[int] | None = None,
    **kwargs: Any,
) -> Any:
    """Issue an HTTP request and decode JSON, wrapping errors as RuckusClientError.

    Enforces the host allow-list (SSRF guard) before contacting the network.
    All exception paths preserve a redacted ``debug`` payload so the UI can
    surface a useful diagnostic without leaking secrets.
    """
    # Lazy import to avoid a circular dependency: allowlist.assert_host_allowed
    # raises RuckusClientError, which lives in this module.
    from ..net.allowlist import assert_host_allowed

    host = _host_label(url)
    assert_host_allowed(host, config)

    expected_status = expected_status or {200, 201, 202, 204}
    timeout = float(config["RUCKUS_TIMEOUT_SECONDS"])
    debug: dict[str, Any] = {"label": debug_label, "url": _safe_url(url), "status": None}
    try:
        # SSRF guard: the allow-list is checked on the initial host only, so a 3xx
        # must not be auto-followed to an unchecked host. RUCKUS APIs never redirect.
        response = requests.request(method, url, timeout=timeout, allow_redirects=False, **kwargs)
        debug["status"] = response.status_code
        debug["raw"] = response.text[: int(config["RUCKUS_DEBUG_BYTES"])]
        if response.status_code not in expected_status:
            message = f"{debug_label} failed with HTTP {response.status_code}."
            if response.status_code in (401, 403):
                message += (
                    " The SmartZone API session token (serviceTicket) was rejected or "
                    "timed out. Click Refresh to retry, or Logout and reconnect."
                )
            raise RuckusClientError(message, response.status_code, debug)
        if response.status_code == 204 or not response.text.strip():
            return {}
        return response.json()
    except RuckusClientError:
        raise
    except requests_exceptions.SSLError as exc:
        raise RuckusClientError(
            (
                f"{debug_label} failed because the HTTPS certificate could not be "
                "validated. Import the SmartZone CA certificate, set "
                "RUCKUS_VERIFY_TLS to a CA bundle path, or use the self-signed lab "
                "TLS checkbox for controlled testing."
            ),
            502,
            {**debug, "error": str(exc)},
        ) from exc
    except requests_exceptions.ConnectTimeout as exc:
        raise RuckusClientError(
            (
                f"{debug_label} timed out while opening the TCP connection. Verify "
                "firewall access from this dashboard server to the SmartZone host "
                "on TCP 8443."
            ),
            504,
            {**debug, "error": str(exc)},
        ) from exc
    except requests_exceptions.ReadTimeout as exc:
        raise RuckusClientError(
            f"{debug_label} connected but timed out waiting for SmartZone to respond.",
            504,
            {**debug, "error": str(exc)},
        ) from exc
    except requests_exceptions.ConnectionError as exc:
        raise RuckusClientError(
            (
                f"{debug_label} could not connect to {_safe_url(url)}. Check DNS/IP, "
                "routing, and firewall access to TCP 8443."
            ),
            502,
            {**debug, "error": str(exc)},
        ) from exc
    except requests.RequestException as exc:
        raise RuckusClientError(
            f"{debug_label} failed. Check network reachability, TLS, and permissions.",
            502,
            {**debug, "error": str(exc)},
        ) from exc
    except ValueError as exc:
        raise RuckusClientError(
            f"{debug_label} returned a non-JSON response.", 502, debug
        ) from exc
