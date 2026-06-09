"""Zones module."""
from __future__ import annotations
from typing import Any
from urllib.parse import quote

from . import register
from ._base import Column, FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import (
    smartzone_paged_get, smartzone_get, smartzone_post, smartzone_query_body,
)

POLL_SECONDS = 60
ICON = "\U0001F3E2"  # office-building emoji


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    # The /rkszones list is sparse (id + name). Country / firmware / mesh live in
    # the per-zone detail; AP counts come from one bulk AP query grouped by zone.
    rows = smartzone_paged_get(ctx.connection, "rkszones", ctx.config, debug=[])
    ap_by_zone = _ap_counts_by_zone(ctx)
    items = []
    for row in rows:
        zid = str(row.get("id") or row.get("zoneId") or "")
        detail = {}
        if zid:
            try:
                detail = smartzone_get(
                    ctx.connection, f"rkszones/{quote(zid)}", ctx.config, None, []
                ) or {}
            except Exception:  # noqa: BLE001 — detail is best-effort enrichment
                detail = {}
        items.append(_normalize(row, detail, ap_by_zone.get(zid, 0)))
    return {"items": items, "raw_count": len(rows)}


def _ap_counts_by_zone(ctx: FetcherContext) -> dict[str, int]:
    """One bulk /query/ap call → {zoneId: ap_count}. Best-effort."""
    try:
        resp = smartzone_post(ctx.connection, "query/ap", ctx.config,
                              smartzone_query_body(None), []) or {}
    except Exception:  # noqa: BLE001
        return {}
    counts: dict[str, int] = {}
    for ap in resp.get("list") or []:
        zid = str(ap.get("zoneId") or "")
        if zid:
            counts[zid] = counts.get(zid, 0) + 1
    return counts


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    return {"total": len(items),
            "total_aps": sum(int(i.get("ap_count") or 0) for i in items)}


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    try:
        # smartzone_get signature: (connection, path, config, params, debug)
        detail = smartzone_get(ctx.connection,
                               f"rkszones/{quote(entity_id)}",
                               ctx.config, None, [])
    except Exception as exc:
        return {"identity": {"id": entity_id}, "error": str(exc)}
    return {"identity": _normalize(detail or {}, detail or {}, 0), "raw": detail}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for r in results:
        items.extend(r.get("items", []))
    return {"items": items, "raw_count": len(items)}


def _mesh_mode(detail: dict) -> str | None:
    mesh = detail.get("mesh")
    if isinstance(mesh, dict):
        if "meshMode" in mesh:
            return mesh.get("meshMode")
        if "enabled" in mesh:
            return "Enabled" if mesh.get("enabled") else "Disabled"
    if isinstance(mesh, str):
        return mesh
    return detail.get("meshMode")


def _normalize(row: dict, detail: dict | None = None, ap_count: int = 0) -> dict:
    detail = detail or {}
    return {
        "id": row.get("id") or row.get("zoneId"),
        "name": row.get("name") or row.get("serviceName") or "-",
        "ap_count": ap_count,
        "fw": detail.get("version") or row.get("version") or row.get("firmwareVersion"),
        "country": detail.get("countryCode") or row.get("countryCode"),
        "mesh_mode": _mesh_mode(detail) or _mesh_mode(row),
        "description": detail.get("description") or row.get("description"),
    }


register(ModuleSpec(
    slug="zones", title="Zones", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS, fetcher=fetch, drill_fetcher=fetch_drill,
    drill_tabs=(TabSpec(slug="summary", title="Summary"),
                TabSpec(slug="raw", title="Raw")),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("GET", "/rkszones"),),
    supports_views=("table", "tree"),
    warmup=True, merge=merge,
    columns=(
        Column("Zone", "name"),
        Column("APs", "ap_count", "number"),
        Column("Firmware", "fw"),
        Column("Country", "country"),
        Column("Mesh", "mesh_mode"),
        Column("Description", "description"),
    ),
))
