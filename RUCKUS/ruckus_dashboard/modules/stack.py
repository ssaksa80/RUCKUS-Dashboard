"""ICX Stack — switch stack topology derived from switch/view/details."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
from ..clients.base import RuckusClientError
from ..clients.switchm import _api_version_fallbacks, switch_manager_post

POLL_SECONDS = 60
ICON = "\U0001F3D7"  # 🏗️


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    limit = min(int(ctx.config.get("RUCKUS_PAGE_LIMIT", 500)), 1000)
    payload = {"page": 0, "limit": limit}
    rows: list[dict[str, Any]] = []
    for version in _api_version_fallbacks(ctx.connection.api_version):
        try:
            data = switch_manager_post(
                ctx.connection, version, "switch/view/details", ctx.config, payload,
            )
        except RuckusClientError:
            continue
        rows = [r for r in ((data or {}).get("list") or []) if isinstance(r, dict)]
        break
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
    groups: dict[str, list[dict]] = {}
    for row in rows:
        stack_id = row.get("stackId")
        if not stack_id:
            continue
        # Skip solo switches where stackId equals the switch id
        if stack_id == row.get("id"):
            continue
        groups.setdefault(stack_id, []).append(row)
    items: list[dict] = []
    for stack_id, members in groups.items():
        master = next(
            (m for m in members if str(m.get("stackRole") or "").lower() == "active"),
            None,
        )
        standby = next(
            (m for m in members if str(m.get("stackRole") or "").lower() == "standby"),
            None,
        )
        firmwares = [m.get("firmware") for m in members]
        fw_aligned = len(set(firmwares)) <= 1
        ports_up = sum(int(m.get("stackPortsUp") or 0) for m in members)
        ports_total = sum(int(m.get("stackPortsTotal") or 0) for m in members)
        items.append({
            "id": stack_id,
            "stack_id": stack_id,
            "members": len(members),
            "master": master.get("id") if master else None,
            "standby": standby.get("id") if standby else None,
            "ports_up": ports_up,
            "ports_total": ports_total,
            "fw_aligned": fw_aligned,
            "firmware": firmwares[0] if firmwares else None,
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
