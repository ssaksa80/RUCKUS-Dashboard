"""Host allow-list / SSRF guard.

Ported from the monolith (RUCKUS/ruckus_dashboard.py lines 2803-2884).
The private ``_assert_host_allowed`` helper is exposed publicly here as
``assert_host_allowed`` so that the ``clients/*`` modules ported in later
tasks can import it directly.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any


class HostAllowList:
    def __init__(self, raw: str = "") -> None:
        self.enabled = False
        self.names: set[str] = set()
        self.networks: list[Any] = []
        self.pinned_ips: set[str] = set()
        self.configure(raw)

    def configure(self, raw: str) -> None:
        self.names.clear()
        self.networks.clear()
        self.pinned_ips.clear()
        for entry in (raw or "").split(","):
            entry = entry.strip()
            if not entry:
                continue
            try:
                self.networks.append(ipaddress.ip_network(entry, strict=False))
                continue
            except ValueError:
                pass
            name = self._normalize(entry)
            if name:
                self.names.add(name)
                for ip in self._resolve(name):
                    self.pinned_ips.add(ip)
        self.enabled = bool(self.names or self.networks)

    @staticmethod
    def _normalize(host: str) -> str:
        return (host or "").strip().lower().strip("[]")

    @staticmethod
    def _resolve(host: str) -> set[str]:
        try:
            infos = socket.getaddrinfo(host, None)
        except (socket.gaierror, OSError, UnicodeError):
            return set()
        return {info[4][0] for info in infos if info[4] and info[4][0]}

    def _ip_in_networks(self, ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in self.networks)

    def host_allowed(self, host: str) -> bool:
        if not self.enabled:
            return True
        h = self._normalize(host)
        if not h:
            return False
        try:
            ipaddress.ip_address(h)
            return self._ip_in_networks(h)
        except ValueError:
            pass
        if h not in self.names:
            return False
        resolved = self._resolve(h)
        if not resolved:
            return False
        # DNS-rebinding guard: every resolved IP must match a pinned IP / network.
        return all(ip in self.pinned_ips or self._ip_in_networks(ip) for ip in resolved)


def assert_host_allowed(host: str, config: dict[str, Any]) -> None:
    allowlist = config.get("RUCKUS_HOST_ALLOWLIST")
    if allowlist is not None and not allowlist.host_allowed(host):
        # Lazy import to break the circular dependency: clients/base.py imports
        # this module for the SSRF check, and RuckusClientError lives there.
        from ..clients.base import RuckusClientError

        raise RuckusClientError(
            f"Host '{host}' is not in the configured allow-list (RUCKUS_ALLOWED_HOSTS).",
            502,
        )
