"""DSO Overview — tiles populated by the warmup SSE stream."""
from __future__ import annotations
from typing import Any

from . import register
from ._base import FetcherContext, ModuleSpec

POLL_SECONDS = 15
ICON = "\U0001F4E1"  # 📡


def fetch(ctx: FetcherContext) -> dict[str, Any]:
    return {"items": [], "_overview": True}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    return {}


def merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {"items": [], "_overview": True}


register(ModuleSpec(
    slug="overview", title="DSO Overview", group="Wireless", icon=ICON,
    poll_seconds=POLL_SECONDS,
    fetcher=fetch, drill_fetcher=None, drill_tabs=(),
    summary_fn=summary,
    requires_platforms=("smartzone",),
    requires_capabilities=(),
    supports_views=("table",),
    warmup=True, merge=merge,
))
