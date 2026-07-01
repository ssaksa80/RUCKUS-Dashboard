"""Generic, registry-driven report collection.

Walks ``all_modules()``, runs each fetcher under the live capability gate with
a per-module timeout, adapts the payload shape to rows, applies the operator's
filters generically (mirroring ``dashboard.js:_applyFilters``), projects to the
module's declared columns, and harvests summary KPIs, a raw field-map sample,
and a small drill sample. Produces a pure ``ReportModel`` (reports/model.py).

A thin ``collect_report_data`` wrapper preserves the legacy 4-domain dict the
alert path consumes (``state_from_data``)."""
from __future__ import annotations

import concurrent.futures
import logging
import time
from typing import Any, Iterable

from .model import ColumnSpec, DrillSample, ModuleReport, ReportModel

LOG = logging.getLogger("ruckus.reports")


def _matches_range(row: dict, col: str, val: Any) -> bool:
    """Range predicate: {min, max} over Number(row[col]) — mirrors JS range:."""
    lo = val.get("min")
    hi = val.get("max")
    lo = None if lo in ("", None) else _to_number(lo)
    hi = None if hi in ("", None) else _to_number(hi)
    if lo is None and hi is None:
        return True
    n = _to_number(row.get(col))
    if n is None:
        return False
    if lo is not None and n < lo:
        return False
    if hi is not None and n > hi:
        return False
    return True


def _to_number(value: Any):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def apply_filter(rows: list[dict], filters: dict) -> list[dict]:
    """Filter ``rows`` by ``filters``, mirroring ``dashboard.js:_applyFilters``.

    Parity with the SP1 client-side predicate (``static/dashboard.js``):
    - empty/None values (and empty lists) are ignored;
    - ``__search`` matches a case-insensitive substring over all stringified
      values of a row;
    - ``search:<col>`` matches a case-insensitive substring over one column;
    - ``range:<col>`` matches ``{min, max}`` against ``Number(row[col])``;
    - a list value is a multi-select: the row passes if ``row[key]`` is one of
      the selected values;
    - every other key requires an exact string match against ``row[key]``
      ("" when the key is absent).
    """
    active = {
        k: v for k, v in (filters or {}).items()
        if v not in ("", None) and not (isinstance(v, list) and len(v) == 0)
    }
    if not active:
        return list(rows)
    out: list[dict] = []
    for row in rows:
        keep = True
        for key, val in active.items():
            if key == "__search":
                hay = " ".join(str(v if v is not None else "")
                               for v in row.values()).lower()
                if str(val).lower() not in hay:
                    keep = False
                    break
            elif isinstance(key, str) and key.startswith("search:"):
                col = key[7:]
                cell = str(row.get(col, "") if row.get(col) is not None else "")
                if str(val).lower() not in cell.lower():
                    keep = False
                    break
            elif isinstance(key, str) and key.startswith("range:"):
                if isinstance(val, dict) and not _matches_range(row, key[6:], val):
                    keep = False
                    break
            elif isinstance(val, list):
                cell = str(row.get(key, "") if row.get(key) is not None else "")
                if cell not in [str(v) for v in val]:
                    keep = False
                    break
            elif str(row.get(key, "") if row.get(key) is not None else "") != str(val):
                keep = False
                break
        if keep:
            out.append(row)
    return out


def project_columns(rows: list[dict],
                    columns: list[ColumnSpec]) -> list[dict]:
    """Keep only ``columns`` keys (label order), always passing through ``id``.

    With no columns the rows pass through unchanged (e.g. graph modules that
    declare none)."""
    if not columns:
        return list(rows)
    keys: list[str] = ["id"] + [c.key for c in columns if c.key != "id"]
    out: list[dict] = []
    for row in rows:
        projected: dict[str, Any] = {}
        for k in keys:
            if k == "id" and "id" not in row:
                continue
            if k in row:
                projected[k] = row[k]
        out.append(projected)
    return out


