"""VLANs — VLAN inventory and member-switch tallies module."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
from ..clients.switchm import switch_manager_query

POLL_SECONDS = 60
ICON = "\U0001F3F7"  # 🏷️


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    data = switch_manager_query(ctx.connection, "vlan/list", ctx.config)
    rows = [r for r in ((data or {}).get("list") or []) if isinstance(r, dict)]
    items = [_normalize(r) for r in rows]
    return {"items": items, "raw_count": len(items)}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    total_tagged = sum(int(i.get("tagged_ports") or 0) for i in items)
    total_untagged = sum(int(i.get("untagged_ports") or 0) for i in items)
    return {"total_vlans": len(items),
            "total_tagged_ports": total_tagged,
            "total_untagged_ports": total_untagged}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    return {"identity": {"id": entity_id}}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}


def _normalize(row: dict) -> dict:
    vlan_id = row.get("vlanId")
    members = row.get("memberSwitches") or []
    if not isinstance(members, list):
        members = []
    return {
        "id": str(vlan_id) if vlan_id is not None else "",
        "vlan_id": int(vlan_id or 0),
        "name": row.get("name") or "",
        "member_switches": members,
        "member_switch_count": len(members),
        "tagged_ports": int(row.get("taggedPortCount") or 0),
        "untagged_ports": int(row.get("untaggedPortCount") or 0),
    }


register(ModuleSpec(
    slug="vlans", title="VLANs", group="Switching", icon=ICON,
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
))
