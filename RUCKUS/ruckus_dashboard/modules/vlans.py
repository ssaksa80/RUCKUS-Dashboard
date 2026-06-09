"""VLANs — VLAN inventory and member-switch tallies module."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
from ..clients.switchm import switch_manager_query

POLL_SECONDS = 60
ICON = "\U0001F3F7"  # 🏷️


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    # SmartZone 7.1.1 serves VLANs at /vlans/query with a minimal {page, limit}
    # body (the full switch envelope filters everything out). Each row is a VLAN
    # *on one switch* (vlanId + switchId + ports[]), so paginate all pages and
    # group by vlanId to get member-switch and port tallies.
    limit = min(int(ctx.config.get("RUCKUS_PAGE_LIMIT", 500)), 1000)
    rows: list[dict] = []
    page = 1
    while page <= 20:
        data = switch_manager_query(
            ctx.connection, "vlans/query", ctx.config,
            payload={"page": page, "limit": limit},
        )
        batch = [r for r in ((data or {}).get("list") or []) if isinstance(r, dict)]
        rows.extend(batch)
        if len(batch) < limit:
            break
        page += 1

    items = _group_by_vlan(rows)
    return {"items": items, "raw_count": len(items), "raw_rows": rows[:2]}


def _group_by_vlan(rows: list[dict]) -> list[dict]:
    groups: dict[Any, dict] = {}
    for r in rows:
        vid = r.get("vlanId")
        g = groups.get(vid)
        if g is None:
            g = {"vlan_id": vid, "name": r.get("name") or "",
                 "switches": set(), "port_count": 0}
            groups[vid] = g
        if not g["name"] and r.get("name"):
            g["name"] = r.get("name")
        sw = r.get("switchId")
        if sw:
            g["switches"].add(sw)
        ports = r.get("ports")
        if isinstance(ports, list):
            g["port_count"] += len(ports)
    items = []
    for vid, g in groups.items():
        members = sorted(g["switches"])
        items.append({
            "id": str(vid) if vid is not None else "",
            "vlan_id": int(vid or 0),
            "name": g["name"],
            "member_switches": members,
            "member_switch_count": len(members),
            "port_count": g["port_count"],
        })
    items.sort(key=lambda i: i["vlan_id"])
    return items


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    return {"total_vlans": len(items),
            "total_switch_links": sum(int(i.get("member_switch_count") or 0) for i in items),
            "total_ports": sum(int(i.get("port_count") or 0) for i in items)}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    return {"identity": {"id": entity_id}}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}


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
    columns=(
        Column("VLAN", "vlan_id", "number"),
        Column("Name", "name"),
        Column("Member Switches", "member_switch_count", "number"),
        Column("Ports", "port_count", "number"),
    ),
))
