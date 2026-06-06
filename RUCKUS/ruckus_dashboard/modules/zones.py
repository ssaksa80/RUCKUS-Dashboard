"""Zones module."""
from __future__ import annotations
from typing import Any
from urllib.parse import quote

from . import register
from ._base import FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_paged_get, smartzone_get

POLL_SECONDS = 60
ICON = "\U0001F3E2"  # office-building emoji


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    # smartzone_paged_get signature: (connection, path, config, *, params=None, debug)
    rows = smartzone_paged_get(ctx.connection, "rkszones", ctx.config, debug=[])
    items = [_normalize(r) for r in rows]
    return {"items": items, "raw_count": len(rows)}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    return {"total": len(items),
            "total_aps": sum(int(i.get("ap_count") or 0) for i in items),
            "total_wlans": sum(int(i.get("wlan_count") or 0) for i in items)}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    try:
        # smartzone_get signature: (connection, path, config, params, debug)
        detail = smartzone_get(ctx.connection,
                               f"rkszones/{quote(entity_id)}",
                               ctx.config, None, [])
    except Exception as exc:
        return {"identity": {"id": entity_id}, "error": str(exc)}
    return {"identity": _normalize(detail or {}), "raw": detail}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for r in results:
        items.extend(r.get("items", []))
    return {"items": items, "raw_count": len(items)}


def _normalize(row: dict) -> dict:
    return {
        "id": row.get("id") or row.get("zoneId"),
        "name": row.get("name") or row.get("serviceName") or "-",
        "ap_count": int(row.get("apCount") or 0),
        "wlan_count": int(row.get("wlanCount") or 0),
        "fw": row.get("version") or row.get("firmwareVersion"),
        "country": row.get("countryCode"),
        "mesh_mode": row.get("meshMode"),
    }


register(ModuleSpec(
    slug="zones", title="Zones", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS, fetcher=fetch, drill_fetcher=fetch_drill,
    drill_tabs=(TabSpec(slug="summary", title="Summary"),
                TabSpec(slug="raw", title="Raw")),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("GET", "/rkszones"),),
    supports_views=("table", "tree"),
    warmup=True, merge=merge,
))
