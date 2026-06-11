"""Switch Traffic — top switches by traffic usage module."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
from ..clients.switchm import switch_manager_query, fetch_switches

POLL_SECONDS = 30
ICON = "\U0001F4CA"  # 📊


# Per-switch counter baselines + last computed rates, kept in-process.
# SmartZone refreshes the traffic aggregate only periodically, so each
# baseline is held until the counter actually moves and the rate is averaged
# over the real elapsed window (a 30s delta would almost always read 0).
_PREV: dict[str, Any] = {"base": {}, "rate": {}}


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    import time as _time
    # traffic/top/usage rows are {key: <switch MAC>, value: <total bytes>} with
    # no switch name — resolve names from the switch inventory.
    name_by_mac = _switch_name_map(ctx)
    data = switch_manager_query(ctx.connection, "traffic/top/usage", ctx.config)
    rows = [r for r in ((data or {}).get("list") or []) if isinstance(r, dict)]
    items = [_normalize(r, name_by_mac) for r in rows]

    now = _time.time()
    for i in items:
        sid = str(i.get("id") or "")
        total = int(i.get("total_bytes") or 0)
        base = _PREV["base"].get(sid)
        if base is None or total < base["bytes"]:
            # First sighting or counter reset — start the baseline.
            _PREV["base"][sid] = {"bytes": total, "t": now}
            _PREV["rate"].pop(sid, None) if base is None else None
        elif total > base["bytes"] and now - base["t"] >= 5:
            _PREV["rate"][sid] = round((total - base["bytes"]) * 8
                                       / (now - base["t"]))
            _PREV["base"][sid] = {"bytes": total, "t": now}
        # unchanged counter → keep the last computed rate
        i["rate_bps"] = _PREV["rate"].get(sid)
    return {"items": items, "raw_count": len(items), "raw_rows": rows[:2]}


def _switch_name_map(ctx: FetcherContext) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        resp = fetch_switches(ctx.connection, ctx.config) or {}
    except Exception:  # noqa: BLE001
        return out
    for sw in resp.get("switches") or []:
        if not isinstance(sw, dict):
            continue
        name = sw.get("switchName") or sw.get("name")
        for key in (sw.get("id"), sw.get("macAddress"), sw.get("mac")):
            if key and name:
                out[str(key).upper()] = name
    return out


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    total_switches = len(items)
    total_bytes = sum(int(i.get("total_bytes") or 0) for i in items)
    top_switch = items[0]["switch_name"] if items else "—"
    return {"total_switches": total_switches,
            "total_bytes": total_bytes,
            "top_switch": top_switch}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    return {"identity": {"id": entity_id}}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}


def _normalize(row: dict, name_by_mac: dict[str, str] | None = None) -> dict:
    name_by_mac = name_by_mac or {}
    key = row.get("key") or row.get("id") or row.get("switchId")
    total = int(row.get("value") or row.get("totalUsage") or 0)
    name = name_by_mac.get(str(key).upper()) if key else None
    return {
        "id": key,
        "switch_id": key,
        "switch_name": name or key or "—",
        "total_bytes": total,
    }


register(ModuleSpec(
    slug="traffic", title="Traffic", group="Switching", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("POST", "/traffic/top/usage"),),
    supports_views=("table",),
    warmup=True,
    merge=merge,
    columns=(
        Column("Switch", "switch_name"),
        Column("Live Rate", "rate_bps", "rate"),
        Column("Total Traffic", "total_bytes", "bytes"),
    ),
))
