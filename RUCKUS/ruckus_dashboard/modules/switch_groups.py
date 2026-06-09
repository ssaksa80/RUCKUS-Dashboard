"""Switch Groups — Switch Manager group hierarchy module."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
from ..clients.base import _extract_items
from ..clients.switchm import switch_manager_query

POLL_SECONDS = 120
ICON = "\U0001F5C2️"  # 🗂️


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    # SmartZone 7.x exposes the switch-group query at POST /group (not /group/list).
    data = switch_manager_query(ctx.connection, "group", ctx.config)
    rows = [r for r in _extract_items(data) if isinstance(r, dict)]
    items = [_normalize(r) for r in rows]
    return {"items": items, "raw_count": len(items)}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    total_switches = sum(int(i.get("switch_count") or 0) for i in items)
    root_groups = sum(1 for i in items if i.get("parent_id") is None)
    return {"total": len(items), "total_switches": total_switches,
            "root_groups": root_groups}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    return {"identity": {"id": entity_id}}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}


def _normalize(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "switch_count": int(row.get("switchCount") or 0),
        "parent_id": row.get("parentId"),
    }


register(ModuleSpec(
    slug="switch-groups", title="Switch Groups", group="Switching", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(),
    supports_views=("table",),
    warmup=True,
    merge=merge,
    columns=(
        Column("Group", "name"),
        Column("Switches", "switch_count", "number"),
        Column("Parent", "parent_id"),
    ),
))
