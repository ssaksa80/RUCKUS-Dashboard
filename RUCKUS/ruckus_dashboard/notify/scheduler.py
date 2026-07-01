"""Background scheduler: automated alert e-mails + the daily Excel report.

A single daemon thread ticks every 30 s. ``/connect`` hands it the active
controller connection; logout clears it. Every action is best-effort — a
failed fetch or send is logged and never kills the thread."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .config import load_config, smtp_password
from .mailer import send_email
from .rules import evaluate

LOG = logging.getLogger("ruckus.notify")

TICK_SECONDS = 30


def collect_report_data(connection, config: dict) -> dict[str, Any]:
    """Run the relevant module fetchers (dump-style) for the report/alerts."""
    from ..modules import MODULES
    from ..modules._base import FetcherContext
    from ..infra.capability_gate import CapabilityGate

    ctx = FetcherContext(connection=connection, config=config, filters=None,
                         capability_gate=CapabilityGate(set()),
                         connection_label=getattr(connection, "display_name", ""))
    out: dict[str, Any] = {}
    for slug, key in (("aps", "aps"), ("clients", "clients"),
                      ("alarms", "alarms"), ("switches", "switches")):
        try:
            out[key] = (MODULES[slug].fetcher(ctx) or {}).get("items", [])
        except Exception:  # noqa: BLE001
            LOG.exception("notify: %s fetch failed", slug)
            out[key] = []
    return out


def state_from_data(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "aps_offline": sum(1 for a in data.get("aps") or []
                           if a.get("status") == "offline"),
        "switches_offline": sum(
            1 for s in data.get("switches") or []
            if str(s.get("status")).lower() not in ("online", "in_service")),
        "critical_alarms": sum(int(a.get("count") or 0)
                               for a in data.get("alarms") or []
                               if a.get("severity") == "critical"),
        "poor_aps": poor_quality_aps(data.get("clients") or []),
    }


def poor_quality_aps(clients: list[dict], ratio: float = 0.8,
                     min_clients: int = 3) -> list[str]:
    """APs where ≥ratio of their connected clients report poor quality.

    min_clients avoids flagging an AP because its single client is poor."""
    by_ap: dict[str, list[str]] = {}
    for c in clients:
        ap = str(c.get("ap") or "")
        if ap:
            by_ap.setdefault(ap, []).append(str(c.get("quality") or ""))
    flagged = []
    for ap, qualities in by_ap.items():
        if len(qualities) < min_clients:
            continue
        poor = sum(1 for q in qualities if q == "poor")
        if poor / len(qualities) >= ratio:
            flagged.append(f"{ap} ({poor}/{len(qualities)} poor)")
    return sorted(flagged)


class NotifyScheduler:
    def __init__(self, instance_path: str, app_config: dict,
                 secrets) -> None:
        self._instance_path = instance_path
        self._app_config = app_config
        self._secrets = secrets
        self._connection = None
        self._lock = threading.Lock()
        self._prev_state: dict | None = None
        self._last_alert_check = 0.0
        self._last_report_day: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── wiring ───────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="notify-scheduler")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def set_connection(self, connection) -> None:
        with self._lock:
            self._connection = connection
            self._prev_state = None

    def clear_connection(self) -> None:
        with self._lock:
            self._connection = None

    # ── due logic (unit-tested) ──────────────────────────────────────────
    def _alerts_due(self, cfg: dict, now: float) -> bool:
        if not cfg["alerts"]["enabled"]:
            return False
        return now - self._last_alert_check >= int(cfg["alerts"]["check_seconds"])

    def _report_due(self, cfg: dict, now_struct) -> bool:
        if not cfg["report"]["enabled"]:
            return False
        day = time.strftime("%Y-%m-%d", now_struct)
        if self._last_report_day == day:
            return False
        hhmm = time.strftime("%H:%M", now_struct)
        return hhmm >= str(cfg["report"]["time"] or "07:00")

    # ── loop ─────────────────────────────────────────────────────────────
    def _run(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self._tick()
            except Exception:  # noqa: BLE001 — the loop must survive anything
                LOG.exception("notify: tick failed")

    def _tick(self) -> None:
        with self._lock:
            connection = self._connection
        if connection is None:
            return
        cfg = load_config(self._instance_path)
        now = time.time()

        if self._alerts_due(cfg, now):
            self._last_alert_check = now
            data = collect_report_data(connection, self._app_config)
            state = state_from_data(data)
            alerts = evaluate(self._prev_state, state,
                              cfg["alerts"]["rules"],
                              int(cfg["alerts"]["offline_threshold"]))
            self._prev_state = state
            if alerts:
                try:
                    send_email(cfg, smtp_password(cfg, self._secrets),
                               cfg["alerts"]["recipients"],
                               "[RUCKUS DSO] Alert: fabric degradation",
                               "\n".join(alerts))
                    LOG.info("notify: sent %d alert(s)", len(alerts))
                except Exception:  # noqa: BLE001
                    LOG.exception("notify: alert e-mail failed")

        if self._report_due(cfg, time.localtime(now)):
            self._last_report_day = time.strftime("%Y-%m-%d", time.localtime(now))
            try:
                from ..reports.excel import build_report
                data = collect_report_data(connection, self._app_config)
                xlsx = build_report(data)
                ts = time.strftime("%Y-%m-%d", time.localtime(now))
                send_email(cfg, smtp_password(cfg, self._secrets),
                           cfg["report"]["recipients"],
                           f"[RUCKUS DSO] Daily report {ts}",
                           "Attached: daily RUCKUS DSO fabric report.",
                           attachment=xlsx,
                           filename=f"ruckus-dso-report-{ts}.xlsx")
                LOG.info("notify: daily report sent")
            except Exception:  # noqa: BLE001
                LOG.exception("notify: daily report failed")
