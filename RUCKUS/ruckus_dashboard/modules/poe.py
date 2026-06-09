"""Switch PoE — power-over-Ethernet budget per switch.

SmartZone 7.1.1's ``traffic/top/poeutilization`` rows don't carry usable
budget fields, but every switch row reports a ``poe`` budget block
(``total``/``free``/``percent`` watts). Derive PoE from the switch inventory."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
from ..clients.switchm import fetch_switches

POLL_SECONDS = 60
ICON = "⚡"  # ⚡


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    response = fetch_switches(ctx.connection, ctx.config) or {}
    switches = response.get("switches") or []
    items = [_normalize(sw) for sw in switches]
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
    poe = row.get("poe") or {}
    budget_w = int(poe.get("total") or row.get("budgetWatts") or 0)
    available_w = int(poe.get("free") or row.get("availableWatts") or 0)
    allocated_w = max(0, budget_w - available_w)
    pct = poe.get("percent")
    util_pct = round(float(pct), 1) if pct is not None else (
        round(allocated_w / budget_w * 100, 1) if budget_w > 0 else 0
    )
    sid = row.get("id") or row.get("macAddress") or row.get("switchId")
    return {
        "id": sid,
        "switch_id": sid,
        "switch_name": row.get("switchName") or row.get("name"),
        "budget_w": budget_w,
        "allocated_w": allocated_w,
        "available_w": available_w,
        "ports_powered": int(row.get("portsPoweredCount") or 0),
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
    requires_capabilities=(("POST", "/switch"),),
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
