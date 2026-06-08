"""Rogues — SmartZone rogue AP inventory with classification summary."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_post, smartzone_query_body

POLL_SECONDS = 60
ICON = "\U0001F47B"  # ghost emoji

_CLASSIFICATIONS = ("malicious", "rogue", "known")


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    payload = _build_query(ctx.filters)
    # smartzone_post signature: (connection, path, config, body, debug, *, optional=False)
    response = smartzone_post(
        ctx.connection, "query/roguesInfoList", ctx.config, payload, []
    )
    response = response or {}
    rows = response.get("list") or []
    items = [_normalize(r) for r in rows]
    return {"items": items, "raw_count": response.get("totalCount", len(rows))}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    counts = {cls: 0 for cls in _CLASSIFICATIONS}
    for item in items:
        cls = str(item.get("classification") or "").lower()
        if cls in counts:
            counts[cls] += 1
    counts["total"] = len(items)
    return counts


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    # SmartZone does not expose a per-rogue detail endpoint; full row data is
    # already returned by /query/roguesInfoList. Provide a minimal identity
    # payload so the drill route has a uniform shape across modules.
    return {"identity": {"bssid": entity_id}, "raw": None}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}


def _build_query(filters: dict | None) -> dict:
    return smartzone_query_body(filters)


def _normalize(row: dict) -> dict:
    return {
        "id": row.get("bssid"),
        "bssid": row.get("bssid"),
        "ssid": row.get("ssid"),
        "channel": int(row.get("channel") or 0),
        "encryption": row.get("encryption"),
        "rssi": int(row.get("rssi") or 0),
        "detecting_ap": row.get("detectingAp"),
        "classification": str(row.get("classification") or "").lower(),
        "first_seen": row.get("firstFoundTime"),
        "last_seen": row.get("lastFoundTime"),
    }


register(ModuleSpec(
    slug="rogues", title="Rogues", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("POST", "/query/roguesInfoList"),),
    supports_views=("table", "grid"),
    warmup=True,
    merge=merge,
))
