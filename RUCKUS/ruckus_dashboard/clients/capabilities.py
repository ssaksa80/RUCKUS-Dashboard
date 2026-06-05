"""SmartZone OpenAPI capability discovery.

Ported from the monolith (``RUCKUS/ruckus_dashboard.py``) per Task 16 of the
foundation plan:

* ``OPENAPI_METHODS``                   -- line 817
* ``SMARTZONE_CAPABILITY_CANDIDATES``   -- lines 819-835
* ``discover_capabilities``             -- lines 1556-1571
* ``_discover_smartzone_capabilities``  -- lines 1573-1615
* ``_discover_openapi_source``          -- lines 1617-1659
* ``_summarize_openapi_source``         -- lines 1661-1694
* ``_candidate_probes``                 -- lines 1696-1704
* ``_capability_group``                 -- lines 1706-1749
* ``_strip_openapi_version``            -- lines 1751-1753
* ``_smartzone_openapi_urls``           -- lines 1760-1765

``_controller_root`` is imported from ``clients/switchm.py`` (Task 14, line 86)
to avoid duplication; ``SWITCH_MANAGER_CAPABILITY_CANDIDATES`` is imported from
the same module because the constants live next to their owning client.

NEW behaviour vs the monolith
-----------------------------

``_summarize_openapi_source`` now also publishes an ``available_ops`` set of
``(METHOD, /version-stripped/path)`` tuples for every operation in the spec.
``discover_capabilities`` merges those sets across all sources and exposes the
union at the top level under ``"available_ops"``. ModuleSpec capability gating
(Task 19+) uses this set as the source of truth for "can this controller
satisfy this module's required ops?". The monolith only surfaced the curated
probe list and group counts, both of which are still returned in each source
entry under ``"probes"`` / ``"groups"``.
"""

from __future__ import annotations

import re
from typing import Any

from ..auth.session_store import ConnectionConfig
from .base import (
    RuckusClientError,
    _safe_url,
    request_json,
)
from .smartzone import _api_version_key, _token_valid
from .switchm import SWITCH_MANAGER_CAPABILITY_CANDIDATES, _controller_root


# ─────────────────────────────────────────────────────────────────────────────
# Constants (monolith 817, 819-835)
# ─────────────────────────────────────────────────────────────────────────────
OPENAPI_METHODS = {"get", "post", "put", "patch", "delete"}

