"""Switch Ports — per-switch port utilisation summary.

SmartZone 7.1.1 does not serve a fabric-wide per-port list (``/switch/ports/
summary`` and ``/switch/ports/details`` 404 on this build). Each switch row,
however, carries a ``portStatus`` rollup (up/down/warning/total) plus a ``poe``
budget — so this module presents one row per switch with its port utilisation,
derived from the switch inventory (the reliable switch endpoint)."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, Filter, FetcherContext, ModuleSpec, TabSpec
from ..clients.switchm import fetch_switches

POLL_SECONDS = 30
ICON = "\U0001F517"  # 🔗


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    response = fetch_switches(ctx.connection, ctx.config) or {}
    switches = response.get("switches") or []
    items = [_normalize(sw) for sw in switches]
    return {"items": items, "raw_count": len(items)}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    return {
        "switches": len(items),
        "ports_total": sum(int(i.get("ports_total") or 0) for i in items),
        "ports_up": sum(int(i.get("ports_up") or 0) for i in items),
        "ports_down": sum(int(i.get("ports_down") or 0) for i in items),
        "ports_warning": sum(int(i.get("ports_warning") or 0) for i in items),
    }


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    return {"identity": {"id": entity_id}}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}


def _normalize(row: dict) -> dict:
    ps = row.get("portStatus") or {}
    poe = row.get("poe") or {}
    poe_total = int(poe.get("total") or 0)
    poe_free = int(poe.get("free") or 0)
    return {
        "id": row.get("id") or row.get("macAddress"),
        "switch": row.get("switchName") or row.get("name") or "-",
        "ip": row.get("ipAddress") or row.get("ip"),
        "model": row.get("model"),
        "ports_total": int(ps.get("total") or row.get("ports") or 0),
        "ports_up": int(ps.get("up") or 0),
        "ports_down": int(ps.get("down") or 0),
        "ports_warning": int(ps.get("warning") or 0),
        "poe_total_w": poe_total,
        "poe_used_w": max(0, poe_total - poe_free),
        "poe_pct": float(poe.get("percent") or 0),
    }


register(ModuleSpec(
    slug="ports", title="Ports", group="Switching", icon=ICON,
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
        Column("Switch", "switch"),
        Column("IP", "ip"),
        Column("Model", "model"),
        Column("Ports", "ports_total", "number"),
        Column("Up", "ports_up", "number"),
        Column("Down", "ports_down", "number"),
        Column("Warning", "ports_warning", "number"),
        Column("PoE %", "poe_pct", "number"),
    ),
    filters=(
        Filter("model", "Model", "select"),
    ),
))
