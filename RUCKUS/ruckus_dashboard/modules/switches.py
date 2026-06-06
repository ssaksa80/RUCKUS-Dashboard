"""ICX Switches — primary switching module."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import FetcherContext, ModuleSpec, TabSpec
from ..clients.switchm import fetch_switches

POLL_SECONDS = 60
ICON = "\U0001F50C"  # electric-plug emoji

ONLINE_VALUES = {"online", "connected", "run", "operational", "registered", "up",
                 "approved", "ok"}
OFFLINE_VALUES = {"offline", "disconnected", "down", "unregistered", "gone"}
FLAGGED_VALUES = {"flagged", "warning", "degraded"}


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    response = fetch_switches(ctx.connection, ctx.config) or {}
    rows = response.get("switches") or []
    items = [_normalize(r) for r in rows]
    return {
        "items": items,
        "raw_count": int(response.get("total", len(rows))),
        "online": int(response.get("online", 0)),
        "offline": int(response.get("offline", 0)),
    }


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    online = sum(1 for i in items if i.get("status") == "online")
    offline = sum(1 for i in items if i.get("status") == "offline")
    ports_up = sum(int(i.get("ports_online") or 0) for i in items)
    ports_total = sum(int(i.get("ports_total") or 0) for i in items)
    return {"total": len(items), "online": online, "offline": offline,
            "ports_up": ports_up, "ports_total": ports_total}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    return {"identity": {"id": entity_id}}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    online_total, offline_total = 0, 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
        online_total += int(r.get("online", 0))
        offline_total += int(r.get("offline", 0))
    return {"items": items, "raw_count": raw,
            "online": online_total, "offline": offline_total}


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
        "id": row.get("id"),
        "name": row.get("name"),
        "model": row.get("model"),
        "ip": row.get("ip"),
        "status": status,
        "stack": row.get("stackId"),
        "fw": row.get("firmware"),
        "uptime": row.get("uptime"),
        "ports_online": row.get("portsOnline"),
        "ports_total": row.get("portsTotal"),
    }


register(ModuleSpec(
    slug="switches", title="Switches", group="Switching", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("POST", "/switch/view/details"),),
    supports_views=("table",),
    warmup=True,
    merge=merge,
))
