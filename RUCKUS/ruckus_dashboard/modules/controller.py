"""Controller — SmartZone cluster + devices + license summary (singleton view)."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import FetcherContext, ModuleSpec
from ..clients.smartzone import smartzone_get

POLL_SECONDS = 120
ICON = "\U0001F39B"  # control knobs emoji


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    cluster: dict | None = None
    devices: dict | None = None
    licenses: Any = None

    try:
        cluster = smartzone_get(ctx.connection, "cluster/state", ctx.config, None, [])
    except Exception:
        cluster = None
    try:
        devices = smartzone_get(
            ctx.connection, "system/devicesSummary", ctx.config, None, []
        )
    except Exception:
        devices = None
    try:
        licenses = smartzone_get(
            ctx.connection, "licensesSummary", ctx.config, None, []
        )
    except Exception:
        licenses = None

    return {
        "items": [],
        "cluster": cluster,
        "devices": devices,
        "licenses": licenses,
    }


def summary(data: dict[str, Any]) -> dict[str, Any]:
    cluster = data.get("cluster") or {}
    licenses = data.get("licenses") or {}

    rows: list[dict] = []
    if isinstance(licenses, dict):
        maybe = licenses.get("summary")
        if isinstance(maybe, list):
            rows = [r for r in maybe if isinstance(r, dict)]
    elif isinstance(licenses, list):
        rows = [r for r in licenses if isinstance(r, dict)]

    license_used = 0
    license_total = 0
    for row in rows:
        try:
            license_used += int(row.get("consumedCount") or 0)
        except (TypeError, ValueError):
            pass
        try:
            license_total += int(row.get("totalCount") or 0)
        except (TypeError, ValueError):
            pass

    nodes_online = 0
    nodes_total = 0
    if isinstance(cluster, dict):
        try:
            nodes_online = int(cluster.get("currentNodes") or 0)
        except (TypeError, ValueError):
            nodes_online = 0
        try:
            nodes_total = int(cluster.get("totalNodes") or 0)
        except (TypeError, ValueError):
            nodes_total = 0

    return {
        "nodes_online": nodes_online,
        "nodes_total": nodes_total,
        "license_used": license_used,
        "license_total": license_total,
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
    merge=None,
))
