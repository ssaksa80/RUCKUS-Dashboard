"""Switch PoE — power-over-Ethernet utilisation per switch module."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
from ..clients.base import RuckusClientError
from ..clients.switchm import _api_version_fallbacks, switch_manager_post

POLL_SECONDS = 60
ICON = "⚡"  # ⚡


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    limit = min(int(ctx.config.get("RUCKUS_PAGE_LIMIT", 500)), 1000)
    payload = {"page": 0, "limit": limit}
    rows: list[dict[str, Any]] = []
    for version in _api_version_fallbacks(ctx.connection.api_version):
        try:
            data = switch_manager_post(
                ctx.connection, version, "traffic/top/poeutilization", ctx.config, payload,
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
    total_budget_w = sum(int(i.get("budget_w") or 0) for i in items)
    total_allocated_w = sum(int(i.get("allocated_w") or 0) for i in items)
    total_ports_powered = sum(int(i.get("ports_powered") or 0) for i in items)
    avg_util_pct = round(
        sum(float(i.get("util_pct") or 0) for i in items) / len(items), 1
    ) if items else 0
    return {"total_switches": total_switches,
            "total_budget_w": total_budget_w,
            "total_allocated_w": total_allocated_w,
            "total_ports_powered": total_ports_powered,
            "avg_util_pct": avg_util_pct}


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
    budget_w = int(row.get("budgetWatts") or 0)
    allocated_w = int(row.get("allocatedWatts") or 0)
    available_w = int(row.get("availableWatts") or 0)
    ports_powered = int(row.get("portsPoweredCount") or 0)
    util_pct = round((allocated_w / budget_w * 100) if budget_w > 0 else 0, 1)
    return {
        "id": switch_id,
        "switch_id": switch_id,
        "switch_name": row.get("switchName"),
        "budget_w": budget_w,
        "allocated_w": allocated_w,
        "available_w": available_w,
        "ports_powered": ports_powered,
        "util_pct": util_pct,
    }


register(ModuleSpec(
    slug="poe", title="PoE", group="Switching", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("POST", "/traffic/top/poeutilization"),),
    supports_views=("table",),
    warmup=True,
    merge=merge,
    columns=(
        Column("Switch", "switch_name"),
        Column("Budget W", "budget_w", "number"),
        Column("Allocated W", "allocated_w", "number"),
        Column("Available W", "available_w", "number"),
        Column("Ports Powered", "ports_powered", "number"),
        Column("Util %", "util_pct", "number"),
    ),
))
