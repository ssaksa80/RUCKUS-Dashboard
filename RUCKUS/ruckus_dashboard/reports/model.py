"""Pure, serializable report model — no openpyxl, no Flask.

``collect_report_model`` (reports/collect.py) produces a ``ReportModel``;
``reports/excel.py`` and the per-tab route render from it. Keeping the model
free of I/O lets both the collector and the renderers be unit-tested without
SMTP or a workbook."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ColumnSpec:
    """Decoupled mirror of ``modules._base.Column`` (label + key + kind)."""
    label: str
    key: str
    kind: str = "text"


@dataclass
class DrillSample:
    """One entity's drill payload (``drill_fetcher`` output), or an error."""
    entity_id: str
    sections: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ModuleReport:
    slug: str
    title: str
    group: str
    status: str                              # "ok" | "disabled" | "error"
    columns: list[ColumnSpec] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)   # projected, post-filter
    row_total: int = 0                       # pre-filter raw count
    raw_samples: list[dict] = field(default_factory=list)      # upstream field map
    drill_samples: list[DrillSample] = field(default_factory=list)
    filters_applied: dict[str, str] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)           # str-safe controller errors
    note: str | None = None


@dataclass
class ReportModel:
    generated_at: str
    connection_label: str
    modules: list[ModuleReport] = field(default_factory=list)

    def by_slug(self, slug: str) -> ModuleReport | None:
        return next((m for m in self.modules if m.slug == slug), None)
