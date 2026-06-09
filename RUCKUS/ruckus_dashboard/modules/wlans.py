"""WLANs — wireless SSID inventory."""
from __future__ import annotations
from typing import Any
from urllib.parse import quote

from . import register
from ._base import Column, Filter, FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_query_paged

POLL_SECONDS = 60
ICON = "\U0001F310"  # globe emoji


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    f = ctx.filters or {}
    body = {"filters": [{"type": "ZONE_ID", "value": f["zone"]}]} if f.get("zone") else {}
    rows = smartzone_query_paged(ctx.connection, "query/wlan", ctx.config, [], body=body)
    items = [_normalize(r) for r in rows]
    return {"items": items, "raw_count": len(rows)}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    clients = sum(int(i.get("clients") or 0) for i in items)
    by_auth: dict[str, int] = {}
    for i in items:
        auth = i.get("auth") or "UNKNOWN"
        by_auth[auth] = by_auth.get(auth, 0) + 1
    return {"total": len(items), "clients": clients, "by_auth": by_auth}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    from ..clients.smartzone import smartzone_get
    try:
        # smartzone_get signature: (connection, path, config, params, debug)
        detail = smartzone_get(ctx.connection,
                               f"query/wlan/{quote(entity_id)}",
                               ctx.config, None, [])
    except Exception as exc:
        return {"identity": {"id": entity_id, "ssid": "-"}, "error": str(exc)}
    if not detail:
        return {"identity": {"id": entity_id, "ssid": "-"}}
    return {"identity": _normalize(detail), "raw": detail}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}




def _normalize(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "ssid": row.get("name") or "-",
        "zone": row.get("zoneName"),
        "zone_id": row.get("zoneId"),
        "vlan": int(row.get("vlanId") or 0),
        "auth": row.get("authType"),
        "encryption": row.get("encryption"),
        "clients": int(row.get("numClients") or 0),
    }


register(ModuleSpec(
    slug="wlans", title="WLANs", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("POST", "/query/wlan"),),
    supports_views=("table", "grid"),
    warmup=True,
    merge=merge,
    columns=(
        Column("SSID", "ssid"),
        Column("Zone", "zone"),
        Column("VLAN", "vlan", "number"),
        Column("Auth", "auth"),
        Column("Encryption", "encryption"),
        Column("Clients", "clients", "number"),
    ),
    filters=(
        Filter("zone", "Zone", "select"),
        Filter("auth", "Auth", "select"),
    ),
))
