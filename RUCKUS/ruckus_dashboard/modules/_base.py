"""ModuleSpec contract — every dashboard module declares one."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Callable, Any

VALID_GROUPS = {"Wireless", "Switching", "Cross-cutting"}
VALID_VIEWS = {"table", "grid", "heatmap", "chart", "tree"}
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
    kind: str = "text"     # text | status | bytes | uptime | number | link


@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    kind: str = "select"   # select | search


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
