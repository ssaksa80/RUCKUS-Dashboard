"""Clients — wireless client inventory.

SmartZone 7.1.1 serves no per-client GET endpoint (the published
``clients/{mac}/operational/summary`` 404s); everything — list and drill —
derives from the proven ``POST query/client``."""
from __future__ import annotations
import time
from typing import Any

from . import register
from ._base import Column, Filter, FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_query_paged

POLL_SECONDS = 20
ICON = "\U0001F465"  # busts-in-silhouette emoji


def _zone_names(ctx: FetcherContext) -> dict[str, str]:
    """{zoneId: zoneName} so Site shows names, not GUIDs. Best-effort."""
    try:
        from ..clients.smartzone import smartzone_paged_get
        rows = smartzone_paged_get(ctx.connection, "rkszones", ctx.config, debug=[])
    except Exception:  # noqa: BLE001
        return {}
    return {str(z.get("id")): z.get("name")
            for z in rows or [] if z.get("id") and z.get("name")}


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    # Paginate — fabrics commonly exceed the 500-row single-page cap.
    rows = smartzone_query_paged(ctx.connection, "query/client", ctx.config, [])
    zone_names = _zone_names(ctx)
    items = [_normalize(r, zone_names) for r in rows]
    # raw_rows: first upstream rows (pre-normalize) so the dump exposes real keys.
    return {"items": items, "raw_count": len(rows), "raw_rows": rows[:2]}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    bands = {"2.4 GHz": 0, "5 GHz": 0, "6 GHz": 0}
    poor = 0
    top_name, top_bytes = "—", -1
    for i in items:
        band = i.get("band")
        if band in bands:
            bands[band] += 1
        if i.get("quality") == "poor":
            poor += 1
        total = int(i.get("rx_bytes") or 0) + int(i.get("tx_bytes") or 0)
        if total > top_bytes:
            top_bytes, top_name = total, i.get("hostname") or i.get("mac") or "—"
    return {"total": len(items),
            "band_2_4": bands["2.4 GHz"], "band_5": bands["5 GHz"],
            "band_6": bands["6 GHz"], "poor_signal": poor,
            "top_talker": top_name if items else "—"}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    """Drill from the list source: walk query/client, match the MAC."""
    target = str(entity_id).strip().lower()
    try:
        rows = smartzone_query_paged(ctx.connection, "query/client", ctx.config, [])
    except Exception as exc:  # noqa: BLE001
        return {"identity": {"mac": entity_id}, "error": str(exc)}
    row = next((r for r in rows
                if str(r.get("clientMac") or "").lower() == target), None)
    if row is None:
        return {"identity": {"mac": entity_id,
                             "note": "Client not currently connected."}}
    n = _normalize(row, _zone_names(ctx))
    return {
        "identity": {"hostname": n["hostname"], "mac": n["mac"],
                     "ip": n["ip"], "user": n["user"], "os": n["os"],
                     "site": n["site"], "site_id": n["site_id"]},
        "connection": {"ap": n["ap"], "ssid": n["ssid"], "band": n["band"],
                       "channel": n["channel"], "vlan": n["vlan"],
                       "rssi": n["rssi"], "snr": n["snr"],
                       "quality": n["quality"]},
        "usage": {"rx_bytes": n["rx_bytes"], "tx_bytes": n["tx_bytes"],
                  "session": n["session"]},
        "raw": row,
    }


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items, raw = [], 0
    for r in results:
        items.extend(r.get("items", []))
        raw += int(r.get("raw_count", 0))
    return {"items": items, "raw_count": raw}


def _band(row: dict) -> str:
    text = " ".join(str(row.get(k) or "") for k in
                    ("radioType", "radioMode", "band", "radio")).lower()
    if "6g" in text or "(6" in text or text.strip() == "6":
        return "6 GHz"
    if "5" in text:
        return "5 GHz"
    if "2.4" in text or "24g" in text or "11g" in text or "11b" in text:
        return "2.4 GHz"
    # Live 7.1.1 radioType strings often carry no band digit ("11ax") — fall
    # back to the channel number, which the controller always reports.
    try:
        channel = int(row.get("channel") or 0)
    except (TypeError, ValueError):
        channel = 0
    if channel:
        return "2.4 GHz" if channel <= 14 else "5 GHz"
    return "—"


def _quality(rssi: int) -> str:
    if not rssi:
        return "unknown"
    if rssi < 0:  # dBm
        if rssi >= -65:
            return "good"
        return "fair" if rssi >= -75 else "poor"
    # positive scale (SNR-like)
    if rssi >= 25:
        return "good"
    return "fair" if rssi >= 15 else "poor"


def _session(row: dict) -> str:
    start = row.get("sessionStartTime") or row.get("connectionTime") or 0
    try:
        start = float(start)
    except (TypeError, ValueError):
        return "—"
    if start > 1e12:  # epoch ms
        secs = max(0, time.time() - start / 1000.0)
        d, rem = divmod(int(secs), 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        if d:
            return f"{d}d {h}h"
        return f"{h}h {m}m" if h else f"{m}m"
    return str(row.get("connectionTime") or "—")


def _normalize(row: dict, zone_names: dict[str, str] | None = None) -> dict:
    zone_names = zone_names or {}
    mac = row.get("clientMac")
    rssi = int(row.get("rssi") or 0)
    site_id = str(row.get("zoneId") or "")
    site = (row.get("zoneName") or zone_names.get(site_id)
            or site_id or row.get("domainName"))
    return {
        "id": mac,
        "mac": mac,
        "hostname": row.get("hostname") or "-",
        "ip": row.get("ipAddress"),
        "user": row.get("userName") or row.get("username"),
        "ssid": row.get("ssid"),
        "ap": row.get("apName") or row.get("apMac"),
        "site": site,
        "site_id": site_id,
        "band": _band(row),
        "channel": row.get("channel"),
        "vlan": row.get("vlanId") or row.get("vlan"),
        "rssi": rssi,
        "snr": row.get("snr"),
        "quality": _quality(rssi),
        "rx_bytes": int(row.get("rxBytes") or 0),
        "tx_bytes": int(row.get("txBytes") or 0),
        "os": row.get("osType"),
        "auth_method": row.get("authMethod"),
        "session": _session(row),
    }


register(ModuleSpec(
    slug="clients", title="Clients", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="connection", title="Connection"),
        TabSpec(slug="usage", title="Usage"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("POST", "/query/client"),),
    supports_views=("table", "grid"),
    warmup=True,
    merge=merge,
    columns=(
        Column("Host", "hostname"),
        Column("MAC", "mac"),
        Column("IP", "ip"),
        Column("User", "user"),
        Column("SSID", "ssid"),
        Column("AP", "ap"),
        Column("Site", "site"),
        Column("Band", "band"),
        Column("Ch", "channel", "number"),
        Column("VLAN", "vlan", "number"),
        Column("Quality", "quality", "status"),
        Column("RX", "rx_bytes", "bytes"),
        Column("TX", "tx_bytes", "bytes"),
        Column("OS", "os"),
    ),
    filters=(
        Filter("ssid", "SSID", "select"),
        Filter("os", "OS", "select"),
        Filter("band", "Band", "select"),
        Filter("quality", "Quality", "select"),
        Filter("ap", "AP", "select"),
        Filter("site", "Site", "select"),
    ),
))
