"""Security module — validates the live AP inventory against CISA KEV + NVD CVE.

Live feed calls are slow and network-dependent, so the module honors
``config["RUCKUS_SECURITY_LOOKUPS"]``. When False, ``validate_assets`` marks
every asset "unknown" and performs NO network calls.
"""
from __future__ import annotations
from typing import Any

from . import register
from ._base import FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_query_paged
from ..security import SecurityLookupCache, validate_assets

POLL_SECONDS = 600
ICON = "\U0001F512"  # lock

_STATUSES = ("critical", "watch", "ok", "unknown")


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    try:
        rows = smartzone_query_paged(ctx.connection, "query/ap", ctx.config, debug=[])
    except Exception:
        return {"items": [], "raw_count": 0, "validation": {"status": "error"}}

    assets = [_build_asset(r) for r in rows or []]
    cache = SecurityLookupCache(int(ctx.config["RUCKUS_SECURITY_CACHE_SECONDS"]))
    validation = validate_assets(assets, ctx.config, cache)
    return {"items": assets, "raw_count": len(assets), "validation": validation}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    counts = {status: 0 for status in _STATUSES}
    for item in items:
        status = str((item.get("security") or {}).get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for r in results:
        items.extend(r.get("items", []))
    return {"items": items, "raw_count": len(items)}


def _build_asset(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("apMac"),
        "name": row.get("deviceName") or row.get("name") or "-",
        "model": row.get("model"),
        "firmware_version": row.get("firmwareVersion") or row.get("firmware"),
        "platform": "smartzone",
    }


register(ModuleSpec(
    slug="security", title="Security", group="Cross-cutting", icon=ICON,
    poll_seconds=POLL_SECONDS, fetcher=fetch,
    drill_fetcher=None,
    drill_tabs=(TabSpec(slug="summary", title="Summary"),
                TabSpec(slug="raw", title="Raw")),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(("POST", "/query/ap"),),
    supports_views=("table",),
    warmup=True, merge=merge,
))
