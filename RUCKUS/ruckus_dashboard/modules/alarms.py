"""Alarms — SmartZone alarm inventory + severity summary."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import Column, Filter, FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_post, smartzone_query_body

POLL_SECONDS = 10
ICON = "\U0001F6A8"  # police-light/alarm emoji

_SEVERITIES = ("critical", "major", "minor", "warning")


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    list_payload = _build_query(ctx.filters)
    # SmartZone 7.x serves the alarm list at /alert/alarm/list (query/alarm 404s).
    # /alert/alarmSummary returns all-zero counts on 7.1.1, so KPIs are derived
    # from the list rows instead (see summary()).
    list_resp = smartzone_post(
        ctx.connection, "alert/alarm/list", ctx.config, list_payload, []
    )
    list_resp = list_resp or {}
    rows = list_resp.get("list") or []
    items = [_normalize(r) for r in rows]
    return {"items": items}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items", [])
    counts = {sev: 0 for sev in _SEVERITIES}
    total = 0
    for item in items:
        sev = str(item.get("severity") or "").lower()
        cnt = int(item.get("count") or 1)
        total += cnt
        if sev in counts:
            counts[sev] += cnt
    counts["total"] = total
    return counts


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    # Alarm objects are returned in full by /alert/alarm/list; SmartZone does not
    # expose a per-alarm detail endpoint. Provide a minimal identity payload
    # so the drill route has a uniform shape across modules.
    return {"identity": {"id": entity_id}, "raw": None}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for r in results:
        items.extend(r.get("items", []))
    return {"items": items}


def _build_query(filters: dict | None) -> dict:
    return smartzone_query_body(filters)


def _normalize(row: dict) -> dict:
    # Live 7.1.1 rows vary in which identity/ack keys they populate.
    source = (row.get("sourceName") or row.get("entityName")
              or row.get("apName") or row.get("switchName")
              or row.get("deviceName") or row.get("entityId"))
    ack = (row.get("ackState") or row.get("acknowledged")
           or row.get("ackStatus"))
    if isinstance(ack, bool):
        ack = "acked" if ack else "unacked"
    return {
        "id": row.get("alarmId"),
        "severity": str(row.get("severity") or "").lower(),
        "category": row.get("category"),
        "source": source,
        "message": row.get("alarmType") or row.get("activityDesc"),
        "first_seen": row.get("firstAppearTime"),
        "last_seen": row.get("lastAppearTime"),
        "ack_state": str(ack).lower() if ack else "unacked",
        "count": int(row.get("alarmCount") or 1),
    }


register(ModuleSpec(
    slug="alarms", title="Alarms", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch,
    drill_fetcher=fetch_drill,
    drill_tabs=(
        TabSpec(slug="summary", title="Summary"),
        TabSpec(slug="raw", title="Raw"),
    ),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(
        ("POST", "/alert/alarm/list"),
    ),
    supports_views=("table", "grid"),
    warmup=True,
    merge=merge,
    columns=(
        Column("Severity", "severity", "status"),
        Column("Category", "category"),
        Column("Source", "source"),
        Column("Message", "message"),
        Column("Ack", "ack_state"),
        Column("Count", "count", "number"),
    ),
    filters=(
        Filter("severity", "Severity", "select"),
        Filter("category", "Category", "select"),
    ),
))