SMARTZONE_CAPABILITY_CANDIDATES = [
    ("GET", "/aps"),
    ("GET", "/aps/{apMac}/operational/summary"),
    ("GET", "/aps/{apMac}/operational/client/totalCount"),
    ("GET", "/rkszones"),
    ("GET", "/rkszones/{zoneId}/wlans"),
    ("POST", "/query/client"),
    ("POST", "/query/wiredclient"),
    ("POST", "/query/wlan"),
    ("POST", "/alert/alarmSummary"),
    ("POST", "/alert/eventSummary"),
    ("POST", "/query/roguesInfoList"),
    ("GET", "/system/devicesSummary"),
    ("GET", "/system/inventory"),
    ("GET", "/cluster/state"),
    ("GET", "/licensesSummary"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point (monolith 1556-1571)
# ─────────────────────────────────────────────────────────────────────────────
def discover_capabilities(
    connection: ConnectionConfig, config: dict[str, Any]
) -> dict[str, Any]:
    """Probe controller OpenAPI surfaces and return capability summary.

    Returns a dict with ``status``, ``summary``, ``sources``, ``debug``, and
    ``available_ops`` (a ``set[tuple[str, str]]`` of ``(METHOD, /path)`` pairs
    derived from every OpenAPI document the probe could reach). ModuleSpec
    capability gating uses ``available_ops``; the legacy keys are preserved
    for the diagnostics panel in the monolith UI.
    """
    _token_valid(connection)
    if connection.platform != "smartzone":
        return {
            "status": "unsupported",
            "summary": {
                "source_count": 0,
                "available_sources": 0,
                "operation_count": 0,
            },
            "sources": [],
            "debug": [],
            "available_ops": set(),
        }
    debug: list[dict[str, Any]] = []
    capabilities = _discover_smartzone_capabilities(connection, config, debug)
    capabilities["debug"] = debug
    return capabilities


# ─────────────────────────────────────────────────────────────────────────────
# SmartZone discovery (monolith 1573-1615)
# ─────────────────────────────────────────────────────────────────────────────
def _discover_smartzone_capabilities(
    connection: ConnectionConfig,
    config: dict[str, Any],
    debug: list[dict[str, Any]],
) -> dict[str, Any]:
    if not config.get("RUCKUS_CAPABILITY_DISCOVERY", False):
        return {
            "status": "disabled",
            "summary": {
                "source_count": 0,
                "available_sources": 0,
                "operation_count": 0,
            },
            "sources": [],
            "available_ops": set(),
        }
    controller_root = _controller_root(connection.api_base)
    sources = [
        _discover_openapi_source(
            connection, config, debug,
            name="SmartZone Public API", family="wireless",
            prefix="/wsg/api/public/{apiVersion}",
            urls=_smartzone_openapi_urls(connection.api_base, controller_root),
            candidates=SMARTZONE_CAPABILITY_CANDIDATES,
        ),
        _discover_openapi_source(
            connection, config, debug,
            name="Switch Manager API", family="switch",
            prefix="/switchm/api/{apiVersion}",
            urls=[f"{controller_root}/switchm/api/openapi"],
            candidates=SWITCH_MANAGER_CAPABILITY_CANDIDATES,
        ),
    ]
    available_sources = [s for s in sources if s["status"] == "available"]
    if len(available_sources) == len(sources):
        status = "available"
    elif available_sources:
        status = "partial"
    else:
        status = "unavailable"

    # NEW: union of operations across every available source. ``pop`` the
    # per-source set so the returned ``sources`` entries stay JSON-friendly
    # (sets aren't JSON-serialisable and the monolith debug panel will choke).
    available_ops: set[tuple[str, str]] = set()
    for source in sources:
        ops = source.pop("available_ops", None)
        if ops:
            available_ops.update(ops)

    return {
        "status": status,
        "summary": {
            "source_count": len(sources),
            "available_sources": len(available_sources),
            "operation_count": sum(s.get("operation_count", 0) for s in sources),
        },
        "sources": sources,
        "available_ops": available_ops,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Single source probe (monolith 1617-1659)
# ─────────────────────────────────────────────────────────────────────────────
def _discover_openapi_source(
    connection: ConnectionConfig,
    config: dict[str, Any],
    debug: list[dict[str, Any]],
    *,
    name: str,
    family: str,
    prefix: str,
    urls: list[str],
    candidates: list[tuple[str, str]],
) -> dict[str, Any]:
    errors: list[str] = []
    for url in urls:
        for params in [None, {"serviceTicket": connection.auth_token}]:
            try:
                spec = request_json(
                    "GET", url, config, params=params, verify=connection.verify_tls,
                    headers={"Accept": "application/json"},
                    debug_label=f"{name} OpenAPI discovery",
                )
            except RuckusClientError as exc:
                errors.append(f"{_safe_url(url)}: {exc.message}")
                debug.append(
                    {
                        "label": f"GET {_safe_url(url)}",
                        "status": exc.status_code,
                        "capability": name,
                    }
                )
                if params is None and exc.status_code in {401, 403}:
                    continue
                break
            source = _summarize_openapi_source(
                name=name, family=family, prefix=prefix, url=url,
                spec=spec, candidates=candidates,
            )
            debug.append(
                {
                    "label": f"GET {_safe_url(url)}",
                    "status": "ok",
                    "capability": name,
                    "paths": source["path_count"],
                    "operations": source["operation_count"],
                }
            )
            return source
    return {
        "name": name,
        "family": family,
        "status": "unavailable",
        "prefix": prefix,
        "url": _safe_url(urls[0]) if urls else "",
        "path_count": 0,
        "operation_count": 0,
        "versions": [],
        "groups": [],
        "probes": [],
        "available_ops": set(),
        "message": errors[-1] if errors else "OpenAPI document was not available.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Summarisation (monolith 1661-1694) -- NEW: includes ``available_ops`` set
# ─────────────────────────────────────────────────────────────────────────────
def _summarize_openapi_source(
    *,
    name: str,
    family: str,
    prefix: str,
    url: str,
    spec: dict[str, Any],
    candidates: list[tuple[str, str]],
) -> dict[str, Any]:
    paths = spec.get("paths") if isinstance(spec, dict) else {}
    if not isinstance(paths, dict):
        paths = {}
    versions: set[str] = set()
    group_counts: dict[str, int] = {}
    operations: set[tuple[str, str]] = set()
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        text_path = str(path)
        versions.update(re.findall(r"/(v\d+_\d+)(?:/|$)", text_path))
        stripped_path = _strip_openapi_version(text_path)
        group = _capability_group(family, stripped_path)
        for method in path_item:
            normalized_method = str(method).lower()
            if normalized_method not in OPENAPI_METHODS:
                continue
            operations.add((normalized_method.upper(), stripped_path))
            group_counts[group] = group_counts.get(group, 0) + 1
    available_ops = {
        (method.upper(), _strip_openapi_version(str(path)))
        for path, ops in paths.items()
        if isinstance(ops, dict)
        for method in ops
        if str(method).lower() in OPENAPI_METHODS
    }
    return {
        "name": name,
        "family": family,
        "status": "available",
        "prefix": prefix,
        "url": _safe_url(url),
        "path_count": len(paths),
        "operation_count": len(operations),
        "versions": sorted(versions, key=_api_version_key),
        "groups": [
            {"name": group, "count": count}
            for group, count in sorted(
                group_counts.items(), key=lambda item: (-item[1], item[0])
            )[:10]
        ],
        "probes": _candidate_probes(operations, candidates),
        "available_ops": available_ops,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers (monolith 1696-1753, 1760-1765)
# ─────────────────────────────────────────────────────────────────────────────
def _candidate_probes(
    operations: set[tuple[str, str]],
    candidates: list[tuple[str, str]],
) -> list[dict[str, str]]:
    probes = []
    for method, path in candidates:
        if (method, path) in operations:
            probes.append({"method": method, "path": path})
    return probes[:12]


def _capability_group(family: str, path: str) -> str:
    lowered = path.lower()
    if family == "switch":
        if "client" in lowered:
            return "Wired Clients"
        if "/health/" in lowered or lowered.startswith("/health"):
            return "Health"
        if "traffic" in lowered:
            return "Traffic"
        if "port" in lowered:
            return "Ports"
        if "firmware" in lowered:
            return "Firmware"
        if "stack" in lowered:
            return "Stacks"
        if "vlan" in lowered:
            return "VLANs"
        if "group" in lowered:
            return "Switch Groups"
        if "switch" in lowered:
            return "Switches"
        return "Other Switch APIs"
    if "wiredclient" in lowered:
        return "Wired Clients"
    if "client" in lowered:
        return "Wireless Clients"
    if lowered.startswith("/aps") or "/apgroups" in lowered:
        return "Access Points"
    if "wlan" in lowered:
        return "WLANs"
    if "rkszones" in lowered:
        return "Zones"
    if "alert" in lowered or "alarm" in lowered or "event" in lowered:
        return "Alarms & Events"
    if "rogue" in lowered:
        return "Rogues"
    if "map" in lowered:
        return "Maps"
    if "license" in lowered:
        return "Licensing"
    if "system" in lowered or "cluster" in lowered or "controller" in lowered:
        return "Controller"
    return "Other Wireless APIs"


def _strip_openapi_version(path: str) -> str:
    return re.sub(r"^/v\d+_\d+(?=/|$)", "", path) or path


def _smartzone_openapi_urls(api_base: str, controller_root: str) -> list[str]:
    from urllib.parse import urlparse

    parsed = urlparse(api_base)
    if parsed.path.startswith("/wsg/"):
        return [f"{controller_root}/wsg/apiDoc/openapi"]
    return [
        f"{controller_root}/apiDoc/openapi",
        f"{controller_root}/wsg/apiDoc/openapi",
    ]
