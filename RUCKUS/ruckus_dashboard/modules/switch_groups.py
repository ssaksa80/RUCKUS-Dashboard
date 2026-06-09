"""Switch Groups — Switch Manager group hierarchy module."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
from ..clients.switchm import fetch_switches

POLL_SECONDS = 120
ICON = "\U0001F5C2️"  # 🗂️


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    # SmartZone 7.1.1 does not serve a POST /group switch-group list (404), but
    # every switch row carries groupId/groupName — derive the groups from the
    # switch inventory (the one switch endpoint that works on this build).
    response = fetch_switches(ctx.connection, ctx.config) or {}
    switches = response.get("switches") or []
    groups: dict[str, dict[str, Any]] = {}
    for sw in switches:
        gid = str(sw.get("groupId") or "")
        gname = sw.get("groupName") or gid or "Ungrouped"
        g = groups.setdefault(gid, {
            "id": gid or gname, "name": gname, "switch_count": 0,
            "parent_id": sw.get("parentGroupId") or None,
        })
        g["switch_count"] += 1
    items = list(groups.values())
    return {"items": items, "raw_count": len(items)}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    total_switches = sum(int(i.get("switch_count") or 0) for i in items)
    root_groups = sum(1 for i in items if not i.get("parent_id"))
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
