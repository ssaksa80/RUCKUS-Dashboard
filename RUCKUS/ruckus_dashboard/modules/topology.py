"""Topology — logical hierarchy map (controller → zones / switch-groups → switches).

SmartZone's public API exposes only per-device neighbor data, so this builds a
logical hierarchy from already-cached sources rather than physical L2 wiring."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import FetcherContext, ModuleSpec
from ..clients.smartzone import (
    smartzone_get, smartzone_paged_get, smartzone_query_paged,
)
from ..clients.switchm import fetch_switches, switch_manager_query

POLL_SECONDS = 60
ICON = "\U0001F578"  # spider web (map-like)

_ONLINE = {"online", "in_service", "connected", "run", "operational", "registered", "up"}
_OFFLINE = {"offline", "disconnected", "down", "gone", "unregistered"}

STATUS_COLORS = {"online": "#2ecc71", "flagged": "#f1c40f",
                 "offline": "#e74c3c", "unknown": "#7c8aa0"}


def _norm_status(raw: Any) -> str:
    r = str(raw or "").lower()
    if r in _ONLINE:
        return "online"
    if r in _OFFLINE:
        return "offline"
    if r in {"flagged", "warning", "degraded"}:
        return "flagged"
    return "unknown"


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    cluster = _safe(lambda: smartzone_get(ctx.connection, "cluster/state", ctx.config, None, []))
    zones = _safe(lambda: smartzone_paged_get(ctx.connection, "rkszones", ctx.config, debug=[])) or []
    aps = _safe(lambda: smartzone_query_paged(ctx.connection, "query/ap", ctx.config, [])) or []
    sw_resp = _safe(lambda: fetch_switches(ctx.connection, ctx.config)) or {}
    switches = sw_resp.get("switches") or []
    traffic_by_mac = _traffic_map(ctx)
    alarms_by_name = _alarm_counts(ctx)
    expand_raw = str((ctx.filters or {}).get("expand") or "")
    expand = {z for z in (p.strip() for p in expand_raw.split(",")) if z}
    # Per-AP average client signal — only worth the client pull when AP
    # leaves are actually being rendered (a zone is expanded).
    rssi_by_ap = _rssi_by_ap(ctx) if expand else {}
    return _build_graph(cluster, zones, aps, switches, traffic_by_mac,
                        alarms_by_name=alarms_by_name, expand=expand,
                        rssi_by_ap=rssi_by_ap)


def _rssi_by_ap(ctx) -> dict[str, int]:
    """{ap mac/name (lower): avg client rssi dBm}. Best-effort."""
    rows = _safe(lambda: smartzone_query_paged(
        ctx.connection, "query/client", ctx.config, [])) or []
    sums: dict[str, list[int]] = {}
    for c in rows:
        rssi = int(c.get("rssi") or 0)
        if not rssi:
            continue
        for key in (c.get("apMac"), c.get("apName")):
            if key:
                sums.setdefault(str(key).lower(), []).append(rssi)
    return {k: round(sum(v) / len(v)) for k, v in sums.items() if v}


def _alarm_counts(ctx) -> dict[str, int]:
    """Active alarm counts keyed by lowercase source name. Best-effort."""
    try:
        from ..clients.smartzone import smartzone_post, smartzone_query_body
        resp = smartzone_post(ctx.connection, "alert/alarm/list", ctx.config,
                              smartzone_query_body(None), []) or {}
    except Exception:  # noqa: BLE001
        return {}
    counts: dict[str, int] = {}
    for row in resp.get("list") or []:
        src = str(row.get("sourceName") or "").strip().lower()
        if src:
            counts[src] = counts.get(src, 0) + int(row.get("alarmCount") or 1)
    return counts


def _alarms_for(alarms_by_name: dict[str, int], *names) -> int:
    """Match a node to alarm sources by exact or substring name (both ways)."""
    total = 0
    for src, count in alarms_by_name.items():
        for name in names:
            n = str(name or "").strip().lower()
            if n and (n == src or n in src or src in n):
                total += count
                break
    return total


def _safe(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001 — each source is best-effort
        return None


def _traffic_map(ctx) -> dict:
    out: dict = {}
    data = _safe(lambda: switch_manager_query(ctx.connection, "traffic/top/usage", ctx.config)) or {}
    for r in (data.get("list") or []):
        if isinstance(r, dict):
            key = r.get("key") or r.get("id")
            if key:
                out[str(key).upper()] = int(r.get("value") or 0)
    return out


def _build_graph(cluster, zones, aps, switches, traffic_by_mac,
                 alarms_by_name=None, expand=frozenset(), rssi_by_ap=None):
    cluster = cluster or {}
    traffic_by_mac = traffic_by_mac or {}
    alarms_by_name = alarms_by_name or {}
    rssi_by_ap = rssi_by_ap or {}
    expand = set(expand or ())
    nodes: list[dict] = []
    edges: list[dict] = []

    def _escalate(status: str, alarm_count: int) -> str:
        return "flagged" if alarm_count and status == "online" else status

    ctrl_status = "online" if str(cluster.get("clusterState") or "").lower() in _ONLINE else "unknown"
    nodes.append({"id": "controller", "label": cluster.get("clusterName") or "Controller",
                  "type": "controller", "status": ctrl_status,
                  "meta": {"cluster_state": cluster.get("clusterState")}})

    # Zones with aggregated AP counts (raw rows kept for expansion).
    ap_rows_by_zone: dict[str, list[dict]] = {}
    for ap in aps or []:
        zid = str(ap.get("zoneId") or "")
        ap_rows_by_zone.setdefault(zid, []).append(ap)
    for z in zones or []:
        zid = str(z.get("id") or z.get("zoneId") or "")
        node_id = zid or (z.get("name") or "zone")
        rows = ap_rows_by_zone.get(zid, [])
        statuses = [_norm_status(r.get("status")) for r in rows]
        total = len(statuses)
        down = sum(1 for s in statuses if s == "offline")
        zstatus = "online" if total == 0 or down == 0 else ("offline" if down == total else "flagged")
        alarm_count = _alarms_for(alarms_by_name, z.get("name"))
        nodes.append({"id": node_id, "label": f"{z.get('name') or 'Zone'} ({total} APs)",
                      "type": "zone", "status": _escalate(zstatus, alarm_count),
                      "meta": {"ap_total": total, "ap_down": down,
                               "alarm_count": alarm_count}})
        edges.append({"source": "controller", "target": node_id, "status": zstatus, "label": ""})

        if node_id in expand and rows:
            # Offline APs first so problems are always within the cap.
            ordered = sorted(rows, key=lambda r: _norm_status(r.get("status")) != "offline")
            shown, extra = ordered[:60], len(ordered) - min(len(ordered), 60)
            for ap in shown:
                mac = ap.get("apMac") or ap.get("mac")
                astatus = _norm_status(ap.get("status"))
                a_alarms = _alarms_for(alarms_by_name, ap.get("deviceName"), mac)
                rssi = (rssi_by_ap.get(str(mac or "").lower())
                        or rssi_by_ap.get(str(ap.get("deviceName") or "").lower()))
                name = ap.get("deviceName") or mac
                label = f"{name} ({rssi} dB)" if rssi else name
                nodes.append({"id": mac, "label": label,
                              "type": "ap", "status": _escalate(astatus, a_alarms),
                              "meta": {"model": ap.get("model"),
                                       "ip": ap.get("ip") or ap.get("ipAddress"),
                                       "rssi_avg": rssi,
                                       "alarm_count": a_alarms}})
                edges.append({"source": node_id, "target": mac,
                              "status": astatus, "label": ""})
            if extra > 0:
                more_id = f"{node_id}-more"
                nodes.append({"id": more_id, "label": f"+{extra} more APs",
                              "type": "more", "status": "unknown", "meta": {}})
                edges.append({"source": node_id, "target": more_id,
                              "status": "unknown", "label": ""})

    # Switch groups/stacks + switch leaves.
    groups: dict[str, dict] = {}
    for sw in switches or []:
        gid = str(sw.get("groupId") or sw.get("stackId") or "ungrouped")
        gname = sw.get("groupName") or sw.get("stack") or "Switches"
        groups.setdefault(gid, {"name": gname, "switches": []})
        groups[gid]["switches"].append(sw)
    for gid, g in groups.items():
        child_statuses = [_norm_status(s.get("status")) for s in g["switches"]]
        gstatus = "online"
        if any(s == "offline" for s in child_statuses):
            gstatus = "flagged"
        if child_statuses and all(s == "offline" for s in child_statuses):
            gstatus = "offline"
        nodes.append({"id": gid, "label": f"{g['name']} ({len(g['switches'])})",
                      "type": "group", "status": gstatus, "meta": {}})
        edges.append({"source": "controller", "target": gid, "status": gstatus, "label": ""})
        for sw in g["switches"]:
            sid = sw.get("id") or sw.get("macAddress")
            mac = str(sid).upper() if sid else ""
            bytes_ = (traffic_by_mac.get(mac) or traffic_by_mac.get(str(sid))) if sid else None
            name = sw.get("switchName") or sw.get("name") or sid
            sstatus = _norm_status(sw.get("status"))
            alarm_count = _alarms_for(alarms_by_name, name, sid)
            nodes.append({"id": sid, "label": name,
                          "type": "switch", "status": _escalate(sstatus, alarm_count),
                          "meta": {"ip": sw.get("ipAddress"),
                                   "model": sw.get("model"),
                                   "fw": sw.get("firmwareVersion"),
                                   "traffic_bytes": bytes_,
                                   "alarm_count": alarm_count}})
            edges.append({"source": gid, "target": sid,
                          "status": sstatus,
                          "label": _human_bytes(bytes_) if bytes_ else ""})

    return {"nodes": nodes, "edges": edges,
            "legend": {"status": STATUS_COLORS}, "items": []}


def _human_bytes(n) -> str:
    v = float(n or 0)
    if v <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if v < 1024:
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} EB"


def summary(data: dict[str, Any]) -> dict[str, Any]:
    nodes = data.get("nodes", [])
    return {"nodes": len(nodes),
            "online": sum(1 for n in nodes if n.get("status") == "online"),
            "offline": sum(1 for n in nodes if n.get("status") == "offline"),
            "switches": sum(1 for n in nodes if n.get("type") == "switch")}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    # Single controller; preserve the full graph (default merge keeps only items).
    for r in results:
        if r.get("nodes"):
            return r
    return {"nodes": [], "edges": [], "legend": {"status": STATUS_COLORS}, "items": []}


register(ModuleSpec(
    slug="topology", title="Topology", group="Cross-cutting", icon=ICON,
    poll_seconds=POLL_SECONDS, fetcher=fetch, drill_fetcher=None, drill_tabs=(),
    summary_fn=summary, requires_platforms=("smartzone",),
    requires_capabilities=(("GET", "/cluster/state"),),
    supports_views=("graph", "flow"), warmup=True, merge=merge,
))
