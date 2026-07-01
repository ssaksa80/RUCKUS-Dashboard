"""ICX Switches — primary switching module."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
from ..clients.switchm import (
    _api_version_fallbacks, fetch_switches, switch_manager_post, switch_manager_query,
)

POLL_SECONDS = 60
ICON = "\U0001F50C"  # electric-plug emoji

ONLINE_VALUES = {"online", "connected", "run", "operational", "registered", "up",
                 "approved", "ok"}
OFFLINE_VALUES = {"offline", "disconnected", "down", "unregistered", "gone"}
FLAGGED_VALUES = {"flagged", "warning", "degraded"}


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    response = fetch_switches(ctx.connection, ctx.config) or {}
    rows = response.get("switches") or []
    items = [_normalize(r) for r in rows]
    return {
        "items": items,
        "raw_count": int(response.get("total", len(rows))),
        "online": int(response.get("online", 0)),
        "offline": int(response.get("offline", 0)),
    }


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    online = sum(1 for i in items if i.get("status") == "online")
    offline = sum(1 for i in items if i.get("status") == "offline")
    ports_up = sum(int(i.get("ports_online") or 0) for i in items)
    ports_total = sum(int(i.get("ports_total") or 0) for i in items)
    # Inventory rows are core/stack entries; the full count includes every
    # stack member (units).
    total_switches = sum(int(i.get("units") or 1) for i in items)
    return {"core_switches": len(items), "total_switches": total_switches,
            "online": online, "offline": offline,
            "ports_up": ports_up, "ports_total": ports_total}


def _drill_ports(ctx: FetcherContext, entity_id: str) -> list[dict[str, Any]]:
    """Ports belonging to this switch, normalized to minimal fields.

    Walks the SwitchM version fallbacks like ports.fetch does; any upstream
    failure on every candidate returns an empty list (never raises)."""
    from ..clients.base import RuckusClientError

    rows: list[dict[str, Any]] = []
    try:
        data = switch_manager_query(
            ctx.connection, "switch/ports/summary", ctx.config,
            fallback_paths=("switch/ports/details", "portSettings/query"),
        )
        rows = [r for r in ((data or {}).get("list") or []) if isinstance(r, dict)]
    except RuckusClientError:
        rows = []  # drill ports are best-effort; absent section is acceptable
    ports = []
    for r in rows:
        if str(r.get("switchId")) != str(entity_id):
            continue
        ports.append({
            "port_id": r.get("portId"),
            "switch_id": r.get("switchId"),
            "status": str(r.get("status") or "").lower(),
            "vlan": r.get("vlan"),
            "poe_class": r.get("poeClass") or "",
        })
    return ports


def _drill_health(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    """Best-effort CPU/mem aggregates for this switch. Each sub-call is
    isolated; a failure leaves that section absent rather than raising."""
    from ..clients.base import RuckusClientError

    health: dict[str, Any] = {}
    payload = {"switchIds": [entity_id]}
    for key, path in (("cpu", "health/cpu/agg"), ("mem", "health/mem/agg")):
        for version in _api_version_fallbacks(ctx.connection.api_version):
            try:
                data = switch_manager_post(
                    ctx.connection, version, path, ctx.config, payload,
                )
            except RuckusClientError:
                continue
            except Exception:  # noqa: BLE001 — health is best-effort
                break
            if data is not None:
                health[key] = data
            break
    return health


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    """Full switch detail: identity row + this switch's ports + health.

    Never raises — every sub-fetch is isolated so a single upstream failure
    only empties its own section."""
    identity: dict[str, Any] = {"id": entity_id}
    raw: Any = None
    connected: list[dict[str, Any]] = []
    try:
        response = fetch_switches(ctx.connection, ctx.config) or {}
        rows = response.get("switches") or []
        target = next((r for r in rows
                       if str(r.get("id")) == str(entity_id)), None)
        if target is not None:
            identity = _normalize(target)
            raw = target
            # Switches connected to this core: same group/stack, minus itself.
            gid = target.get("groupId") or target.get("stackId")
            if gid:
                connected = [
                    {"name": r.get("switchName") or r.get("name"),
                     "ip": r.get("ipAddress"),
                     "model": r.get("model"),
                     "status": str(r.get("status") or "").lower(),
                     "units": int(r.get("numOfUnits") or 1)}
                    for r in rows
                    if (r.get("groupId") or r.get("stackId")) == gid
                    and str(r.get("id")) != str(entity_id)
                ]
    except Exception:  # noqa: BLE001 — identity falls back to {"id": entity_id}
        pass

    try:
        ports = _drill_ports(ctx, entity_id)
    except Exception:  # noqa: BLE001
        ports = []

    try:
        health = _drill_health(ctx, entity_id)
    except Exception:  # noqa: BLE001
        health = {}

    return {"identity": identity, "connected_switches": connected,
            "ports": ports, "health": health, "raw": raw}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    online_total, offline_total = 0, 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
        online_total += int(r.get("online", 0))
        offline_total += int(r.get("offline", 0))
    return {"items": items, "raw_count": raw,
            "online": online_total, "offline": offline_total}


def _normalize(row: dict) -> dict:
    raw_status = str(row.get("status") or "").lower()
    if raw_status in ONLINE_VALUES:
        status = "online"
    elif raw_status in OFFLINE_VALUES:
        status = "offline"
    elif raw_status in FLAGGED_VALUES:
        status = "flagged"
    else:
        status = raw_status or "unknown"
    port_status = row.get("portStatus") or {}
    return {
        "id": row.get("id") or row.get("macAddress"),
        "name": row.get("switchName") or row.get("name") or "-",
        "model": row.get("model"),
        "ip": row.get("ipAddress") or row.get("ip"),
        "status": status,
        # This build reports stacks via numOfUnits (stackId is null); show the
        # managing group as the "stack/group" column value.
        "stack": row.get("stackId") or row.get("groupName"),
        "fw": row.get("firmwareVersion") or row.get("firmware"),
        "uptime": row.get("upTime") or row.get("uptime"),
        "ports_online": port_status.get("up") if port_status else row.get("portsOnline"),
        "ports_total": (port_status.get("total") if port_status else None)
                        or row.get("ports") or row.get("portsTotal"),
        "serial": row.get("serialNumber"),
        "group": row.get("groupName"),
        "units": row.get("numOfUnits"),
        "mac": row.get("macAddress") or row.get("id"),
    }


register(ModuleSpec(
    slug="switches", title="Switches", group="Switching", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="connected_switches", title="Connected"),
        TabSpec(slug="ports", title="Ports"),
        TabSpec(slug="health", title="Health"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("POST", "/switch"),),
    supports_views=("table",),
    warmup=True,
    merge=merge,
    columns=(
        Column("Name", "name"),
        Column("Model", "model"),
        Column("IP", "ip"),
        Column("Status", "status", "status"),
        Column("Stack", "stack"),
        Column("Firmware", "fw"),
        Column("Uptime", "uptime"),
        Column("Ports Up", "ports_online", "number"),
        Column("Ports", "ports_total", "number"),
    ),
))