def _rows_from_payload(payload: dict,
                       *, raw_n: int) -> tuple[list[dict], int, list[dict], str | None]:
    """Adapt a fetcher payload to ``(rows, row_total, raw_samples, note)``.

    Handles the real variants:
      * topology graph ``{"nodes":[...], "edges":[...], "items":[]}`` -> node rows
      * overview ``{"items":[], "_overview":True}`` -> empty + note
      * ``{"items":[...], "raw_count":N, "raw_rows":[...]}`` -> items
      * ``{"items":[...]}`` -> items, total = len(items)
    """
    payload = payload or {}
    if payload.get("nodes") is not None and "items" in payload:
        nodes = list(payload.get("nodes") or [])
        return nodes, len(nodes), nodes[:raw_n], "graph module — node list"
    if payload.get("_overview"):
        return [], 0, [], "overview tiles (warmup-driven), no list"
    items = list(payload.get("items") or [])
    raw_count = payload.get("raw_count")
    total = int(raw_count) if raw_count is not None else len(items)
    raw_rows = payload.get("raw_rows")
    raw = list(raw_rows) if raw_rows else items[:raw_n]
    return items, total, raw, None


def _error_message(exc: Exception, config: dict) -> str:
    """Error text for the report. Appends the controller's raw body only when
    ``RUCKUS_SHOW_DEBUG`` is set — mirror of routes/modules.py:_upstream_message,
    so the report never leaks upstream bodies by default."""
    from ..clients.base import RuckusClientError
    message = str(getattr(exc, "message", None) or exc)
    if (config or {}).get("RUCKUS_SHOW_DEBUG") and isinstance(exc, RuckusClientError):
        debug = exc.debug if isinstance(exc.debug, dict) else {}
        raw = debug.get("raw")
        if raw:
            message = f"{message} :: {raw}"
    return message


def _error_dict(exc: Exception, label: str, slug: str, config: dict) -> dict:
    from ..clients.base import RuckusClientError
    status = exc.status_code if isinstance(exc, RuckusClientError) else 502
    return {"connection": label, "endpoint": slug,
            "message": _error_message(exc, config), "status": status}


def _collect_module(spec, ctx, *, gate, filters: dict,
                    drill_n: int, raw_n: int) -> ModuleReport:
    """Harvest one module into a ``ModuleReport``. Never raises."""
    columns = [ColumnSpec(c.label, c.key, c.kind) for c in spec.columns]
    rep = ModuleReport(slug=spec.slug, title=spec.title, group=spec.group,
                       status="ok", columns=columns,
                       filters_applied=dict(filters or {}))

    if not gate.satisfied(spec.requires_capabilities):
        rep.status = "disabled"
        rep.note = "module unavailable on this controller"
        return rep

    try:
        payload = spec.fetcher(ctx) or {}
    except Exception as exc:  # noqa: BLE001 — one module never aborts the report
        LOG.warning("report: %s fetch failed", spec.slug)
        rep.status = "error"
        rep.errors.append(_error_dict(exc, ctx.connection_label, spec.slug,
                                      ctx.config))
        return rep

    all_rows, total, raw_samples, note = _rows_from_payload(payload, raw_n=raw_n)
    try:
        rep.summary = spec.summary_fn(payload) or {}
    except Exception:  # noqa: BLE001
        rep.summary = {}
    rep.row_total = total
    rep.raw_samples = raw_samples
    if note:
        rep.note = note

    filtered = apply_filter(all_rows, filters or {})
    rep.rows = project_columns(filtered, columns)

    if spec.drill_fetcher is not None and drill_n > 0:
        for row in filtered:
            if len(rep.drill_samples) >= drill_n:
                break
            ident = row.get("id")
            if ident in (None, ""):
                continue
            try:
                sections = spec.drill_fetcher(ctx, str(ident)) or {}
                rep.drill_samples.append(
                    DrillSample(entity_id=str(ident), sections=sections))
            except Exception as exc:  # noqa: BLE001
                rep.drill_samples.append(
                    DrillSample(entity_id=str(ident),
                                error=_error_message(exc, ctx.config)))
    return rep


