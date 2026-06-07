"""API Explorer — searchable browser over the discovered OpenAPI op set.

Reads the already-discovered ``(METHOD, path)`` tuples from the request's
CapabilityGate. Makes no upstream calls during fetch — purely presents the
set produced by capability discovery. Hence ``warmup=False``.
"""
from __future__ import annotations
from typing import Any

from . import register
from ._base import FetcherContext, ModuleSpec

POLL_SECONDS = 600
ICON = "\U0001F9ED"  # 🧭

# Path fragments that mark a switch (SwitchM) op rather than a wireless one.
_SWITCH_MARKERS = ("/switch", "/traffic", "/vlan", "/stack", "/health", "/firmware")

# First-segment → friendly tag mapping. Default falls back to capitalized segment.
_TAG_MAP = {
    "rkszones": "Zones",
    "query": "Access Points",
    "switch": "Switches",
    "wlans": "WLANs",
    "aps": "Access Points",
    "clients": "Clients",
    "rogues": "Rogues",
    "alarms": "Alarms",
}


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    available = getattr(ctx.capability_gate, "available", None) or set()
    ops = sorted(available)
    items = [_normalize(method, path) for method, path in ops]
    items = _apply_filters(items, ctx.filters)
    return {"items": items, "raw_count": len(items)}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    wireless = sum(1 for i in items if i.get("source") == "wireless")
    switch = sum(1 for i in items if i.get("source") == "switch")
    by_method: dict[str, int] = {}
    for i in items:
        method = i.get("method", "")
        by_method[method] = by_method.get(method, 0) + 1
    return {
        "total_ops": len(items),
        "wireless_ops": wireless,
        "switch_ops": switch,
        "by_method": by_method,
    }


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    seen: dict[str, dict[str, Any]] = {}
    for r in results:
        for item in r.get("items", []):
            seen[item["id"]] = item
    items = sorted(seen.values(), key=lambda i: i["id"])
    return {"items": items, "raw_count": len(items)}


def _normalize(method: str, path: str) -> dict[str, Any]:
    return {
        "id": f"{method} {path}",
        "method": method,
        "path": path,
        "source": _classify(path),
        "tag": _tag(path),
    }


def _classify(path: str) -> str:
    lower = path.lower()
    if any(marker in lower for marker in _SWITCH_MARKERS):
        return "switch"
    return "wireless"


def _tag(path: str) -> str:
    segment = path.strip("/").split("/", 1)[0] if path.strip("/") else ""
    if not segment:
        return ""
    return _TAG_MAP.get(segment.lower(), segment.capitalize())


def _apply_filters(items: list[dict[str, Any]],
                   filters: dict | None) -> list[dict[str, Any]]:
    if not filters:
        return items
    source = filters.get("source")
    method = filters.get("method")
    search = filters.get("search")
    out = items
    if source:
        out = [i for i in out if i["source"] == source]
    if method:
        m = method.upper()
        out = [i for i in out if i["method"].upper() == m]
    if search:
        s = search.lower()
        out = [i for i in out if s in i["path"].lower()]
    return out


register(ModuleSpec(
    slug="api-explorer", title="API Explorer", group="Cross-cutting", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch, drill_fetcher=None, drill_tabs=(),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(),
    supports_views=("table",),
    warmup=False, merge=merge,
))
