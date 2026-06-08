"""Alarms — SmartZone alarm inventory + severity summary."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import FetcherContext, ModuleSpec, TabSpec
from ..clients.smartzone import smartzone_post, smartzone_query_body

POLL_SECONDS = 10
ICON = "\U0001F6A8"  # police-light/alarm emoji

_SEVERITIES = ("critical", "major", "minor", "warning")


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    # /alert/alarmSummary returns a flat dict of severity counts, not a {"list": ...} envelope.
    summary_resp = smartzone_post(
        ctx.connection, "alert/alarmSummary", ctx.config, {}, []
    )
    summary_raw = _normalize_summary(summary_resp)

    list_payload = _build_query(ctx.filters)
    list_resp = smartzone_post(
        ctx.connection, "query/alarm", ctx.config, list_payload, []
    )
    list_resp = list_resp or {}
    rows = list_resp.get("list") or []
    items = [_normalize(r) for r in rows]
    return {"items": items, "summary_raw": summary_raw}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("summary_raw")
    if isinstance(raw, dict):
        critical = int(raw.get("critical") or 0)
        major = int(raw.get("major") or 0)
        minor = int(raw.get("minor") or 0)
        warning = int(raw.get("warning") or 0)
        total = int(raw.get("total") or (critical + major + minor + warning))
        return {"critical": critical, "major": major, "minor": minor,
                "warning": warning, "total": total}
    items = data.get("items", [])
    counts = {sev: 0 for sev in _SEVERITIES}
    for item in items:
        sev = str(item.get("severity") or "").lower()
        if sev in counts:
            counts[sev] += 1
    counts["total"] = len(items)
    return counts


def fetch_drill(ctx: FetcherContext, entity_id: str) -> dict[str, Any]:
    # Alarm objects are returned in full by /query/alarm; SmartZone does not
    # expose a per-alarm detail endpoint. Provide a minimal identity payload
    # so the drill route has a uniform shape across modules.
    return {"identity": {"id": entity_id}, "raw": None}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    totals = {sev: 0 for sev in _SEVERITIES}
    total = 0
    have_summary = False
    for r in results:
        items.extend(r.get("items", []))
        raw = r.get("summary_raw")
        if isinstance(raw, dict):
            have_summary = True
            for sev in _SEVERITIES:
                totals[sev] += int(raw.get(sev) or 0)
            total += int(raw.get("total") or 0)
    summary_raw: dict[str, Any] | None = None
    if have_summary:
        summary_raw = dict(totals)
        summary_raw["total"] = total or sum(totals.values())
    return {"items": items, "summary_raw": summary_raw}


def _build_query(filters: dict | None) -> dict:
    return smartzone_query_body(filters)


def _normalize_summary(resp: Any) -> dict[str, Any] | None:
    if not isinstance(resp, dict):
        return None
    # Accept either flat dict or one wrapped in {"summary": {...}}.
    source = resp.get("summary") if isinstance(resp.get("summary"), dict) else resp
    critical = int(source.get("critical") or source.get("Critical") or 0)
    major = int(source.get("major") or source.get("Major") or 0)
    minor = int(source.get("minor") or source.get("Minor") or 0)
    warning = int(source.get("warning") or source.get("Warning") or 0)
    total = int(source.get("total") or source.get("Total")
                or (critical + major + minor + warning))
    return {"critical": critical, "major": major, "minor": minor,
            "warning": warning, "total": total}


def _normalize(row: dict) -> dict:
    ack = row.get("ackState")
    return {
        "id": row.get("alarmId"),
        "severity": str(row.get("severity") or "").lower(),
        "category": row.get("category"),
        "source": row.get("sourceName"),
        "message": row.get("alarmType"),
        "first_seen": row.get("firstAppearTime"),
        "last_seen": row.get("lastAppearTime"),
        "ack_state": ack.lower() if ack else "",
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
        ("POST", "/alert/alarmSummary"),
        ("POST", "/query/alarm"),
    ),
    supports_views=("table", "grid"),
    warmup=True,
    merge=merge,
))
