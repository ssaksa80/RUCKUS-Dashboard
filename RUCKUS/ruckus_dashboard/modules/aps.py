"""Access Points — primary wireless module."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_query_paged

POLL_SECONDS = 30
ICON = "\U0001F4F6"  # signal-bars emoji

ONLINE_VALUES = {"online", "connected", "run", "operational", "registered", "up"}
OFFLINE_VALUES = {"offline", "disconnected", "down", "unregistered", "gone"}
FLAGGED_VALUES = {"flagged", "warning", "degraded"}


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    # Paginate: SmartZone caps a single page at 500, fabrics often exceed it.
    rows = smartzone_query_paged(ctx.connection, "query/ap", ctx.config, [],
                                 body=_filter_body(ctx.filters))
    rssi_by_ap = _client_rssi_by_ap(ctx)
    items = [_normalize(r) for r in rows]
    for i in items:
        key = (str(i.get("mac") or "").lower(), str(i.get("name") or "").lower())
        i["signal_db"] = rssi_by_ap.get(key[0]) or rssi_by_ap.get(key[1])
    return {"items": items, "raw_count": len(rows)}


def _client_rssi_by_ap(ctx: FetcherContext) -> dict[str, int]:
    """Realtime per-AP average client signal (dBm) — refreshed every poll."""
    try:
        rows = smartzone_query_paged(ctx.connection, "query/client", ctx.config, [])
    except Exception:  # noqa: BLE001
        return {}
    sums: dict[str, list[int]] = {}
    for c in rows or []:
        rssi = int(c.get("rssi") or 0)
        if not rssi:
            continue
        for key in (c.get("apMac"), c.get("apName")):
            if key:
                sums.setdefault(str(key).lower(), []).append(rssi)
    return {k: round(sum(v) / len(v)) for k, v in sums.items() if v}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    online = sum(1 for i in items if i.get("status") == "online")
    offline = sum(1 for i in items if i.get("status") == "offline")
    flagged = sum(1 for i in items if i.get("status") == "flagged")
    clients = sum(int(i.get("clients") or 0) for i in items)
    return {"total": len(items), "online": online,
            "offline": offline, "flagged": flagged, "clients": clients}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    from ..clients.smartzone import smartzone_get
    try:
        # smartzone_get signature: (connection, path, config, params, debug)
        detail = smartzone_get(ctx.connection,
                               f"aps/{entity_id}/operational/summary",
                               ctx.config, None, [])
    except Exception as exc:
        return {"identity": {"id": entity_id}, "error": str(exc)}
    return {"identity": _normalize(detail or {}), "raw": detail}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}


def _filter_body(filters: dict | None) -> dict:
    """Filter portion of a /query/ap body (page/limit are added by the pager).

    Delegates to smartzone_query_body so push-down is token-driven: it honors
    both the resolved-filter tokens under ``__server`` and the legacy ``zone``
    key. Page/limit are stripped here because the pager owns them."""
    from ..clients.smartzone import smartzone_query_body
    body = smartzone_query_body(filters or {})
    return {"filters": body["filters"]} if "filters" in body else {}


def _normalize(row: dict) -> dict:
    raw_status = str(row.get("status") or "").lower()
    if raw_status in ONLINE_VALUES:
        status = "online"
    elif raw_status in OFFLINE_VALUES:
        status = "offline"
    elif raw_status in FLAGGED_VALUES:
        status = "flagged"
    else:
        status = raw_status or "unknown"
    return {
        "id": row.get("apMac"),
        "name": row.get("deviceName") or row.get("name") or "-",
        "model": row.get("model"),
        "zone": row.get("zoneName"),
        "zone_id": row.get("zoneId"),
        "status": status,
        "clients": int(row.get("numClients") or 0),
        "fw": row.get("firmwareVersion") or row.get("firmware"),
        "ip": row.get("ip") or row.get("ipAddress"),
        "mac": row.get("apMac"),
        "last_seen": row.get("lastSeenTime"),
    }


register(ModuleSpec(
    slug="aps", title="Access Points", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("POST", "/query/ap"),),
    supports_views=("table", "grid"),
    warmup=True,
    merge=merge,
    columns=(
        Column("Name", "name"),
        Column("Model", "model"),
        Column("Zone", "zone", filter_kind="select", server_filter="ZONE_ID"),
        Column("Status", "status", "status"),
        Column("Clients", "clients", "number"),
        Column("Signal dB", "signal_db", "number"),
        Column("Firmware", "fw"),
        Column("IP", "ip"),
        Column("MAC", "mac"),
    ),
))