def collect_report_model(
    connection, config: dict, *,
    available_ops: set[tuple[str, str]],
    slugs: Iterable[str] | None = None,
    filters_by_slug: dict[str, dict[str, str]] | None = None,
    drill_sample_size: int = 3,
    raw_sample_size: int = 2,
    per_module_timeout: float = 20.0,
    max_workers: int = 4,
) -> ReportModel:
    """Collect a ``ReportModel`` over the registry (or a slug subset).

    ``slugs=None`` => every module in ``all_modules()`` order. Each module runs
    under a real ``CapabilityGate(available_ops)`` with a per-module timeout
    enforced via ``future.result(timeout=...)`` (a slow module bounds its own
    slot)."""
    from ..modules import all_modules
    from ..modules._base import FetcherContext
    from ..infra.capability_gate import CapabilityGate

    gate = CapabilityGate(available=set(available_ops or set()))
    filters_by_slug = filters_by_slug or {}
    ordered = all_modules()
    if slugs is not None:
        wanted = set(slugs)
        ordered = [s for s in ordered if s.slug in wanted]

    label = getattr(connection, "display_name", "") or ""
    model = ReportModel(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        connection_label=label, modules=[])

    def _run(spec) -> ModuleReport:
        ctx = FetcherContext(connection=connection, config=config,
                             filters=filters_by_slug.get(spec.slug),
                             capability_gate=gate, connection_label=label)
        return _collect_module(spec, ctx, gate=gate,
                               filters=filters_by_slug.get(spec.slug) or {},
                               drill_n=drill_sample_size, raw_n=raw_sample_size)

    if not ordered:
        return model

    results: dict[str, ModuleReport] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_spec = {pool.submit(_run, spec): spec for spec in ordered}
        for future, spec in future_to_spec.items():
            try:
                results[spec.slug] = future.result(timeout=per_module_timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                results[spec.slug] = ModuleReport(
                    slug=spec.slug, title=spec.title, group=spec.group,
                    status="error", note="timed out",
                    columns=[ColumnSpec(c.label, c.key, c.kind)
                             for c in spec.columns])
            except Exception as exc:  # noqa: BLE001 — defensive
                LOG.warning("report: %s crashed", spec.slug)
                results[spec.slug] = ModuleReport(
                    slug=spec.slug, title=spec.title, group=spec.group,
                    status="error",
                    errors=[{"connection": label, "endpoint": spec.slug,
                             "message": str(exc), "status": 502}])

    model.modules = [results[spec.slug] for spec in ordered]
    return model


_LEGACY_SLUGS = ("aps", "clients", "alarms", "switches")


def collect_report_data(connection, config: dict) -> dict[str, Any]:
    """Backward-compatible shim for the alert path.

    Returns the legacy ``{"aps":[...], "clients":[...], "alarms":[...],
    "switches":[...]}`` dict (full normalized rows, not column-projected) so
    ``notify.scheduler.state_from_data`` is untouched. Implemented over
    ``collect_report_model`` so alerts and reports share one collector."""
    from ..modules import MODULES
    from ..modules._base import FetcherContext
    from ..infra.capability_gate import CapabilityGate

    gate = CapabilityGate(available=set())
    out: dict[str, Any] = {}
    for slug in _LEGACY_SLUGS:
        spec = MODULES.get(slug)
        if spec is None:
            out[slug] = []
            continue
        ctx = FetcherContext(connection=connection, config=config, filters=None,
                             capability_gate=gate,
                             connection_label=getattr(connection,
                                                      "display_name", ""))
        try:
            payload = spec.fetcher(ctx) or {}
            out[slug] = list(payload.get("items") or [])
        except Exception:  # noqa: BLE001
            LOG.exception("report(legacy): %s fetch failed", slug)
            out[slug] = []
    return out
