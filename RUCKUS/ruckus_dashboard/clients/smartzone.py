"""RUCKUS SmartZone (on-prem controller public API) client.

Ported from the monolith ``RUCKUS/ruckus_dashboard.py``. This module is
deliberately SmartZone-only: cross-platform dispatch (``platform == "smartzone"``
vs ``"ruckus_one"``) is inlined here for ``fetch_inventory`` rather than
preserving the monolith's central dispatcher (which will live in the app
factory once Ruckus One is ported in Task 15).

Source line ranges (monolith):

* AP / firmware / zone / patch field constants  -- 768-816
* ``authenticate_smartzone``                    -- 876-930
* ``disconnect_smartzone`` (renamed from ``disconnect_connection``)
                                                -- 976-988
* ``_token_valid``                              -- 991-993
* ``fetch_inventory``                           -- 996-1002 (platform branch
                                                  inlined to smartzone only)
* ``normalize_smartzone_base``                  -- 1026-1050
* ``_fetch_smartzone_inventory``                -- 1098-1240
* ``_fetch_smartzone_operational``              -- 1242-1278
* ``_aggregate_ap_status`` / ``_empty_ap_stats``-- 1360-1393
* ``smartzone_alarm_summary``                   -- 1415-1438
* paged / get / post helpers                    -- 1834-1931
* posture / catalog / activity helpers          -- 1989-2154
* ``_connection_payload``                       -- 2157-2167
* ``_smartzone_ap_needs_detail``                -- 2182-2189
* ``_latest_api_version`` / ``_api_version_key``-- 2209-2219
* ``_latest_firmware`` / ``_version_key``       -- 2220-2228

Switch Manager-only helpers (``switch_manager_post``, ``fetch_switches``,
``_controller_root``, ``switch_query_payload``, ``_aggregate_switch_status``,
``_api_version_fallbacks``) live in ``clients/switchm.py`` (Task 14).
``_fetch_smartzone_operational`` re-imports ``fetch_switches`` from there.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

from ..auth.session_store import ConnectionConfig
from .base import (
    RuckusClientError,
    _as_list,
    _coerce_int,
    _extract_items,
    _first_present,
    _first_value,
    _format_host,
    _format_now,
    _format_time,
    _host_label,
    _maybe_disable_tls_warnings,
    _nested_first,
    _redact,
    _safe_port,
    request_json,
)

DEFAULT_SMARTZONE_API_PORT = 8443


# ─────────────────────────────────────────────────────────────────────────────
# AP / firmware / zone / patch field constants (monolith 768-816)
# ─────────────────────────────────────────────────────────────────────────────
AP_MODEL_FIELDS = [
    "model", "apModel", "modelName", "apModelName", "deviceModel", "hardwareModel",
    "productName", "productModel", "apType", "type", "apInfo.model", "apInfo.apModel",
    "device.model", "identity.model", "system.model",
]

AP_FIRMWARE_FIELDS = [
    "firmwareVersion", "firmware", "version", "softwareVersion", "software.version",
    "currentFirmwareVersion", "currentVersion", "fwVersion", "swVersion", "imageVersion",
    "activeVersion", "apVersion", "apFirmwareVersion", "firmware.version",
    "firmware.currentVersion", "apInfo.firmwareVersion", "apInfo.version",
    "device.firmwareVersion", "system.firmwareVersion",
    "configFirmwareVersion", "apConfigFirmwareVersion", "baselineVersion", "lwappFirmwareVersion",
]

AP_ZONE_ID_FIELDS = ["zoneId", "zoneUUID", "zoneUuid", "zoneID"]
AP_ZONE_NAME_FIELDS = ["zoneName", "zone", "domainName"]

AP_LAST_UPGRADE_FIELDS = [
    "lastFirmwareUpgradeAt", "lastFirmwareUpgradeTime", "lastFirmwareUpdateAt",
    "lastFirmwareUpdateTime", "firmwareUpdatedAt", "firmwareUpdatedTime",
    "firmwareUpgradeTime", "lastUpgradeTime", "lastUpgradeAt", "upgradeTime",
    "imageUpgradeTime", "lastImageUpgradeAt", "lastImageUpgradeTime", "lastFwUpgradeAt",
    "lastFwUpgradeTime", "lastFWUpgradeAt", "lastFWUpgradeTime", "fwUpgradeTime",
    "fwUpdatedAt", "softwareUpdatedAt", "firmware.lastUpgradeAt", "firmware.lastUpgradeTime",
    "firmware.updatedAt", "upgrade.lastUpgradeAt", "upgrade.lastUpgradeTime",
    "upgrade.completedAt", "imageUpgrade.completedAt", "apInfo.lastFirmwareUpgradeAt",
    "apInfo.firmwareUpdatedAt", "device.lastFirmwareUpgradeAt", "device.firmwareUpdatedAt",
    "system.lastFirmwareUpgradeAt", "system.firmwareUpdatedAt",
]

PATCH_TIME_FIELDS = [
    "completedAt", "completedTime", "endTime", "finishedAt", "updatedAt", "createdAt",
    "startTime", "releaseDate", "releasedAt", "uploadedAt", "publishDate",
]

AP_STATUS_FIELDS = [
    "status", "connectionStatus", "apStatus", "operationalStatus", "state",
    "administrativeState", "registrationState",
]
AP_CLIENT_COUNT_FIELDS = [
    "clientCount", "numClients", "numSta", "clients", "connectedClients", "staCount",
]
AP_ONLINE_VALUES = {"online", "connected", "connect", "run", "operational", "registered", "up"}
AP_FLAGGED_VALUES = {"flagged", "warning", "degraded"}
AP_OFFLINE_VALUES = {"offline", "disconnected", "disconnect", "gone", "down", "unregistered"}


# ─────────────────────────────────────────────────────────────────────────────
# URL normalization (monolith 1026-1050)
# ─────────────────────────────────────────────────────────────────────────────
def normalize_smartzone_base(
    api_host: str, default_port: int = DEFAULT_SMARTZONE_API_PORT
) -> str:
    raw = (api_host or "").strip().rstrip("/")
    if not raw:
        raise ValueError("SmartZone controller host is required.")
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    scheme = parsed.scheme or "https"
    if scheme != "https":
        raise ValueError("Only HTTPS SmartZone API endpoints are supported.")
    if parsed.username or parsed.password:
        raise ValueError("Do not include credentials in the SmartZone host field.")
    if parsed.query or parsed.fragment:
        raise ValueError("Enter the SmartZone host without query strings or fragments.")
    if not parsed.hostname:
        raise ValueError("SmartZone controller host is required.")
    path = parsed.path.rstrip("/")
    if path in {"", "/"}:
        path = "/wsg/api/public"
    elif path not in {"/wsg/api/public", "/api/public"}:
        raise ValueError(
            "Enter the SmartZone host or the public API prefix ending in /wsg/api/public."
        )
    return urlunparse(
        (
            "https",
            f"{_format_host(parsed.hostname)}:{_safe_port(parsed, default_port)}",
            path,
            "",
            "",
            "",
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Authentication / lifecycle (monolith 876-993)
# ─────────────────────────────────────────────────────────────────────────────
def authenticate_smartzone(form: Any, config: dict[str, Any]) -> ConnectionConfig:
    # Lazy import for the SSRF guard so a future refactor can swap allowlist
    # implementations without forcing a circular import.
    from ..net.allowlist import assert_host_allowed

    host = (form.get("smartzone_host") or "").strip()
    username = (form.get("smartzone_username") or "").strip()
    password = form.get("smartzone_password") or ""
    requested_version = (form.get("smartzone_api_version") or "auto").strip()
    skip_tls_verify = (form.get("smartzone_skip_tls_verify") or "").lower() in {
        "1", "true", "yes", "on",
    }

    if not host or not username or not password:
        raise ValueError("SmartZone host, username, and password are required.")

    api_base = normalize_smartzone_base(host, config["RUCKUS_SMARTZONE_PORT"])
    assert_host_allowed(urlparse(api_base).hostname or host, config)
    verify_tls = False if skip_tls_verify else config["RUCKUS_VERIFY_TLS"]
    _maybe_disable_tls_warnings(verify_tls)

    info = request_json(
        "GET", f"{api_base}/apiInfo", config, verify=verify_tls,
        debug_label="SmartZone API information",
    )
    api_versions = _as_list(info.get("apiSupportVersions"))
    api_version = (
        _latest_api_version(api_versions)
        if requested_version.lower() in {"", "auto"}
        else requested_version
    )
    if not api_version:
        raise RuckusClientError(
            "SmartZone did not return a supported public API version.",
            502, {"raw": info},
        )

    login = request_json(
        "POST", f"{api_base}/{api_version}/serviceTicket", config,
        json={"username": username, "password": password},
        verify=verify_tls, debug_label="SmartZone service ticket",
    )
    service_ticket = _first_value(login, ["serviceTicket", "ticket"])
    if not service_ticket:
        raise RuckusClientError(
            "SmartZone authenticated but did not return a service ticket.",
            502, {"raw": _redact(login)},
        )

    controller_version = _first_value(login, ["controllerVersion"]) or ""
    return ConnectionConfig(
        platform="smartzone",
        api_base=api_base,
        display_name=f"SmartZone {controller_version or _host_label(api_base)}",
        auth_token=str(service_ticket),
        verify_tls=verify_tls,
        api_version=api_version,
        controller_version=str(controller_version),
        token_expires_at=time.time() + 24 * 60 * 60,
    )


def disconnect_smartzone(
    connection: ConnectionConfig, config: dict[str, Any]
) -> None:
    """Best-effort serviceTicket logout (monolith ``disconnect_connection``).

    Renamed from ``disconnect_connection`` per Task 13 spec because this
    module is SmartZone-only; ruckus_one disconnect (no-op) and the unified
    dispatcher will live in their own modules.
    """
    if connection.platform != "smartzone" or not connection.auth_token:
        return
    try:
        request_json(
            "DELETE",
            f"{connection.api_base}/{connection.api_version}/serviceTicket",
            config,
            params={"serviceTicket": connection.auth_token},
            verify=connection.verify_tls,
            headers={"Accept": "application/json"},
            debug_label="SmartZone service ticket logout",
            expected_status={200, 202, 204},
        )
    except RuckusClientError:
        pass


def _token_valid(connection: ConnectionConfig) -> None:
    if connection.token_expires_at and connection.token_expires_at <= time.time():
        raise RuckusClientError(
            "The temporary platform token expired. Please reconnect.", 401
        )


def fetch_inventory(
    connection: ConnectionConfig, config: dict[str, Any]
) -> dict[str, Any]:
    """SmartZone inventory entry point.

    The monolith ``fetch_inventory`` branches on ``connection.platform`` to
    dispatch to SmartZone or Ruckus One. Since this module is SmartZone-only,
    the dispatch is inlined: we still validate the platform to give a clear
    error if someone hands us a Ruckus One connection by mistake.
    """
    _token_valid(connection)
    if connection.platform != "smartzone":
        raise RuckusClientError("Unsupported RUCKUS management platform.", 400)
    return _fetch_smartzone_inventory(connection, config)


# ─────────────────────────────────────────────────────────────────────────────
# Inventory + operational (monolith 1098-1278)
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_smartzone_inventory(
    connection: ConnectionConfig, config: dict[str, Any]
) -> dict[str, Any]:
    """Build inventory from the bulk POST /query/ap call.

    The query API returns every AP (model/firmware/status/zone) in a few paged
    requests. This avoids the per-AP GET /aps/{mac} detail walk that, on large
    fabrics, can outlive the SmartZone serviceTicket and surface as HTTP 401.
    Zone firmware catalogs (a handful of calls) are still fetched for posture.
    """
    debug: list[dict[str, Any]] = []
    try:
        zones = smartzone_paged_get(connection, "rkszones", config, debug=debug)
    except RuckusClientError as exc:
        debug.append({"label": "GET /rkszones", "status": exc.status_code})
        zones = []

    zone_map: dict[str, dict[str, Any]] = {}
    zone_records: list[dict[str, Any]] = []
    patches: list[dict[str, Any]] = []

    for zone in zones:
        zone_id = str(_first_value(zone, ["id", "zoneId"]) or "")
        if not zone_id:
            continue
        zone_detail = smartzone_optional_get(
            connection, f"rkszones/{quote(zone_id)}", config, debug=debug
        )
        zone_name = str(
            _first_value(zone_detail or zone, ["name", "serviceName"]) or zone_id
        )
        zone_firmware = str(
            _first_value(zone_detail or {}, ["version", "firmwareVersion"]) or ""
        )
        firmware_catalog = smartzone_optional_get(
            connection, f"rkszones/{quote(zone_id)}/apFirmware", config, debug=debug
        )
        catalog_items = _extract_items(firmware_catalog)
        latest_supported = _latest_firmware(
            [
                str(_first_value(item, ["firmwareVersion", "version"]))
                for item in catalog_items
                if item.get("supported") is not False
                and _first_value(item, ["firmwareVersion", "version"])
            ]
        )
        zone_map[zone_id] = {
            "name": zone_name,
            "firmware": zone_firmware,
            "items": catalog_items,
            "latest": latest_supported,
            "details": _build_patching_details(
                zone_id, zone_name, zone_firmware, latest_supported, catalog_items
            ),
        }
        zone_records.append(
            {
                "id": zone_id,
                "name": zone_name,
                "firmware_version": zone_firmware,
                "latest_supported_firmware": latest_supported,
                "ap_count": 0,
            }
        )
        patches.extend(
            _firmware_catalog_to_patch_records(
                zone_id, zone_name, zone_firmware, catalog_items
            )
        )

    ap_rows = smartzone_query_paged(
        connection, "query/ap", config, debug, optional=True
    )
    used_query = bool(ap_rows)
    if not ap_rows:
        ap_rows = []
        for zone_id in zone_map:
            zone_aps = smartzone_paged_get(
                connection, "aps", config, params={"zoneId": zone_id}, debug=debug
            )
            for ap in zone_aps:
                ap.setdefault("zoneId", zone_id)
            ap_rows.extend(zone_aps)

    detail_budget = (
        int(config["RUCKUS_MAX_DETAIL_REQUESTS"])
        if (config["RUCKUS_FETCH_AP_DETAILS"] and not used_query)
        else 0
    )
    zone_counts: dict[str, int] = {}
    assets: list[dict[str, Any]] = []

    for ap in ap_rows:
        merged_ap = dict(ap)
        zone_id = str(_first_value(merged_ap, AP_ZONE_ID_FIELDS) or "")
        zone = zone_map.get(zone_id, {})
        zone_name = zone.get("name") or str(
            _first_value(merged_ap, AP_ZONE_NAME_FIELDS) or "Unknown zone"
        )
        zone_firmware = zone.get("firmware", "")
        catalog_items = zone.get("items", [])
        latest_supported = zone.get("latest", "")
        zone_patching_details = zone.get("details") or _build_patching_details(
            zone_id, zone_name, zone_firmware, latest_supported, catalog_items
        )

        mac = _first_value(merged_ap, ["mac", "apMac", "macAddress"])
        if detail_budget > 0 and _smartzone_ap_needs_detail(merged_ap) and mac:
            detail_budget -= 1
            details = smartzone_optional_get(
                connection,
                f"aps/{quote(str(mac), safe='')}",
                config,
                debug=debug,
            )
            if isinstance(details, dict):
                merged_ap.update(details)

        firmware = str(_first_present(merged_ap, AP_FIRMWARE_FIELDS) or zone_firmware)
        model = str(_first_present(merged_ap, AP_MODEL_FIELDS) or "Not reported")
        last_upgrade = _first_present(merged_ap, AP_LAST_UPGRADE_FIELDS)
        zone_counts[zone_id] = zone_counts.get(zone_id, 0) + 1
        assets.append(
            {
                "id": str(
                    _first_value(merged_ap, ["serial", "serialNumber", "mac", "apMac"])
                    or ""
                ),
                "platform": "SmartZone",
                "name": str(
                    _first_value(merged_ap, ["name", "apName", "deviceName"]) or "-"
                ),
                "site": zone_name,
                "zone_id": zone_id,
                "serial": str(
                    _first_value(merged_ap, ["serial", "serialNumber"]) or ""
                ),
                "mac": str(
                    _first_value(merged_ap, ["mac", "apMac", "macAddress"]) or ""
                ),
                "ip": str(
                    _nested_first(
                        merged_ap,
                        [["network", "ip"], ["ip"], ["ipAddress"], ["externalIp"]],
                    )
                    or ""
                ),
                "model": model,
                "firmware_version": firmware or "Not reported",
                "last_upgrade_at": _format_time(last_upgrade) or "Not reported",
                "patch": _build_patch_posture(firmware, latest_supported, catalog_items),
                "patching_details": zone_patching_details,
                "raw": _redact(merged_ap),
            }
        )

    for record in zone_records:
        record["ap_count"] = zone_counts.get(record["id"], 0)

    return {
        "connection": _connection_payload(connection),
        "zones": zone_records,
        "assets": assets,
        "patches": patches,
        "debug": debug,
    }


def _fetch_smartzone_operational(
    connection: ConnectionConfig, config: dict[str, Any]
) -> dict[str, Any]:
    debug: list[dict[str, Any]] = []

    aps = smartzone_query_paged(
        connection, "query/ap", config, debug, optional=True
    )
    if not aps:
        aps = smartzone_paged_get(connection, "aps", config, debug=debug)
    ap_stats = _aggregate_ap_status(aps)

    client_total = ap_stats["clients"]
    client_query = smartzone_post(
        connection, "query/client", config, {"limit": 1}, debug, optional=True
    )
    if isinstance(client_query, dict):
        explicit = _coerce_int(
            _first_value(client_query, ["totalCount", "total"]), -1
        )
        if explicit >= 0:
            client_total = explicit

    alarms = smartzone_alarm_summary(connection, config, debug)

    # Switch health lives in its own module (clients/switchm.py) because the
    # /switchm/api surface has a different version line and URL prefix.
    # Lazy import to keep the smartzone/switchm split clean -- nothing in the
    # rest of this module touches the Switch Manager API.
    from .switchm import fetch_switches

    switches = fetch_switches(connection, config, debug)

    return {
        "connection": _connection_payload(connection),
        "status": "ok",
        "ap": ap_stats,
        "clients": {"total": client_total},
        "alarms": alarms,
        "switches": switches,
        "generated_at": _format_now(),
        "debug": debug,
    }


# ─────────────────────────────────────────────────────────────────────────────
# AP status aggregation (monolith 1360-1393)
# ─────────────────────────────────────────────────────────────────────────────
def _empty_ap_stats() -> dict[str, Any]:
    return {
        "total": 0, "online": 0, "flagged": 0, "offline": 0, "other": 0,
        "online_up": 0, "online_pct": None, "clients": 0,
    }


def _aggregate_ap_status(aps: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(aps)
    online = flagged = offline = other = clients = 0
    for ap in aps:
        status = str(_first_present(ap, AP_STATUS_FIELDS) or "").strip().lower()
        clients += _coerce_int(_first_present(ap, AP_CLIENT_COUNT_FIELDS), 0)
        if status in AP_ONLINE_VALUES:
            online += 1
        elif status in AP_FLAGGED_VALUES:
            flagged += 1
        elif status in AP_OFFLINE_VALUES:
            offline += 1
        else:
            other += 1
    online_up = online + flagged
    online_pct = round(online_up / total * 100) if total else None
    return {
        "total": total,
        "online": online,
        "flagged": flagged,
        "offline": offline,
        "other": other,
        "online_up": online_up,
        "online_pct": online_pct,
        "clients": clients,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Alarms (monolith 1415-1438)
# ─────────────────────────────────────────────────────────────────────────────
def smartzone_alarm_summary(
    connection: ConnectionConfig,
    config: dict[str, Any],
    debug: list[dict[str, Any]],
) -> dict[str, Any] | None:
    data = smartzone_post(
        connection, "alert/alarmSummary", config, {}, debug, optional=True
    )
    if not isinstance(data, dict):
        return None
    source = data.get("summary") if isinstance(data.get("summary"), dict) else data

    def count(*names: str) -> int:
        return _coerce_int(_first_value(source, list(names)), 0)

    critical = count("critical", "Critical", "numCritical", "criticalCount", "criticalAlarmCount")
    major = count("major", "Major", "numMajor", "majorCount", "majorAlarmCount")
    minor = count("minor", "Minor", "numMinor", "minorCount", "minorAlarmCount")
    warning = count("warning", "Warning", "numWarning", "warningCount", "warningAlarmCount")
    total = count("total", "Total", "totalCount", "numTotal") or (
        critical + major + minor + warning
    )
    return {
        "critical": critical,
        "major": major,
        "minor": minor,
        "warning": warning,
        "total": total,
    }


# ─────────────────────────────────────────────────────────────────────────────
# API version helpers (monolith 2209-2228)
#
# ``_api_version_fallbacks`` lives in clients/switchm.py because its only
# consumer is the Switch Manager fetch (its API version line is distinct from
# the wireless public API version, so the fallback walk only makes sense on
# the switchm side).
# ─────────────────────────────────────────────────────────────────────────────
def _latest_api_version(versions: list[Any]) -> str:
    text_versions = [str(v) for v in versions if str(v).startswith("v")]
    if not text_versions:
        return ""
    return sorted(text_versions, key=_api_version_key)[-1]


def _api_version_key(version: str) -> tuple[int, ...]:
    return tuple(_coerce_int(part, 0) for part in version.removeprefix("v").split("_"))


def _latest_firmware(versions: list[str]) -> str:
    clean = [v for v in versions if v and v != "None"]
    return sorted(clean, key=_version_key)[-1] if clean else ""


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(
        _coerce_int(part, 0) for part in str(version).replace("-", ".").split(".")
    )


# ─────────────────────────────────────────────────────────────────────────────
# Paged / GET / POST helpers (monolith 1834-1931)
# ─────────────────────────────────────────────────────────────────────────────
def smartzone_paged_get(
    connection: ConnectionConfig,
    path: str,
    config: dict[str, Any],
    *,
    params: dict[str, Any] | None = None,
    debug: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    page_size = min(int(config["RUCKUS_PAGE_LIMIT"]), 1000)
    index = 0
    records: list[dict[str, Any]] = []
    while True:
        page_params = {"index": index, "listSize": page_size, **(params or {})}
        data = smartzone_get(connection, path, config, page_params, debug)
        items = _extract_items(data)
        records.extend([item for item in items if isinstance(item, dict)])
        if not isinstance(data, dict) or not data.get("hasMore") or not items:
            break
        index += len(items)
    return records


def smartzone_get(
    connection: ConnectionConfig,
    path: str,
    config: dict[str, Any],
    params: dict[str, Any] | None,
    debug: list[dict[str, Any]],
) -> Any:
    verify_tls = connection.verify_tls
    _maybe_disable_tls_warnings(verify_tls)
    # The SmartZone public API authenticates every call with a serviceTicket
    # query parameter -- it has no Authorization-header equivalent. The ticket
    # is a short-lived secret, so every debug/log path runs the URL through
    # _safe_url() (inside request_json) which strips the query string.
    request_params = {"serviceTicket": connection.auth_token, **(params or {})}
    url = f"{connection.api_base}/{connection.api_version}/{path.lstrip('/')}"
    result = request_json(
        "GET", url, config, params=request_params, verify=verify_tls,
        headers={"Accept": "application/json"},
        debug_label=f"SmartZone {path}",
    )
    debug.append({"label": f"GET /{path}", "status": "ok"})
    return result


def smartzone_optional_get(
    connection: ConnectionConfig,
    path: str,
    config: dict[str, Any],
    *,
    debug: list[dict[str, Any]],
) -> Any | None:
    try:
        return smartzone_get(connection, path, config, None, debug)
    except RuckusClientError as exc:
        debug.append({"label": f"GET /{path}", "status": exc.status_code})
        return None


def smartzone_post(
    connection: ConnectionConfig,
    path: str,
    config: dict[str, Any],
    body: dict[str, Any] | None,
    debug: list[dict[str, Any]],
    *,
    optional: bool = False,
) -> Any | None:
    verify_tls = connection.verify_tls
    _maybe_disable_tls_warnings(verify_tls)
    url = f"{connection.api_base}/{connection.api_version}/{path.lstrip('/')}"
    try:
        result = request_json(
            "POST", url, config, params={"serviceTicket": connection.auth_token},
            json=body or {}, verify=verify_tls,
            headers={"Accept": "application/json"},
            debug_label=f"SmartZone {path}",
        )
        debug.append({"label": f"POST /{path}", "status": "ok"})
        return result
    except RuckusClientError as exc:
        debug.append({"label": f"POST /{path}", "status": exc.status_code})
        if optional:
            return None
        raise


def smartzone_query_paged(
    connection: ConnectionConfig,
    path: str,
    config: dict[str, Any],
    debug: list[dict[str, Any]],
    *,
    body: dict[str, Any] | None = None,
    optional: bool = True,
) -> list[dict[str, Any]]:
    limit = min(int(config["RUCKUS_PAGE_LIMIT"]), 1000)
    page = 1
    records: list[dict[str, Any]] = []
    while True:
        payload = {"page": page, "limit": limit, **(body or {})}
        data = smartzone_post(connection, path, config, payload, debug, optional=optional)
        if data is None:
            break
        items = _extract_items(data)
        records.extend([item for item in items if isinstance(item, dict)])
        total = _coerce_int(
            _first_value(data, ["totalCount"]) if isinstance(data, dict) else None, 0
        )
        has_more_key = isinstance(data, dict) and "hasMore" in data
        has_more = bool(data.get("hasMore")) if isinstance(data, dict) else False
        if (
            not items
            or len(items) < limit
            or (total and page * limit >= total)
            or (has_more_key and not has_more)
        ):
            break
        page += 1
    return records


# ─────────────────────────────────────────────────────────────────────────────
# Patch posture / firmware catalog (monolith 1989-2118)
# ─────────────────────────────────────────────────────────────────────────────
def _build_patch_posture(
    current: str, latest_supported: str, catalog_items: list[dict[str, Any]]
) -> dict[str, Any]:
    current = "" if current == "Not reported" else current
    unsupported_current = any(
        str(_first_value(item, ["firmwareVersion", "version"])) == current
        and item.get("supported") is False
        for item in catalog_items
    )
    if not current and catalog_items:
        status = "catalog_context"
        summary = "AP firmware was not reported; SmartZone zone firmware catalog is available for review."
    elif not current:
        status = "not_reported"
        summary = "Firmware version was not reported by SmartZone for this AP."
    elif not catalog_items:
        status = "catalog_unavailable"
        summary = "SmartZone did not return a firmware catalog for this zone."
    elif unsupported_current:
        status = "unsupported"
        summary = "Current firmware is marked unsupported in the zone firmware catalog."
    elif latest_supported and _version_key(latest_supported) > _version_key(current):
        status = "update_available"
        summary = f"Supported firmware {latest_supported} is available."
    elif latest_supported and current:
        status = "current"
        summary = "Current firmware is at the latest supported catalog version."
    else:
        status = "no_supported_versions"
        summary = "Firmware catalog did not include supported upgrade versions."
    return {
        "status": status,
        "latest_supported": latest_supported,
        "summary": summary,
        "details": {
            "available_versions": [
                _catalog_item_to_version_record(item, current)
                for item in catalog_items[:20]
            ]
        },
    }


def _build_patching_details(
    zone_id: str,
    zone_name: str,
    current_version: str,
    latest_supported: str,
    catalog_items: list[dict[str, Any]],
) -> dict[str, Any]:
    versions = [
        _catalog_item_to_version_record(item, current_version)
        for item in catalog_items[:20]
        if _first_value(item, ["firmwareVersion", "version"])
    ]
    current_versions = [
        str(version["firmware_version"])
        for version in versions
        if version.get("current") and version.get("firmware_version")
    ]
    display_current = current_version or ", ".join(current_versions)
    if current_versions and latest_supported:
        summary = (
            f"Zone catalog current {', '.join(current_versions)}; "
            f"latest supported {latest_supported}."
        )
    elif current_versions:
        summary = f"Zone catalog current {', '.join(current_versions)}."
    elif latest_supported:
        summary = f"Latest supported zone catalog version {latest_supported}."
    elif versions:
        summary = "Zone firmware catalog returned versions but no supported latest marker."
    else:
        summary = "SmartZone did not return patching catalog details for this zone."
    return {
        "source": "SmartZone firmware catalog",
        "zone_id": zone_id,
        "site": zone_name,
        "summary": summary,
        "current_firmware": display_current,
        "latest_supported": latest_supported,
        "versions": versions,
    }


def _firmware_catalog_to_patch_records(
    zone_id: str,
    zone_name: str,
    current_version: str,
    catalog_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    for item in catalog_items:
        version_record = _catalog_item_to_version_record(item, current_version)
        records.append(
            {
                "source": "SmartZone firmware catalog",
                "zone_id": zone_id,
                "site": zone_name,
                "firmware_version": version_record["firmware_version"],
                "current": version_record["current"],
                "supported": version_record["supported"],
                "completed_at": "",
                "released_at": version_record["released_at"],
                "reported_at": version_record["reported_at"],
                "details": version_record["unsupported_models"],
            }
        )
    return records


def _catalog_item_to_version_record(
    item: dict[str, Any], current_version: str
) -> dict[str, Any]:
    firmware_version = _first_value(item, ["firmwareVersion", "version"])
    reported_at = _format_time(_first_present(item, PATCH_TIME_FIELDS))
    return {
        "firmware_version": firmware_version,
        "current": _catalog_item_is_current(item, current_version),
        "supported": item.get("supported"),
        "released_at": reported_at,
        "reported_at": reported_at,
        "unsupported_models": item.get("unsupportedApModelSummary", []),
    }


def _catalog_item_is_current(item: dict[str, Any], current_version: str) -> bool:
    firmware_version = str(_first_value(item, ["firmwareVersion", "version"]) or "")
    if current_version and firmware_version == current_version:
        return True
    for name in [
        "current", "isCurrent", "active", "isActive", "selected", "isSelected",
        "inUse", "zoneDefault", "apDefault", "activeFirmware",
    ]:
        if _truthy_flag(_first_value(item, [name])):
            return True
    return False


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "current", "active", "selected", "in-use"}


# ─────────────────────────────────────────────────────────────────────────────
# Activity helpers (monolith 2121-2154) live in ``clients/ruckus_one.py`` --
# they only serve the RUCKUS One inventory builder; the monolith colocated
# them with the SmartZone helpers, but Task 15 relocated them.
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Connection payload + AP detail decision (monolith 2157-2189)
# ─────────────────────────────────────────────────────────────────────────────
def _connection_payload(connection: ConnectionConfig) -> dict[str, Any]:
    return {
        "platform": connection.platform,
        "display_name": connection.display_name,
        "api_base": connection.api_base,
        "api_version": connection.api_version,
        "controller_version": connection.controller_version,
        "tenant_id": connection.tenant_id,
        "connected_at": _format_time(connection.created_at),
        "token_expires_at": _format_time(connection.token_expires_at),
    }


def _smartzone_ap_needs_detail(ap: dict[str, Any]) -> bool:
    return not all(
        [
            _first_present(ap, AP_MODEL_FIELDS),
            _first_present(ap, AP_FIRMWARE_FIELDS),
            _first_present(ap, AP_LAST_UPGRADE_FIELDS),
        ]
    )
