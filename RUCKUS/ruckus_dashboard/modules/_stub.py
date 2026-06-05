"""Stub fetcher used by not-yet-implemented modules."""
from __future__ import annotations
from ._base import FetcherContext

STUB_MESSAGE = "Module not yet implemented — coming in a later plan."


def stub_fetcher(ctx: FetcherContext) -> dict:
    return {"items": [], "_stub": True, "_message": STUB_MESSAGE}


def stub_summary(data: dict) -> dict:
    return {"count": 0, "stub": True}
