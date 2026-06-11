"""WLANs — site-wise rollup: WLANs per site + clients connected per site.

Rows are aggregated per zone (site). Drilling into a site lists its WLANs.
Client counts prefer the WLAN rows' ``numClients``; when the controller
reports zeros there (7.1.1 does), they are counted from ``query/client``
(zone match, SSID-join fallback)."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_query_paged

POLL_SECONDS = 60
ICON = "\U0001F310"  # globe emoji


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    rows = smartzone_query_paged(ctx.connection, "query/wlan", ctx.config, [])
    wlans = [_normalize(r) for r in rows]
    client_counts = _clients_per_site(ctx, wlans)
    items = _group_by_site(wlans, client_counts)
    return {"items": items, "raw_count": len(rows), "raw_rows": rows[:2]}


def _group_by_site(wlans: list[dict], client_counts: dict[str, int]) -> list[dict]:
    sites: dict[str, dict] = {}
    for w in wlans:
        key = str(w.get("zone_id") or w.get("zone") or "unknown")
        s = sites.setdefault(key, {"id": key, "site": w.get("zone") or key,
                                   "wlan_count": 0, "ssids": set(),
                                   "clients": 0})
        s["wlan_count"] += 1
        if w.get("ssid"):
            s["ssids"].add(w["ssid"])
        s["clients"] += int(w.get("clients") or 0)
    for key, s in sites.items():
        # Controller-side numClients is often 0 on 7.1.1 — use the live
        # client tally when it says more.
        s["clients"] = max(s["clients"], client_counts.get(key, 0))
        s["ssids"] = ", ".join(sorted(s["ssids"])[:6])
    return sorted(sites.values(), key=lambda s: s["site"].lower())


def _clients_per_site(ctx: FetcherContext, wlans: list[dict]) -> dict[str, int]:
    """{site key: connected clients} from query/client. Best-effort."""
    try:
        rows = smartzone_query_paged(ctx.connection, "query/client", ctx.config, [])
    except Exception:  # noqa: BLE001
        return {}
    ssid_to_site = {w["ssid"]: str(w.get("zone_id") or w.get("zone") or "unknown")
                    for w in wlans if w.get("ssid")}
    counts: dict[str, int] = {}
    for c in rows or []:
        key = str(c.get("zoneId") or c.get("zoneName") or "")
        if not key:
            key = ssid_to_site.get(str(c.get("ssid") or ""), "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    return {"sites": len(items),
            "total_wlans": sum(int(i.get("wlan_count") or 0) for i in items),
            "total_clients": sum(int(i.get("clients") or 0) for i in items)}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    """Site drill: list that site's WLANs."""
    try:
        rows = smartzone_query_paged(ctx.connection, "query/wlan", ctx.config, [])
    except Exception as exc:  # noqa: BLE001
        return {"identity": {"id": entity_id}, "error": str(exc)}
    wlans = [_normalize(r) for r in rows]
    mine = [w for w in wlans
            if str(w.get("zone_id") or w.get("zone")) == str(entity_id)]
    site = mine[0]["zone"] if mine else entity_id
    return {"identity": {"site": site, "wlan_count": len(mine)},
            "wlans": [{"ssid": w["ssid"], "vlan": w["vlan"], "auth": w["auth"],
                       "encryption": w["encryption"], "clients": w["clients"]}
                      for w in mine]}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}


def _normalize(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "ssid": row.get("name") or "-",
        "zone": row.get("zoneName"),
        "zone_id": row.get("zoneId"),
        "vlan": int(row.get("vlanId") or 0),
        "auth": row.get("authType"),
        "encryption": row.get("encryption"),
        "clients": int(row.get("numClients") or 0),
    }


register(ModuleSpec(
    slug="wlans", title="WLANs", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="wlans", title="WLANs"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("POST", "/query/wlan"),),
    supports_views=("table", "grid"),
    warmup=True,
    merge=merge,
    columns=(
        Column("Site", "site"),
        Column("WLANs", "wlan_count", "number"),
        Column("Clients Connected", "clients", "number"),
        Column("SSIDs", "ssids"),
    ),
))
