"""Clients — wireless client inventory."""
from __future__ import annotations
from typing import Any
from urllib.parse import quote

from . import register
from ._base import FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_post

POLL_SECONDS = 20
ICON = "\U0001F465"  # busts-in-silhouette emoji


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    payload = _build_query(ctx.filters)
    # smartzone_post signature: (connection, path, config, body, debug, *, optional=False)
    response = smartzone_post(ctx.connection, "query/client", ctx.config, payload, [])
    response = response or {}
    rows = response.get("list") or []
    items = [_normalize(r) for r in rows]
    return {"items": items, "raw_count": response.get("totalCount", len(rows))}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    low_rssi = sum(1 for i in items if int(i.get("rssi") or 0) < -70)
    by_os: dict[str, int] = {}
    for i in items:
        os_name = i.get("os") or "UNKNOWN"
        by_os[os_name] = by_os.get(os_name, 0) + 1
    return {"total": len(items), "low_rssi": low_rssi, "by_os": by_os}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    from ..clients.smartzone import smartzone_get
    try:
        # smartzone_get signature: (connection, path, config, params, debug)
        detail = smartzone_get(ctx.connection,
                               f"clients/{quote(entity_id)}/operational/summary",
                               ctx.config, None, [])
    except Exception as exc:
        return {"identity": {"mac": entity_id}, "error": str(exc)}
    if not detail:
        return {"identity": {"mac": entity_id}}
    return {"identity": _normalize(detail), "raw": detail}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}


def _build_query(filters: dict | None) -> dict:
    f = filters or {}
    payload = {"page": int(f.get("page", 0)),
               "limit": int(f.get("limit", 500))}
    if f.get("zone"):
        payload["filters"] = [{"type": "ZONE_ID", "value": f["zone"]}]
    return payload


def _normalize(row: dict) -> dict:
    mac = row.get("clientMac")
    return {
        "id": mac,
        "mac": mac,
        "hostname": row.get("hostname") or "-",
        "ip": row.get("ipAddress"),
        "ssid": row.get("ssid"),
        "ap": row.get("apMac"),
        "rssi": int(row.get("rssi") or 0),
        "rx_bytes": int(row.get("rxBytes") or 0),
        "tx_bytes": int(row.get("txBytes") or 0),
        "os": row.get("osType"),
        "auth_method": row.get("authMethod"),
        "connected_at": row.get("connectionTime"),
    }


register(ModuleSpec(
    slug="clients", title="Clients", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("POST", "/query/client"),),
    supports_views=("table", "grid"),
    warmup=True,
    merge=merge,
))
