"""Daily Excel report — KPI overview + per-domain sheets with charts.

``build_report(data)`` consumes normalized module items:
``data = {"aps": [...], "clients": [...], "alarms": [...], "switches": [...]}``
and returns xlsx bytes (openpyxl)."""
from __future__ import annotations

import io
import time
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

_HEAD = Font(bold=True, color="FFFFFF")
_HEAD_FILL = PatternFill("solid", fgColor="22A6B3")


def _header(ws, row: int, labels: list[str]) -> None:
    for col, label in enumerate(labels, start=1):
        cell = ws.cell(row=row, column=col, value=label)
        cell.font = _HEAD
        cell.fill = _HEAD_FILL


def _autofit(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def build_report(data: dict[str, Any]) -> bytes:
    aps = data.get("aps") or []
    clients = data.get("clients") or []
    alarms = data.get("alarms") or []
    switches = data.get("switches") or []

    wb = Workbook()

    # ── Overview ──────────────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Overview"
    ws["A1"] = "RUCKUS DSO Daily Report"
    ws["A1"].font = Font(bold=True, size=16)
    ws["A2"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    aps_off = sum(1 for a in aps if a.get("status") == "offline")
    sw_off = sum(1 for s in switches if str(s.get("status")).lower() not in
                 ("online", "in_service"))
    crit = sum(int(a.get("count") or 1) for a in alarms
               if a.get("severity") == "critical")
    rows = [
        ("Access points (total)", len(aps)),
        ("Access points offline", aps_off),
        ("Wireless clients", len(clients)),
        ("Clients with poor signal", sum(1 for c in clients if c.get("quality") == "poor")),
        ("Switches (total)", len(switches)),
        ("Switches offline", sw_off),
        ("Active alarms", sum(int(a.get("count") or 1) for a in alarms)),
        ("Critical alarms", crit),
    ]
    _header(ws, 4, ["Metric", "Value"])
    for i, (k, v) in enumerate(rows, start=5):
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=v)
    _autofit(ws, [34, 14])

    # ── APs by Zone (+ bar chart) ─────────────────────────────────────────
    ws = wb.create_sheet("APs by Zone")
    by_zone: dict[str, dict[str, int]] = {}
    for a in aps:
        z = str(a.get("zone") or "Unknown")
        d = by_zone.setdefault(z, {"total": 0, "offline": 0})
        d["total"] += 1
        if a.get("status") == "offline":
            d["offline"] += 1
    _header(ws, 1, ["Zone", "APs", "Offline"])
    for i, (z, d) in enumerate(sorted(by_zone.items()), start=2):
        ws.cell(row=i, column=1, value=z)
        ws.cell(row=i, column=2, value=d["total"])
        ws.cell(row=i, column=3, value=d["offline"])
    _autofit(ws, [30, 10, 10])
    if by_zone:
        chart = BarChart()
        chart.title = "APs per zone (total vs offline)"
        chart.height, chart.width = 10, 24
        last = 1 + len(by_zone)
        chart.add_data(Reference(ws, min_col=2, max_col=3, min_row=1, max_row=last),
                       titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=last))
        ws.add_chart(chart, "E2")

    # ── Clients (+ pie chart by band, top talkers) ───────────────────────
    ws = wb.create_sheet("Clients")
    bands: dict[str, int] = {}
    for c in clients:
        bands[str(c.get("band") or "—")] = bands.get(str(c.get("band") or "—"), 0) + 1
    _header(ws, 1, ["Band", "Clients"])
    for i, (b, n) in enumerate(sorted(bands.items()), start=2):
        ws.cell(row=i, column=1, value=b)
        ws.cell(row=i, column=2, value=n)
    if bands:
        pie = PieChart()
        pie.title = "Clients by band"
        pie.height, pie.width = 9, 12
        last = 1 + len(bands)
        pie.add_data(Reference(ws, min_col=2, min_row=1, max_row=last),
                     titles_from_data=True)
        pie.set_categories(Reference(ws, min_col=1, min_row=2, max_row=last))
        ws.add_chart(pie, "D2")
    top = sorted(clients, key=lambda c: int(c.get("rx_bytes") or 0) +
                 int(c.get("tx_bytes") or 0), reverse=True)[:10]
    base = 4 + len(bands)
    ws.cell(row=base - 1, column=1, value="Top talkers").font = Font(bold=True)
    _header(ws, base, ["Host", "MAC", "SSID", "AP", "RX bytes", "TX bytes"])
    for i, c in enumerate(top, start=base + 1):
        for col, key in enumerate(("hostname", "mac", "ssid", "ap",
                                   "rx_bytes", "tx_bytes"), start=1):
            ws.cell(row=i, column=col, value=c.get(key))
    _autofit(ws, [22, 20, 16, 20, 14, 14])

    # ── Alarms (+ pie chart) ─────────────────────────────────────────────
    ws = wb.create_sheet("Alarms")
    sev: dict[str, int] = {}
    for a in alarms:
        s = str(a.get("severity") or "unknown")
        sev[s] = sev.get(s, 0) + int(a.get("count") or 1)
    _header(ws, 1, ["Severity", "Count"])
    for i, (s, n) in enumerate(sorted(sev.items()), start=2):
        ws.cell(row=i, column=1, value=s)
        ws.cell(row=i, column=2, value=n)
    if sev:
        pie = PieChart()
        pie.title = "Alarms by severity"
        pie.height, pie.width = 9, 12
        last = 1 + len(sev)
        pie.add_data(Reference(ws, min_col=2, min_row=1, max_row=last),
                     titles_from_data=True)
        pie.set_categories(Reference(ws, min_col=1, min_row=2, max_row=last))
        ws.add_chart(pie, "D2")
    base = 4 + len(sev)
    ws.cell(row=base - 1, column=1, value="Active alarms").font = Font(bold=True)
    _header(ws, base, ["Severity", "Category", "Source", "Message", "Count"])
    for i, a in enumerate(alarms[:50], start=base + 1):
        for col, key in enumerate(("severity", "category", "source",
                                   "message", "count"), start=1):
            ws.cell(row=i, column=col, value=a.get(key))
    _autofit(ws, [12, 14, 24, 48, 8])

    # ── Switches (+ traffic bar chart) ───────────────────────────────────
    ws = wb.create_sheet("Switches")
    _header(ws, 1, ["Switch", "IP", "Model", "Firmware", "Status",
                    "Ports up", "Ports total"])
    for i, s in enumerate(switches, start=2):
        for col, key in enumerate(("name", "ip", "model", "fw", "status",
                                   "ports_online", "ports_total"), start=1):
            ws.cell(row=i, column=col, value=s.get(key))
    _autofit(ws, [24, 16, 16, 18, 10, 10, 10])

    # ── Offline devices ──────────────────────────────────────────────────
    ws = wb.create_sheet("Offline Devices")
    _header(ws, 1, ["Type", "Name", "Where", "Identifier"])
    r = 2
    for a in aps:
        if a.get("status") == "offline":
            ws.cell(row=r, column=1, value="AP")
            ws.cell(row=r, column=2, value=a.get("name"))
            ws.cell(row=r, column=3, value=a.get("zone"))
            ws.cell(row=r, column=4, value=a.get("mac"))
            r += 1
    for s in switches:
        if str(s.get("status")).lower() not in ("online", "in_service"):
            ws.cell(row=r, column=1, value="Switch")
            ws.cell(row=r, column=2, value=s.get("name"))
            ws.cell(row=r, column=3, value=s.get("group"))
            ws.cell(row=r, column=4, value=s.get("mac") or s.get("id"))
            r += 1
    _autofit(ws, [10, 26, 24, 22])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
