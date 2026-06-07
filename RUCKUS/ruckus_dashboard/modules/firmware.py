"""Firmware module — per-zone AP firmware catalog + compliance posture."""
from __future__ import annotations
from typing import Any
from urllib.parse import quote

from . import register
from ._base import FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_paged_get, smartzone_get

POLL_SECONDS = 120
ICON = "\U0001F4BE"  # floppy disk


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    try:
        zones = smartzone_paged_get(ctx.connection, "rkszones", ctx.config, debug=[])
    except Exception:
        return {"items": [], "raw_count": 0}

    items = []
    for zone in zones or []:
        zone_id = str(zone.get("id") or zone.get("zoneId") or "")
        zone_name = zone.get("name") or zone.get("serviceName") or zone_id
        if not zone_id:
            continue
        catalog = _fetch_catalog(ctx, zone_id)
        items.append({
            "id": zone_id,
            "zone_id": zone_id,
            "zone_name": zone_name,
            "latest_supported": _latest_supported(catalog),
            "catalog": catalog,
        })
    return {"items": items, "raw_count": len(items)}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    supported = 0
    unsupported = 0
    for zone in items:
        for entry in zone.get("catalog", []):
            if entry.get("supported"):
                supported += 1
            else:
                unsupported += 1
    return {
        "total_zones": len(items),
        "total_supported_versions": supported,
        "unsupported_count": unsupported,
    }


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    return {"identity": {"id": entity_id}, "catalog": _fetch_catalog(ctx, entity_id)}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for r in results:
        items.extend(r.get("items", []))
    return {"items": items, "raw_count": len(items)}


def _fetch_catalog(ctx: FetcherContext, zone_id: str) -> list[dict[str, Any]]:
    try:
        raw = smartzone_get(ctx.connection,
                            f"rkszones/{quote(zone_id)}/apFirmware",
                            ctx.config, None, [])
    except Exception:
        return []
    rows = (raw or {}).get("supportedAPFirmwareList") or (raw or {}).get("list") or []
    return [
        {"version": r.get("firmwareVersion") or r.get("version"),
         "supported": bool(r.get("supported", True))}
        for r in rows
        if (r.get("firmwareVersion") or r.get("version"))
    ]


def _latest_supported(catalog: list[dict[str, Any]]) -> str:
    supported = [c["version"] for c in catalog if c.get("supported") and c.get("version")]
    if not supported:
        return ""
    return max(supported, key=_version_key)


def _version_key(version: str) -> tuple[int, ...]:
    parts = []
    for chunk in str(version).replace("-", ".").split("."):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts)


register(ModuleSpec(
    slug="firmware", title="Firmware", group="Cross-cutting", icon=ICON,
    poll_seconds=POLL_SECONDS, fetcher=fetch, drill_fetcher=fetch_drill,
    drill_tabs=(TabSpec(slug="summary", title="Summary"),
                TabSpec(slug="raw", title="Raw")),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("GET", "/rkszones"),),
    supports_views=("table",),
    warmup=True, merge=merge,
))
