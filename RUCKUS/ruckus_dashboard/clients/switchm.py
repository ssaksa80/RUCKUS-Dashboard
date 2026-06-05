"""RUCKUS Switch Manager (``/switchm/api``) client.

Extracted from ``clients/smartzone.py`` per Task 14 of the foundation plan.
The Switch Manager API lives on the same SmartZone controller host but under
a different URL prefix (``/switchm/api/<version>/...``) and uses a separate
API version line that does not always match the wireless public API version.

Source line ranges (monolith ``RUCKUS/ruckus_dashboard.py``):

* ``SWITCH_MANAGER_CAPABILITY_CANDIDATES`` constant -- 837-854
* ``SWITCH_STATUS_FIELDS`` / ``SWITCH_ONLINE_VALUES`` -- 1396-1402
* ``_aggregate_switch_status``                   -- 1405-1412
* ``_api_version_fallbacks`` (relocated here)    -- 1440-1461
* ``_switch_query_payload`` -> ``switch_query_payload`` -- 1464-1480
* ``_switch_manager_post``  -> ``switch_manager_post``  -- 1483-1496
* ``_fetch_smartzone_switches`` -> ``fetch_switches``   -- 1499-1553
* ``_controller_root``                           -- 1755-1757

``switch_manager_base`` is a NEW helper introduced in this port: the monolith
inlined the URL derivation inside ``_switch_manager_post`` via
``f"{_controller_root(...)}/switchm/api/{version}/..."``. Pulling it out
keeps the path math testable and lets future modules (capabilities discovery,
firmware posture) reuse the same base without duplicating the prefix swap.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, urlunparse

from ..auth.session_store import ConnectionConfig
from .base import (
    RuckusClientError,
    _coerce_int,
    _extract_items,
    _first_present,
    _first_value,
    _maybe_disable_tls_warnings,
    request_json,
)


# ─────────────────────────────────────────────────────────────────────────────
# Switch status constants (monolith 1396-1402)
# ─────────────────────────────────────────────────────────────────────────────
SWITCH_STATUS_FIELDS = [
    "status", "switchStatus.status", "switchStatus", "deviceStatus", "onlineStatus",
    "state", "registrationState", "connectionState", "connectionStatus",
]
SWITCH_ONLINE_VALUES = {
    "online", "connected", "run", "operational", "registered", "up", "approved", "ok",
}


# ─────────────────────────────────────────────────────────────────────────────
# Capability discovery candidates (monolith 837-854)
#
# Surfaced by clients/capabilities.py (Task 16) when probing what the connected
# SmartZone exposes on its Switch Manager surface. Listed here because the
# paths are switchm-specific.
# ─────────────────────────────────────────────────────────────────────────────
SWITCH_MANAGER_CAPABILITY_CANDIDATES = [
    ("POST", "/switch/view/details"),
    ("GET", "/switch/{id}"),
    ("GET", "/switchModel/list"),
    ("POST", "/health/status/all"),
    ("POST", "/health/cpu/agg"),
    ("POST", "/health/mem/agg"),
    ("POST", "/switch/ports/summary"),
    ("POST", "/switch/ports/details"),
    ("POST", "/switch/clients"),
    ("POST", "/switchClientVisibility/query"),
    ("POST", "/traffic/top/usage"),
    ("POST", "/traffic/top/portusage"),
    ("POST", "/traffic/top/poeutilization"),
    ("GET", "/firmware"),
    ("GET", "/switch/{switchId}/firmware"),
    ("GET", "/stack/{switchId}"),
]


# ─────────────────────────────────────────────────────────────────────────────
# URL helpers (monolith 1755-1757 + NEW switch_manager_base helper)
# ─────────────────────────────────────────────────────────────────────────────
def _controller_root(api_base: str) -> str:
    """Strip path/query/fragment from a SmartZone API base URL."""
    parsed = urlparse(api_base)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def switch_manager_base(smartzone_api_base: str) -> str:
    """Derive the Switch Manager API base from a SmartZone API base.

    The monolith inlined this swap (``/wsg/api/public`` -> ``/switchm/api/public``)
    inside ``_switch_manager_post``; pulled out for testability. The substring
    swap matches the behaviour of ``_controller_root + "/switchm/api"`` because
    the public SmartZone prefix is always ``/wsg/api/public`` after
    ``normalize_smartzone_base``.
    """
    return smartzone_api_base.replace("/wsg/api/public", "/switchm/api/public")


# ─────────────────────────────────────────────────────────────────────────────
# API version fallbacks (monolith 1440-1461, relocated from smartzone.py)
# ─────────────────────────────────────────────────────────────────────────────
def _api_version_fallbacks(api_version: str) -> list[str]:
    """Switch Manager API version candidates, newest first.

    The Switch Manager (``/switchm/api``) version can differ from the wireless
    public API version, so walk down from the connected version and append
    known recent SmartZone releases as a backstop.
    """
    versions: list[str] = []
    match = re.fullmatch(r"v(\d+)_(\d+)", str(api_version or ""))
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        for current_major in range(major, max(0, major - 3), -1):
            start_minor = minor if current_major == major else 1
            for current_minor in range(start_minor, -1, -1):
                versions.append(f"v{current_major}_{current_minor}")
    elif api_version:
        versions.append(api_version)
    for fallback in ["v13_1", "v13_0", "v12_0", "v11_1", "v11_0"]:
        if fallback not in versions:
            versions.append(fallback)
    return versions


# ─────────────────────────────────────────────────────────────────────────────
# Query payload + POST helper (monolith 1464-1496)
# ─────────────────────────────────────────────────────────────────────────────
def switch_query_payload(
    page: int, limit: int, sort_column: str = "serialNumber"
) -> dict[str, Any]:
    """Full SmartZone query body the Switch Manager endpoints require.

    A bare ``{page, limit}`` is rejected -- the filters/attributes/fullTextSearch
    envelope is mandatory.
    """
    payload: dict[str, Any] = {
        "filters": [],
        "fullTextSearch": {"type": "AND", "value": ""},
        "attributes": ["*"],
        "page": page,
        "limit": limit,
        "expandDomains": True,
    }
    if sort_column:
        payload["sortInfo"] = {"sortColumn": sort_column, "dir": "ASC"}
    return payload


def switch_manager_post(
    connection: ConnectionConfig,
    version: str,
    path: str,
    config: dict[str, Any],
    payload: dict[str, Any],
) -> Any:
    verify_tls = connection.verify_tls
    _maybe_disable_tls_warnings(verify_tls)
    url = (
        f"{switch_manager_base(connection.api_base)}"
        f"/{version}/{path.lstrip('/')}"
    )
    return request_json(
        "POST", url, config,
        params={"serviceTicket": connection.auth_token}, json=payload,
        verify=verify_tls,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json;charset=UTF-8",
        },
        debug_label=f"Switch Manager {path}",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Switch status aggregation (monolith 1405-1412)
# ─────────────────────────────────────────────────────────────────────────────
def _aggregate_switch_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    online = 0
    for switch in rows:
        status = str(_first_present(switch, SWITCH_STATUS_FIELDS) or "").strip().lower()
        if status in SWITCH_ONLINE_VALUES:
            online += 1
    return {"total": total, "online": online, "offline": max(0, total - online)}


# ─────────────────────────────────────────────────────────────────────────────
# Public fetch entry point (monolith 1499-1553)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_switches(
    connection: ConnectionConfig,
    config: dict[str, Any],
    debug: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """ICX switch online/offline counts via the Switch Manager API.

    Walks version candidates x path candidates until one responds, using the
    full SmartZone query payload. Returns ``None`` only if every combination
    errors. The monolith returned the aggregate-status dict directly; the
    port wraps it in ``{"switches": [...], **aggregate}`` so callers can
    inspect individual rows without re-issuing the paged walk.
    """
    if debug is None:
        debug = []
    limit = min(int(config["RUCKUS_PAGE_LIMIT"]), 1000)
    max_records = int(config.get("RUCKUS_MAX_SWITCH_RECORDS", 2000))
    candidates = ["switch", "switch/view/details"]

    for version in _api_version_fallbacks(connection.api_version):
        for path in candidates:
            rows: list[dict[str, Any]] = []
            page = 1
            ok = False
            try:
                while len(rows) < max_records:
                    data = switch_manager_post(
                        connection, version, path, config,
                        switch_query_payload(page, limit),
                    )
                    ok = True
                    items = [
                        item for item in _extract_items(data)
                        if isinstance(item, dict)
                    ]
                    rows.extend(items)
                    total = _coerce_int(
                        _first_value(data, ["totalCount", "rawDataTotalCount"])
                        if isinstance(data, dict) else None,
                        0,
                    )
                    has_more = isinstance(data, dict) and bool(data.get("hasMore"))
                    if not items or not has_more or (total and len(rows) >= total):
                        break
                    page += 1
            except RuckusClientError as exc:
                debug.append(
                    {
                        "label": f"POST /switchm/api/{version}/{path}",
                        "status": exc.status_code,
                        "domain": "ICX switches",
                    }
                )
                continue
            if ok:
                debug.append(
                    {
                        "label": f"POST /switchm/api/{version}/{path}",
                        "status": "ok",
                        "domain": "ICX switches",
                        "records": len(rows),
                    }
                )
                aggregate = _aggregate_switch_status(rows)
                return {"switches": rows, **aggregate}

    return None
