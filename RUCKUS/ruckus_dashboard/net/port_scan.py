"""Port selection and probing helpers for the RUCKUS dashboard.

Ported from monolith ``RUCKUS/ruckus_dashboard.py`` lines 3268-3357.

This module is intentionally decoupled from Flask: ``select_dashboard_port``
accepts ``scan_limit`` as a keyword argument instead of reading
``app.config["APP_PORT_SCAN_LIMIT"]``.
"""

from __future__ import annotations

import socket
from contextlib import closing


def _connect_probe_hosts(host: str) -> list[str]:
    normalized = (host or "").strip().lower()
    if normalized in ("", "0.0.0.0", "::"):
        return ["127.0.0.1", "::1"]
    if normalized == "localhost":
        return ["127.0.0.1"]
    return [host]


def _is_ipv6_host(host: str) -> bool:
    return ":" in host and host not in {"0.0.0.0"}


def _bind_family_host(host: str) -> tuple[int, str]:
    if _is_ipv6_host(host) or host == "::":
        return socket.AF_INET6, ("::1" if host == "::" else host)
    return socket.AF_INET, ("0.0.0.0" if host in {"", "0.0.0.0"} else host)


def port_has_active_listener(host: str, port: int) -> bool:
    for probe_host in _connect_probe_hosts(host):
        try:
            with closing(socket.create_connection((probe_host, port), timeout=0.25)):
                return True
        except OSError:
            continue
    return False


def can_exclusively_bind_port(host: str, port: int) -> bool:
    """True only if the port is free AND we can exclusively reserve it.

    On Windows SO_REUSEADDR lets two sockets share a port, masking a conflict;
    SO_EXCLUSIVEADDRUSE makes the probe bind fail when another listener exists.
    """
    if port == 0:
        return True
    if port_has_active_listener(host, port):
        return False
    family, bind_host = _bind_family_host(host)
    try:
        with closing(socket.socket(family, socket.SOCK_STREAM)) as probe:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((bind_host, port))
        return True
    except OSError:
        return False


def _reserve_random_port(host: str, scan_limit: int = 50) -> int:
    """Reserve an OS-selected random port for ``host``.

    ``scan_limit`` bounds the number of attempts to find a port we can
    exclusively bind to before returning the last OS-assigned port.
    """
    family, bind_host = _bind_family_host(host)
    attempts = max(1, int(scan_limit))
    last_port = 0
    for _ in range(attempts):
        with closing(socket.socket(family, socket.SOCK_STREAM)) as sock:
            sock.bind((bind_host, 0))
            last_port = int(sock.getsockname()[1])
        if can_exclusively_bind_port(host, last_port):
            return last_port
    return last_port


def select_dashboard_port(
    host: str,
    requested_port: int,
    auto_port: bool = True,
    scan_limit: int = 50,
) -> tuple[int, bool]:
    """Return ``(selected_port, used_random_port)``.

    Honors an explicit random request (port 0). Otherwise binds the requested
    port when exclusively available; if it is taken, falls back to an
    OS-selected random port (unless ``auto_port`` is False).

    ``scan_limit`` caps how many random ports we try before giving up. It is
    accepted as a kwarg so this module does not depend on Flask config.
    """
    if requested_port == 0:
        return _reserve_random_port(host, scan_limit=scan_limit), True
    if can_exclusively_bind_port(host, requested_port):
        return requested_port, False
    if not auto_port:
        raise SystemExit(
            f"Port {requested_port} is already in use. Set RUCKUS_AUTO_PORT=true "
            "(omit --no-auto-port) or free the configured port."
        )
    return _reserve_random_port(host, scan_limit=scan_limit), True


def port_self_test_script_block(host: str, requested_port: int) -> str:
    if requested_port == 0:
        return (
            f"Port self-test script block: request an OS-selected random HTTPS port on {host}; "
            "validate the selected listener before launch."
        )
    return (
        f"Port self-test script block: validate {host}:{requested_port}; "
        "if unavailable, bind to an OS-selected random HTTPS port."
    )
