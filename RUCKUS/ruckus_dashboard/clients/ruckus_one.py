"""RUCKUS One (cloud-managed) client.

Ported from the monolith ``RUCKUS/ruckus_dashboard.py``. This module owns the
RUCKUS One OAuth client-credentials flow, region/host normalization, the
``venues/...`` query helpers, and the firmware-activity helpers that surface
patch posture in the inventory view.

Source line ranges (monolith):

* ``RUCKUS_ONE_REGIONS``                          -- 735-743
* ``RUCKUS_ONE_FIELDS`` / ``RUCKUS_ONE_OPERATIONAL_FIELDS``
                                                  -- 745-766
* ``authenticate_ruckus_one``                     -- 933-973
* ``normalize_ruckus_one_base``                   -- 1053-1075
* ``_fetch_ruckus_one_inventory``                 -- 1280-1338
* ``_fetch_ruckus_one_operational``               -- 1340-1358
* ``_ruckus_one_query``                           -- 1933-1950
* ``_fetch_ruckus_one_activities``                -- 1952-1969
* ``_ruckus_one_request``                         -- 1971-1987
* ``_ruckus_one_auth_base``                       -- 2284-2293
* ``_count_by_site``                              -- 2334-2335 (kept inline; one-liner with a single caller)

Activity helpers ``_activity_to_patch_record`` / ``_activity_summary`` /
``_match_activity`` (monolith 2121-2154) were temporarily parked in
``clients/smartzone.py`` during Task 13 because the monolith colocated them
with the SmartZone helpers. Task 15 relocates them here, since their only
caller is the RUCKUS One inventory builder.

``_aggregate_ap_status`` and ``_connection_payload`` are imported from
``clients.smartzone`` -- they are platform-agnostic AP/connection shapers
that happen to live in that module today; once Task 16+ refactors the
client surface, they can move to a shared module.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

from ..auth.session_store import ConnectionConfig
from .base import (
    RuckusClientError,
    _coerce_int,
    _extract_items,
    _first_present,
    _first_value,
    _format_host,
    _format_now,
    _format_time,
    _host_label,
    _nested_first,
    _redact,
    request_json,
)


# ─────────────────────────────────────────────────────────────────────────────
# Region map + field projections (monolith 735-766)
# ─────────────────────────────────────────────────────────────────────────────
RUCKUS_ONE_REGIONS = {
    "na": "https://api.ruckus.cloud",
    "north-america": "https://api.ruckus.cloud",
    "us": "https://api.ruckus.cloud",
    "eu": "https://api.eu.ruckus.cloud",
    "europe": "https://api.eu.ruckus.cloud",
    "asia": "https://api.asia.ruckus.cloud",
    "apac": "https://api.asia.ruckus.cloud",
}

RUCKUS_ONE_FIELDS = [
    "serialNumber",
    "venueId",
    "model",
    "macAddress",
    "firmwareVersion",
    "name",
    "networkStatus.ipAddress",
    "lastFirmwareUpgradeAt",
    "lastFirmwareUpdateAt",
    "firmwareUpdatedAt",
]

RUCKUS_ONE_OPERATIONAL_FIELDS = [
    "serialNumber",
    "name",
    "venueId",
    "status",
    "apStatus",
    "clientCount",
    "model",
]


# ─────────────────────────────────────────────────────────────────────────────
# URL normalization (monolith 1053-1075 + 2284-2293)
# ─────────────────────────────────────────────────────────────────────────────
def normalize_ruckus_one_base(region_or_host: str) -> str:
    value = (region_or_host or "na").strip()
    mapped = RUCKUS_ONE_REGIONS.get(value.lower())
    if mapped:
        return mapped
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if parsed.scheme != "https":
        raise ValueError("Only HTTPS RUCKUS One API hosts are supported.")
    if parsed.username or parsed.password:
        raise ValueError("Do not include credentials in the RUCKUS One host field.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Enter only the RUCKUS One region host, not a URL path.")
    if not parsed.hostname:
        raise ValueError("RUCKUS One region host is required.")
    host = parsed.hostname
    if host in {"ruckus.cloud", "eu.ruckus.cloud", "asia.ruckus.cloud"}:
        host = f"api.{host}"
    elif not host.startswith("api."):
        host = f"api.{host}"
    netloc = _format_host(host)
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(("https", netloc, "", "", "", ""))


def _ruckus_one_auth_base(api_base: str) -> str:
    parsed = urlparse(api_base)
    host = parsed.hostname or ""
    if host.startswith("api."):
        host = host[4:]
    netloc = _format_host(host)
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(("https", netloc, "", "", "", ""))


# ─────────────────────────────────────────────────────────────────────────────
# Authentication (monolith 933-973)
# ─────────────────────────────────────────────────────────────────────────────
def authenticate_ruckus_one(form: Any, config: dict[str, Any]) -> ConnectionConfig:
    # Lazy import to mirror smartzone.authenticate_smartzone and avoid a
    # circular import via base.request_json -> net.allowlist.
    from ..net.allowlist import assert_host_allowed

    tenant_id = (form.get("tenant_id") or "").strip()
    client_id = (form.get("client_id") or "").strip()
    client_secret = form.get("client_secret") or ""
    region = (form.get("ruckus_one_region") or "na").strip()
    custom_region = (form.get("ruckus_one_custom_host") or "").strip()

    if not tenant_id or not client_id or not client_secret:
        raise ValueError("Tenant ID, client ID, and client secret are required.")

    api_base = normalize_ruckus_one_base(custom_region if region == "custom" else region)
    assert_host_allowed(urlparse(api_base).hostname or "", config)
    token_url = f"{_ruckus_one_auth_base(api_base)}/oauth2/token/{quote(tenant_id)}"

    token_response = request_json(
        "POST", token_url, config,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        verify=True, debug_label="RUCKUS One OAuth token",
    )
    access_token = _first_value(token_response, ["access_token", "accessToken"])
    if not access_token:
        raise RuckusClientError(
            "RUCKUS One did not return an OAuth access token.",
            502, {"raw": _redact(token_response)},
        )

    expires_in = _coerce_int(_first_value(token_response, ["expires_in", "expiresIn"]), 3600)
    return ConnectionConfig(
        platform="ruckus_one",
        api_base=api_base,
        display_name=f"RUCKUS One {_host_label(api_base)}",
        auth_token=str(access_token),
        verify_tls=True,
        tenant_id=tenant_id,
        token_expires_at=time.time() + max(60, expires_in - 30),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Inventory + operational (monolith 1280-1358)
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_ruckus_one_inventory(
    connection: ConnectionConfig, config: dict[str, Any]
) -> dict[str, Any]:
    # Lazy import: _connection_payload is platform-agnostic but currently
    # lives in smartzone.py. Once Task 16+ rationalises the client surface
    # this can move to a shared module.
    from .smartzone import _connection_payload

    debug: list[dict[str, Any]] = []
    venues = _ruckus_one_query(connection, "venues/query", config, ["id", "name"], debug)
    venue_names = {
        str(_first_value(venue, ["id", "venueId"])): str(
            _first_value(venue, ["name", "venueName"]) or "Unknown venue"
        )
        for venue in venues
    }
    ap_records = _ruckus_one_query(connection, "venues/aps/query", config, RUCKUS_ONE_FIELDS, debug)
    activities = _fetch_ruckus_one_activities(connection, config, debug)
    assets: list[dict[str, Any]] = []

    for ap in ap_records:
        venue_id = str(_first_value(ap, ["venueId"]) or "")
        serial = str(_first_value(ap, ["serialNumber", "serial"]) or "")
        firmware = str(_first_value(ap, ["firmwareVersion", "firmware"]) or "")
        activity = _match_activity(activities, [serial, _first_value(ap, ["name"])])
        last_upgrade = _first_value(
            ap, ["lastFirmwareUpgradeAt", "lastFirmwareUpdateAt", "firmwareUpdatedAt", "updatedAt"]
        ) or _first_value(activity or {}, ["completedAt", "endTime", "updatedAt", "createdAt"])

        assets.append(
            {
                "id": serial or str(_first_value(ap, ["macAddress", "mac"]) or ""),
                "platform": "RUCKUS One",
                "name": str(_first_value(ap, ["name"]) or "-"),
                "site": venue_names.get(venue_id, venue_id or "Unassigned"),
                "zone_id": venue_id,
                "serial": serial,
                "mac": str(_first_value(ap, ["macAddress", "mac"]) or ""),
                "ip": str(_nested_first(ap, [["networkStatus", "ipAddress"], ["ipAddress"]]) or ""),
                "model": str(_first_value(ap, ["model"]) or "Unknown"),
                "firmware_version": firmware,
                "last_upgrade_at": _format_time(last_upgrade),
                "patch": {
                    "status": "inventory",
                    "latest_supported": "",
                    "summary": "Firmware version reported by RUCKUS One inventory.",
                    "details": _activity_summary(activity),
                },
                "raw": _redact(ap),
            }
        )

    patches = [_activity_to_patch_record(activity) for activity in activities]
    return {
        "connection": _connection_payload(connection),
        "zones": [
            {"id": venue_id, "name": name, "ap_count": _count_by_site(assets, name)}
            for venue_id, name in venue_names.items()
        ],
        "assets": assets,
        "patches": [patch for patch in patches if patch],
        "debug": debug,
    }


def _fetch_ruckus_one_operational(
    connection: ConnectionConfig, config: dict[str, Any]
) -> dict[str, Any]:
    from .smartzone import _aggregate_ap_status, _connection_payload

    debug: list[dict[str, Any]] = []
    aps = _ruckus_one_query(
        connection, "venues/aps/query", config, RUCKUS_ONE_OPERATIONAL_FIELDS, debug
    )
    ap_stats = _aggregate_ap_status(aps)
    return {
        "connection": _connection_payload(connection),
        "status": "ok",
        "ap": ap_stats,
        "clients": {"total": ap_stats["clients"]},
        "alarms": None,
        "switches": None,
        "generated_at": _format_now(),
        "debug": debug,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Paged query + activities + low-level request (monolith 1933-1987)
# ─────────────────────────────────────────────────────────────────────────────
def _ruckus_one_query(
    connection: ConnectionConfig, path: str, config: dict[str, Any],
    fields: list[str], debug: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    page_size = int(config["RUCKUS_PAGE_LIMIT"])
    page = 1
    records: list[dict[str, Any]] = []
    while True:
        payload = {"page": page, "pageSize": page_size, "fields": fields, "sortOrder": "ASC"}
        data = _ruckus_one_request(connection, "POST", path, config, debug, json=payload)
        items = _extract_items(data)
        records.extend([item for item in items if isinstance(item, dict)])
        total_pages = _coerce_int(_first_value(data, ["totalPages"]), 0)
        if not items or (total_pages and page >= total_pages) or len(items) < page_size:
            break
        page += 1
    return records


def _fetch_ruckus_one_activities(
    connection: ConnectionConfig, config: dict[str, Any], debug: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payload = {
        "page": 1, "pageSize": 100,
        "fields": ["id", "name", "type", "status", "description", "createdAt", "completedAt", "updatedAt"],
        "sortField": "createdAt", "sortOrder": "DESC",
    }
    try:
        data = _ruckus_one_request(connection, "POST", "activities/query", config, debug, json=payload)
    except RuckusClientError as exc:
        debug.append({"label": "POST /activities/query", "status": exc.status_code})
        return []
    return [
        item for item in _extract_items(data)
        if isinstance(item, dict) and "firmware" in str(item).lower()
    ]


def _ruckus_one_request(
    connection: ConnectionConfig, method: str, path: str,
    config: dict[str, Any], debug: list[dict[str, Any]], **kwargs: Any,
) -> Any:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {connection.auth_token}",
        **kwargs.pop("headers", {}),
    }
    url = f"{connection.api_base}/{path.lstrip('/')}"
    data = request_json(
        method, url, config, headers=headers, verify=True,
        debug_label=f"RUCKUS One {path}", **kwargs,
    )
    debug.append({"label": f"{method} /{path}", "status": "ok"})
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Activity helpers (monolith 2121-2154; relocated from clients/smartzone.py)
# ─────────────────────────────────────────────────────────────────────────────
def _activity_to_patch_record(activity: dict[str, Any]) -> dict[str, Any]:
    completed_at = _format_time(
        _first_present(activity, ["completedAt", "endTime", "updatedAt", "createdAt"])
    )
    return {
        "source": "RUCKUS One activity",
        "site": "",
        "firmware_version": "",
        "current": False,
        "supported": None,
        "completed_at": completed_at,
        "reported_at": completed_at,
        "details": _redact(activity),
    }


def _activity_summary(activity: dict[str, Any] | None) -> dict[str, Any]:
    if not activity:
        return {"last_activity": "No matching firmware activity found."}
    return {
        "last_activity": _first_value(activity, ["name", "description", "type"]) or "",
        "status": _first_value(activity, ["status"]) or "",
        "completed_at": _format_time(
            _first_present(activity, ["completedAt", "endTime", "updatedAt", "createdAt"])
        ),
    }


def _match_activity(
    activities: list[dict[str, Any]], identifiers: list[Any]
) -> dict[str, Any] | None:
    needles = [str(value).lower() for value in identifiers if value]
    if not needles:
        return activities[0] if activities else None
    for activity in activities:
        haystack = str(activity).lower()
        if any(needle in haystack for needle in needles):
            return activity
    return activities[0] if activities else None


# ─────────────────────────────────────────────────────────────────────────────
# Local helper (monolith 2334-2335 _count_by_site; kept inline -- one caller)
# ─────────────────────────────────────────────────────────────────────────────
def _count_by_site(assets: list[dict[str, Any]], site: str) -> int:
    return sum(1 for asset in assets if asset.get("site") == site)
