"""Access Points — primary wireless module."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_post, smartzone_query_body

POLL_SECONDS = 30
ICON = "\U0001F4F6"  # signal-bars emoji

ONLINE_VALUES = {"online", "connected", "run", "operational", "registered", "up"}
OFFLINE_VALUES = {"offline", "disconnected", "down", "unregistered", "gone"}
FLAGGED_VALUES = {"flagged", "warning", "degraded"}


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    payload = _build_query(ctx.filters)
    # smartzone_post signature: (connection, path, config, body, debug, *, optional=False)
    response = smartzone_post(ctx.connection, "query/ap", ctx.config, payload, [])
    response = response or {}
    rows = response.get("list") or []
    items = [_normalize(r) for r in rows]
    return {"items": items, "raw_count": response.get("totalCount", len(rows))}


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


def _build_query(filters: dict | None) -> dict:
    return smartzone_query_body(filters)


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
))
