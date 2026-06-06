"""Cross-platform connection dispatch.

``authenticate_connection`` is the single entry point used by the
``/connect`` route. It branches on the form's ``platform`` field and hands
off to the platform-specific authenticator. SmartZone vs RUCKUS One have
incompatible auth flows (serviceTicket vs OAuth client-credentials), so
keeping the dispatch tiny here lets the route stay platform-agnostic.
"""
from __future__ import annotations

from typing import Any


def authenticate_connection(form: Any, config: dict[str, Any]):
    platform = (form.get("platform") or "").strip().lower()
    if platform == "smartzone":
        from .smartzone import authenticate_smartzone
        return authenticate_smartzone(form, config)
    if platform == "ruckus_one":
        from .ruckus_one import authenticate_ruckus_one
        return authenticate_ruckus_one(form, config)
    raise ValueError("Select a supported RUCKUS management platform.")
