"""Alert rule evaluation — transition-only firing.

State dicts: ``{"aps_offline": int, "switches_offline": int,
"critical_alarms": int}``. An alert fires only when a metric crosses the
threshold upward relative to the previous check (no repeat spam while a
condition persists at the same level)."""
from __future__ import annotations

from typing import Any


def evaluate(prev: dict | None, current: dict,
             rules: dict | None = None, offline_threshold: int = 1) -> list[str]:
    prev = prev or {}
    rules = rules or {}
    alerts: list[str] = []

    def _rose(key: str) -> bool:
        return int(current.get(key) or 0) > int(prev.get(key) or 0)

    aps_off = int(current.get("aps_offline") or 0)
    if rules.get("ap_offline", True) and aps_off >= offline_threshold and _rose("aps_offline"):
        alerts.append(f"Access points offline: {aps_off} "
                      f"(was {int(prev.get('aps_offline') or 0)}).")

    sw_off = int(current.get("switches_offline") or 0)
    if rules.get("switch_offline", True) and sw_off >= offline_threshold and _rose("switches_offline"):
        alerts.append(f"Switches offline: {sw_off} "
                      f"(was {int(prev.get('switches_offline') or 0)}).")

    crit = int(current.get("critical_alarms") or 0)
    if rules.get("critical_alarm", True) and crit > 0 and _rose("critical_alarms"):
        alerts.append(f"Critical alarms active: {crit} "
                      f"(was {int(prev.get('critical_alarms') or 0)}).")

    # ≥80% of an AP's clients on poor signal — alert on newly-degraded APs only.
    if rules.get("poor_client_ap", True):
        prev_aps = {str(p).split(" (")[0] for p in prev.get("poor_aps") or []}
        for entry in current.get("poor_aps") or []:
            ap = str(entry).split(" (")[0]
            if ap not in prev_aps:
                alerts.append(f"AP signal degradation: {entry} — 80%+ of "
                              f"connected clients report poor connection.")

    return alerts
