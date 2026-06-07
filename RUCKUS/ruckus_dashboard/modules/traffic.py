"""Switch Traffic — top switches by traffic usage module."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import FetcherContext, ModuleSpec, TabSpec
from ..clients.base import RuckusClientError
from ..clients.switchm import _api_version_fallbacks, switch_manager_post

POLL_SECONDS = 30
ICON = "\U0001F4CA"  # 📊


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    limit = min(int(ctx.config.get("RUCKUS_PAGE_LIMIT", 500)), 1000)
    payload = {"page": 0, "limit": limit}
    rows: list[dict[str, Any]] = []
    for version in _api_version_fallbacks(ctx.connection.api_version):
        try:
            data = switch_manager_post(
                ctx.connection, version, "traffic/top/usage", ctx.config, payload,
            )
        except RuckusClientError:
            continue
        rows = [r for r in ((data or {}).get("list") or []) if isinstance(r, dict)]
        break
    items = [_normalize(r) for r in rows]
    return {"items": items, "raw_count": len(items)}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    total_switches = len(items)
    total_bytes = sum(int(i.get("total_bytes") or 0) for i in items)
    top_switch = items[0]["switch_name"] if items else ""
    return {"total_switches": total_switches,
            "total_bytes": total_bytes,
            "top_switch": top_switch}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    return {"identity": {"id": entity_id}}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}


def _normalize(row: dict) -> dict:
    switch_id = row.get("switchId")
    return {
        "id": switch_id,
        "switch_id": switch_id,
        "switch_name": row.get("switchName"),
        "total_bytes": int(row.get("totalUsage") or 0),
        "rx_bytes": int(row.get("rxBytes") or 0),
        "tx_bytes": int(row.get("txBytes") or 0),
    }


register(ModuleSpec(
    slug="traffic", title="Traffic", group="Switching", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("POST", "/traffic/top/usage"),),
    supports_views=("table",),
    warmup=True,
    merge=merge,
))
