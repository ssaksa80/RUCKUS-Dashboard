"""Controller — SmartZone cluster + devices summary (singleton view).

7.1.1 ``cluster/state`` carries ``clusterName/clusterState`` plus a
``nodeStateList``; ``system/devicesSummary`` carries connected/total AP and
switch counts and capacity. KPIs come from those; the node list is the table."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, FetcherContext, ModuleSpec
from ..clients.smartzone import smartzone_get

POLL_SECONDS = 120
ICON = "\U0001F39B"  # control knobs emoji

_NODE_ONLINE = {"in_service", "online", "active", "up", "management_in_service",
                "service_ready"}


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    try:
        cluster = smartzone_get(ctx.connection, "cluster/state", ctx.config, None, [])
    except Exception:  # noqa: BLE001
        cluster = None
    try:
        devices = smartzone_get(
            ctx.connection, "system/devicesSummary", ctx.config, None, []
        )
    except Exception:  # noqa: BLE001
        devices = None

    nodes = (cluster or {}).get("nodeStateList") or []
    items = [
        {
            "id": n.get("nodeId") or n.get("nodeName"),
            "node": n.get("nodeName"),
            "state": n.get("nodeState"),
        }
        for n in nodes if isinstance(n, dict)
    ]
    return {"items": items, "cluster": cluster, "devices": devices}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    # Preserve cluster/devices (the default merge keeps only items, which would
    # zero out every KPI). Controller is effectively a single-cluster singleton.
    items: list[dict[str, Any]] = []
    cluster: dict | None = None
    devices: dict | None = None
    for r in results:
        items.extend(r.get("items", []))
        cluster = cluster or r.get("cluster")
        devices = devices or r.get("devices")
    return {"items": items, "cluster": cluster, "devices": devices}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    cluster = data.get("cluster") or {}
    devices = data.get("devices") or {}
    nodes = cluster.get("nodeStateList") or []
    online = sum(1 for n in nodes if isinstance(n, dict)
                 and str(n.get("nodeState") or "").lower() in _NODE_ONLINE)

    def _int(src: dict, key: str) -> int:
        try:
            return int(src.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    return {
        "cluster_state": cluster.get("clusterState") or "—",
        "nodes_online": online,
        "nodes_total": len(nodes),
        "aps_connected": _int(devices, "aps"),
        "total_aps": _int(devices, "totalAps"),
        "switches_connected": _int(devices, "switches"),
        "total_switches": _int(devices, "totalSwitches"),
    }


register(ModuleSpec(
    slug="controller", title="Controller", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=None,
    drill_tabs=(),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("GET", "/cluster/state"),),
    supports_views=("table",),
    warmup=True,
    merge=merge,
    columns=(
        Column("Node", "node"),
        Column("State", "state", "status"),
    ),
))
