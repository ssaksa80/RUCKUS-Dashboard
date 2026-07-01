"""Renderer tests: build_report over a ReportModel and the legacy dict."""
import io

import openpyxl

from ruckus_dashboard.reports.excel import build_report, _safe_sheet_name
from ruckus_dashboard.reports.model import (
    ColumnSpec, DrillSample, ModuleReport, ReportModel,
)


def _model():
    return ReportModel(
        generated_at="2026-06-30T07:00:00Z", connection_label="SZ-LAB",
        modules=[
            ModuleReport(
                slug="aps", title="Access Points", group="Wireless", status="ok",
                columns=[ColumnSpec("Name", "name"),
                         ColumnSpec("Status", "status", "status")],
                summary={"total": 2, "online": 1, "offline": 1},
                rows=[{"id": "a", "name": "AP1", "status": "online"},
                      {"id": "b", "name": "AP2", "status": "offline"}],
                row_total=2,
                raw_samples=[{"apMac": "a", "deviceName": "AP1"}],
                drill_samples=[DrillSample("a", {"identity": {"name": "AP1"}})],
            ),
            ModuleReport(slug="topology", title="Topology", group="Cross-cutting",
                         status="disabled", note="module unavailable"),
        ],
    )


def test_safe_sheet_name_truncates_and_dedupes():
    used: set[str] = set()
    a = _safe_sheet_name("A very long module title that exceeds excel limit", used)
    assert len(a) <= 31 and a not in ("",)
    used.add(a)
    b = _safe_sheet_name("A very long module title that exceeds excel limit", used)
    assert b != a and len(b) <= 31           # deduped suffix


def test_safe_sheet_name_strips_illegal_chars():
    used: set[str] = set()
    name = _safe_sheet_name("APs: by/zone [x]?", used)
    for bad in ":/\\?*[]":
        assert bad not in name


def test_build_report_from_model_loads_with_overview_and_coverage():
    blob = build_report(_model())
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    assert "Overview" in wb.sheetnames
    assert "Coverage" in wb.sheetnames
    # Coverage lists every module + its status.
    cov_text = "\n".join(str(c.value) for row in wb["Coverage"].iter_rows()
                         for c in row if c.value is not None)
    assert "Access Points" in cov_text and "Topology" in cov_text
    assert "disabled" in cov_text


def test_build_report_legacy_dict_still_renders_curated_sheets():
    data = {
        "aps": [{"name": "AP1", "zone": "HQ", "status": "online", "mac": "a"},
                {"name": "AP2", "zone": "HQ", "status": "offline", "mac": "b"}],
        "clients": [{"hostname": "h1", "mac": "m", "ssid": "S", "ap": "AP1",
                     "band": "5 GHz", "quality": "good",
                     "rx_bytes": 10, "tx_bytes": 20}],
        "alarms": [{"severity": "critical", "category": "AP", "source": "AP2",
                    "message": "down", "count": 1}],
        "switches": [{"name": "SW1", "ip": "10.0.0.1", "model": "ICX",
                      "fw": "x", "status": "online", "ports_online": 10,
                      "ports_total": 24, "group": "Core", "mac": "c"}],
    }
    wb = openpyxl.load_workbook(io.BytesIO(build_report(data)))
    # Curated sheets preserved; charts intact (regression for current suite).
    assert {"Overview", "APs by Zone", "Clients", "Alarms",
            "Switches", "Offline Devices"} <= set(wb.sheetnames)
    assert len(wb["APs by Zone"]._charts) == 1
    assert len(wb["Clients"]._charts) == 1
    assert len(wb["Alarms"]._charts) == 1
