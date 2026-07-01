"""ModuleSpec contract — every dashboard module declares one."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Callable, Any

VALID_GROUPS = {"Wireless", "Switching", "Cross-cutting"}
VALID_VIEWS = {"table", "grid", "heatmap", "chart", "tree", "graph"}
VALID_PLATFORMS = {"smartzone", "ruckus_one"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class FetcherContext:
    connection: Any           # ConnectionConfig
    config: dict
    filters: dict | None
    capability_gate: Any      # CapabilityGate
    connection_label: str


@dataclass(frozen=True)
class TabSpec:
    slug: str
    title: str
    fetcher: Callable[[FetcherContext, str], dict] | None = None


@dataclass(frozen=True)
class Column:
    label: str
    key: str
    kind: str = "text"          # text | status | bytes | uptime | number | link | rate
    filterable: bool = True     # set False to suppress a filter for this column
    filter_kind: str | None = None    # override inferred control: select|search|range|none
    server_filter: str | None = None  # push-down token, e.g. "ZONE_ID"; None = client-only


@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    kind: str = "select"        # select | search | range
    server_filter: str | None = None


# Column.kind -> inferred filter control. status enumerates, text/link search,
# numeric-ish columns use a min/max range.
_FILTER_KIND_BY_COLUMN_KIND = {
    "status": "select",
    "text": "search",
    "link": "search",
    "number": "range",
    "bytes": "range",
    "rate": "range",
    "uptime": "range",
}


def _infer_filter_kind(column_kind: str) -> str:
    """Map a Column.kind to a filter control kind (default: search)."""
    return _FILTER_KIND_BY_COLUMN_KIND.get(column_kind, "search")


def resolve_filters(
    columns: tuple[Column, ...],
    overrides: tuple[Filter, ...],
) -> tuple[Filter, ...]:
    """Derive the universal filter set from columns, applying overrides.

    - Every filterable column yields one Filter; kind is inferred from
      Column.kind unless Column.filter_kind overrides it.
    - filterable=False or filter_kind="none" suppresses the column's filter.
    - An explicit Filter in ``overrides`` whose key matches a column replaces
      the derived one (label/kind/server_filter win). Explicit filters with no
      matching column are appended in declaration order.
    """
    override_by_key = {f.key: f for f in overrides}
    resolved: list[Filter] = []
    seen: set[str] = set()
    for col in columns:
        if not col.filterable or col.filter_kind == "none":
            continue
        if col.key in override_by_key:
            resolved.append(override_by_key[col.key])
        else:
            kind = col.filter_kind or _infer_filter_kind(col.kind)
            resolved.append(Filter(key=col.key, label=col.label, kind=kind,
                                   server_filter=col.server_filter))
        seen.add(col.key)
    for f in overrides:
        if f.key not in seen:
            resolved.append(f)
            seen.add(f.key)
    return tuple(resolved)


@dataclass(frozen=True)
class ModuleSpec:
    slug: str
    title: str
    group: str
    icon: str
    poll_seconds: int
    fetcher: Callable[[FetcherContext], dict]
    drill_fetcher: Callable[[FetcherContext, str], dict] | None
    drill_tabs: tuple[TabSpec, ...]
    summary_fn: Callable[[dict], dict]
    requires_platforms: tuple[str, ...]
    requires_capabilities: tuple[tuple[str, str], ...]
    supports_views: tuple[str, ...]
    warmup: bool = True
    merge: Callable[[list[dict]], dict] | None = None
    columns: tuple[Column, ...] = ()
    filters: tuple[Filter, ...] = ()
    resolved_filters: tuple[Filter, ...] = field(default=(), init=False, compare=False)

    def __post_init__(self) -> None:
        if not SLUG_RE.match(self.slug):
            raise ValueError(f"ModuleSpec.slug must be kebab-case: {self.slug!r}")
        if self.group not in VALID_GROUPS:
            raise ValueError(f"ModuleSpec.group must be one of {VALID_GROUPS}: {self.group!r}")
        for view in self.supports_views:
            if view not in VALID_VIEWS:
                raise ValueError(f"unknown view {view!r}; allowed: {VALID_VIEWS}")
        for platform in self.requires_platforms:
            if platform not in VALID_PLATFORMS:
                raise ValueError(f"unknown platform {platform!r}; allowed: {VALID_PLATFORMS}")
        if self.poll_seconds < 5:
            raise ValueError("poll_seconds must be >= 5")
        object.__setattr__(self, "resolved_filters",
                           resolve_filters(self.columns, self.filters))
