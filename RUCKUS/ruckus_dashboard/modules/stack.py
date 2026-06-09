"""ICX Stack — switch stack topology derived from switch/view/details."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
from ..clients.switchm import switch_manager_query

POLL_SECONDS = 60
ICON = "\U0001F3D7"  # 🏗️


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    # SmartZone 7.1.1 serves the switch list at /switch (not /switch/view/details).
    data = switch_manager_query(
        ctx.connection, "switch", ctx.config,
        fallback_paths=("switch/view/details",),
    )
    rows = [r for r in ((data or {}).get("list") or []) if isinstance(r, dict)]
    items = _group_by_stack(rows)
    return {"items": items, "raw_count": len(items)}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    total_stacks = len(items)
    total_members = sum(int(i.get("members") or 0) for i in items)
    misaligned_fw = sum(1 for i in items if not i.get("fw_aligned"))
    return {"total_stacks": total_stacks,
            "total_members": total_members,
            "misaligned_fw": misaligned_fw}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    return {"identity": {"id": entity_id}}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}


def _group_by_stack(rows: list[dict]) -> list[dict]:
    """Identify ICX stacks from the switch list.

    SmartZone 7.1.1 reports a stacked unit as a single switch row with
    ``numOfUnits > 1`` (and ``modules == "stack"``); ``stackId`` is null. Older
    builds grouped explicit member rows by ``stackId`` with per-member
    ``stackRole``. Support both: prefer explicit stackId grouping, otherwise
    treat each multi-unit switch as one stack.
    """
    explicit: dict[str, list[dict]] = {}
    for row in rows:
        sid = row.get("stackId")
        if sid and sid != row.get("id"):
            explicit.setdefault(str(sid), []).append(row)

    items: list[dict] = []
    if explicit:
        for stack_id, members in explicit.items():
            master = next((m for m in members
                           if str(m.get("stackRole") or "").lower() == "active"), None)
            standby = next((m for m in members
                            if str(m.get("stackRole") or "").lower() == "standby"), None)
            firmwares = [m.get("firmwareVersion") or m.get("firmware") for m in members]
            items.append({
                "id": stack_id, "stack_id": stack_id, "members": len(members),
                "master": master.get("id") if master else None,
                "standby": standby.get("id") if standby else None,
                "ports_up": sum(int(m.get("stackPortsUp") or 0) for m in members),
                "ports_total": sum(int(m.get("stackPortsTotal") or 0) for m in members),
                "fw_aligned": len(set(firmwares)) <= 1,
                "firmware": firmwares[0] if firmwares else None,
            })
        return items

    # Fallback: each multi-unit switch row is its own stack.
    for row in rows:
        units = int(row.get("numOfUnits") or 1)
        if units <= 1 and str(row.get("modules") or "").lower() != "stack":
            continue
        port_status = row.get("portStatus") or {}
        sid = row.get("id") or row.get("macAddress")
        items.append({
            "id": sid, "stack_id": sid, "name": row.get("switchName"),
            "members": units, "master": sid, "standby": None,
            "ports_up": port_status.get("up"),
            "ports_total": port_status.get("total") or row.get("ports"),
            "fw_aligned": True,
            "firmware": row.get("firmwareVersion") or row.get("firmware"),
            "group": row.get("groupName"),
        })
    return items


register(ModuleSpec(
    slug="stack", title="Stack", group="Switching", icon=ICON,
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
        Column("Stack", "stack_id"),
        Column("Members", "members", "number"),
        Column("Master", "master"),
        Column("Standby", "standby"),
        Column("Ports Up", "ports_up", "number"),
        Column("FW Aligned", "fw_aligned"),
        Column("Firmware", "firmware"),
    ),
))
