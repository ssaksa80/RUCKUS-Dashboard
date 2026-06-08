"""Switch Ports — port-level status and PoE telemetry module."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, Filter, FetcherContext, ModuleSpec, TabSpec
from ..clients.base import RuckusClientError
from ..clients.switchm import _api_version_fallbacks, switch_manager_post

POLL_SECONDS = 30
ICON = "\U0001F517"  # 🔗


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    limit = min(int(ctx.config.get("RUCKUS_PAGE_LIMIT", 500)), 1000)
    payload = {"page": 0, "limit": limit}
    rows: list[dict[str, Any]] = []
    for version in _api_version_fallbacks(ctx.connection.api_version):
        try:
            data = switch_manager_post(
                ctx.connection, version, "switch/ports/summary", ctx.config, payload,
            )
        except RuckusClientError:
            continue
        rows = [r for r in ((data or {}).get("list") or []) if isinstance(r, dict)]
        break
    items = [_normalize(r) for r in rows]
    return {"items": items, "raw_count": len(items)}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    up = sum(1 for i in items if i.get("status") == "up")
    down = sum(1 for i in items if i.get("status") == "down")
    poe_on = sum(1 for i in items if i.get("poe_on"))
    errors_total = sum(int(i.get("errors") or 0) for i in items)
    errors_ports = sum(1 for i in items if int(i.get("errors") or 0) > 0)
    return {"total": len(items), "up": up, "down": down,
            "poe_on": poe_on, "errors_total": errors_total,
            "errors_ports": errors_ports}


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
    port_id = row.get("portId")
    return {
        "id": f"{switch_id}:{port_id}",
        "switch_id": switch_id,
        "port_id": port_id,
        "name": row.get("name"),
        "status": str(row.get("status") or "").lower(),
        "speed": int(row.get("speed") or 0),
        "vlan": int(row.get("vlan") or 0),
        "poe_class": row.get("poeClass") or "",
        "poe_on": bool(row.get("poeEnabled")),
        "rx_bps": int(row.get("rxBps") or 0),
        "tx_bps": int(row.get("txBps") or 0),
        "errors": int(row.get("errors") or 0),
        "attached_mac": row.get("attachedMac") or "",
        "lldp_neighbor": row.get("lldpNeighbor") or "",
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
    requires_capabilities=(("POST", "/switch/ports/summary"),),
    supports_views=("table",),
    warmup=True,
    merge=merge,
    columns=(
        Column("Switch", "switch_id"),
        Column("Port", "port_id"),
        Column("Status", "status", "status"),
        Column("Speed", "speed", "number"),
        Column("VLAN", "vlan", "number"),
        Column("PoE", "poe_class"),
        Column("RX bps", "rx_bps", "bytes"),
        Column("TX bps", "tx_bps", "bytes"),
        Column("Errors", "errors", "number"),
        Column("Neighbor", "lldp_neighbor"),
    ),
    filters=(
        Filter("status", "Status", "select"),
    ),
))
