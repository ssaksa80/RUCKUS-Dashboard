"""Headless data dump: capture everything the dashboard collects into one JSON."""
from __future__ import annotations
import time
from typing import Any

from . import APP_VERSION
from .modules import MODULES
from .modules._base import FetcherContext
from .infra.capability_gate import CapabilityGate
from .clients.base import RuckusClientError, _redact
from .clients.capabilities import discover_capabilities


def run_dump(connection, config: dict[str, Any]) -> dict[str, Any]:
    """Run discovery + every module fetcher + a sample drill. Returns a JSON-safe dict."""
    caps = _safe_capabilities(connection, config)
    available_ops = caps.get("available_ops") or set()
    gate = CapabilityGate(available=set(available_ops))

    modules_out: dict[str, Any] = {}
    for slug, spec in sorted(MODULES.items()):
        modules_out[slug] = _dump_module(slug, spec, connection, config, gate)

    return {
        "dumped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "app_version": APP_VERSION,
        "controller": {
            "platform": getattr(connection, "platform", ""),
            "version": getattr(connection, "controller_version", ""),
            "api_base": getattr(connection, "api_base", ""),
        },
        "capabilities": {
            "op_count": len(available_ops),
            "available_ops": sorted([list(op) for op in available_ops]),
        },
        "modules": modules_out,
    }


def _safe_capabilities(connection, config) -> dict[str, Any]:
    try:
        return discover_capabilities(connection, config) or {}
    except Exception as exc:  # noqa: BLE001
        return {"available_ops": set(), "error": str(exc)}


def _dump_module(slug, spec, connection, config, gate) -> dict[str, Any]:
    ctx = FetcherContext(connection=connection, config=config, filters=None,
                         capability_gate=gate,
                         connection_label=getattr(connection, "display_name", ""))
    entry: dict[str, Any] = {"status": "complete", "summary": None,
                             "item_count": 0, "items": [], "sample_drill": None,
                             "error": None}
    try:
        data = spec.fetcher(ctx)
    except RuckusClientError as exc:
        entry["status"] = "error"
        entry["error"] = _error_text(exc)
        return entry
    except Exception as exc:  # noqa: BLE001
        entry["status"] = "error"
        entry["error"] = str(exc)
        return entry

    items = data.get("items", []) if isinstance(data, dict) else []
    entry["items"] = _redact(items)
    entry["item_count"] = len(items)
    try:
        entry["summary"] = spec.summary_fn(data) if spec.summary_fn else None
    except Exception as exc:  # noqa: BLE001
        entry["summary"] = {"error": str(exc)}

    # sample drill on first item with an id
    if spec.drill_fetcher and items:
        first_id = None
        for it in items:
            if isinstance(it, dict) and it.get("id"):
                first_id = it["id"]
                break
        if first_id is not None:
            try:
                drill = spec.drill_fetcher(ctx, str(first_id))
                entry["sample_drill"] = {"entity_id": str(first_id), "data": _redact(drill)}
            except Exception as exc:  # noqa: BLE001
                entry["sample_drill"] = {"entity_id": str(first_id), "error": str(exc)}
    return entry


def _error_text(exc: RuckusClientError) -> str:
    msg = exc.message
    if isinstance(exc.debug, dict) and exc.debug.get("raw"):
        msg = f"{msg} :: {exc.debug['raw']}"
    return msg
