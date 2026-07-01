"""Background scheduler: automated alert e-mails + the daily Excel report.

A single daemon thread ticks every 30 s. ``/connect`` hands it the active
controller connection; logout clears it. Every action is best-effort — a
failed fetch or send is logged and never kills the thread.

SP2 changes:
- collect_device_snapshot() replaces collect_report_data() for alerts.
- OutageEngine.reconcile() + JsonOutageStateStore replace _prev_state + evaluate().
- _last_report_day migrated into notify_state.json (durable across restart).
- set_connection() no longer nulls the state (committed state is source of truth).
- state_from_data() count fix: 'count or 0' (audit #14).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from ..modules import MODULES
from .channels import CHANNELS
from .config import load_config, smtp_password
from .mailer import send_email
from .outage import DeviceStatus, OutageEngine, device_online, render_alert
from .state_store import JsonOutageStateStore

LOG = logging.getLogger("ruckus.notify")

TICK_SECONDS = 30


def collect_report_data(connection, config: dict) -> dict[str, Any]:
    """Run the relevant module fetchers (dump-style) for the report/alerts."""
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


def collect_device_snapshot(
    connection, config: dict
) -> tuple[dict[str, DeviceStatus], set[str]]:
    """Fetch APs, switches, and controller nodes; normalize to DeviceStatus.

    Returns ``(snapshot, fetched_kinds)`` where *fetched_kinds* is the set of
    device kinds (``"ap"``, ``"switch"``, ``"controller"``) whose fetch
    SUCCEEDED this tick. Each fetcher is isolated: if one throws, that device
    type is absent from *snapshot* AND absent from *fetched_kinds*. The caller
    passes *fetched_kinds* to ``OutageEngine.reconcile`` so that a failed type's
    committed devices are carried forward unchanged rather than being marked
    offline — a per-type fetch outage must not trigger a false offline storm.
    A type that fetched successfully but returned zero devices IS in
    *fetched_kinds* (empty result is real; its committed devices go offline).
    """
    from ..modules._base import FetcherContext
    from ..infra.capability_gate import CapabilityGate

    ctx = FetcherContext(
        connection=connection, config=config, filters=None,
        capability_gate=CapabilityGate(set()),
        connection_label=getattr(connection, "display_name", ""),
    )
    snapshot: dict[str, DeviceStatus] = {}
    fetched_kinds: set[str] = set()

    # ── APs ───────────────────────────────────────────────────────────────
    try:
        ap_items = (MODULES["aps"].fetcher(ctx) or {}).get("items", [])
        for row in ap_items or []:
            dev_id = str(row.get("mac") or row.get("id") or row.get("name") or "")
            if not dev_id:
                continue
            key = f"ap:{dev_id}"
            raw_status = str(row.get("status") or "")
            snapshot[key] = DeviceStatus(
                key=key, type="ap",
                name=str(row.get("name") or dev_id),
                group=row.get("zone"),
                online=device_online("ap", raw_status),
                raw_status=raw_status,
                last_change=0.0,
            )
        fetched_kinds.add("ap")
    except Exception:  # noqa: BLE001
        LOG.exception("notify: ap fetch failed for device snapshot")

    # ── Switches ──────────────────────────────────────────────────────────
    try:
        sw_items = (MODULES["switches"].fetcher(ctx) or {}).get("items", [])
        for row in sw_items or []:
            dev_id = str(row.get("id") or row.get("mac") or "")
            if not dev_id:
                continue
            key = f"switch:{dev_id}"
            raw_status = str(row.get("status") or "")
            snapshot[key] = DeviceStatus(
                key=key, type="switch",
                name=str(row.get("name") or dev_id),
                group=row.get("group") or row.get("stack"),
                online=device_online("switch", raw_status),
                raw_status=raw_status,
                last_change=0.0,
            )
        fetched_kinds.add("switch")
    except Exception:  # noqa: BLE001
        LOG.exception("notify: switch fetch failed for device snapshot")

    # ── Controller nodes ──────────────────────────────────────────────────
    try:
        ctrl_items = (MODULES["controller"].fetcher(ctx) or {}).get("items", [])
        for row in ctrl_items or []:
            dev_id = str(row.get("id") or row.get("node") or "")
            if not dev_id:
                continue
            key = f"controller:{dev_id}"
            raw_status = str(row.get("state") or "")
            snapshot[key] = DeviceStatus(
                key=key, type="controller",
                name=str(row.get("node") or dev_id),
                group="controller",
                online=device_online("controller", raw_status),
                raw_status=raw_status,
                last_change=0.0,
            )
        fetched_kinds.add("controller")
    except Exception:  # noqa: BLE001
        LOG.exception("notify: controller fetch failed for device snapshot")

    return snapshot, fetched_kinds


def state_from_data(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "aps_offline": sum(1 for a in data.get("aps") or []
                           if a.get("status") == "offline"),
        "switches_offline": sum(
            1 for s in data.get("switches") or []
            if str(s.get("status")).lower() not in ("online", "in_service")),
        "critical_alarms": sum(int(a.get("count") or 0)          # #14: was 'or 1'
                               for a in data.get("alarms") or []
                               if a.get("severity") == "critical"),
        "poor_aps": poor_quality_aps(data.get("clients") or []),
    }


def poor_quality_aps(clients: list[dict], ratio: float = 0.8,
                     min_clients: int = 3) -> list[str]:
    """APs where ≥ratio of their connected clients report poor quality."""
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
        self._last_alert_check = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._store = JsonOutageStateStore(instance_path)

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
        # SP2: do NOT null committed state — the store is the source of truth.
        # A reconnect must not re-baseline (audit #4 fix).

    def clear_connection(self) -> None:
        with self._lock:
            self._connection = None

    # ── due logic (unit-tested) ──────────────────────────────────────────
    def _alerts_due(self, cfg: dict, now: float) -> bool:
        if not cfg["alerts"]["enabled"]:
            return False
        return now - self._last_alert_check >= int(cfg["alerts"]["check_seconds"])

    def _report_due(self, cfg: dict, now_struct) -> bool:
        """True when the daily report has not yet been sent today.

        SP2: reads last_report_day from the durable store (not in-memory field)
        so a restart after the configured time doesn't re-send (audit #5 fix).
        """
        if not cfg["report"]["enabled"]:
            return False
        day = time.strftime("%Y-%m-%d", now_struct)
        state = self._store.load()
        last_day = (state.get("report") or {}).get("last_report_day")
        if last_day == day:
            return False
        hhmm = time.strftime("%H:%M", now_struct)
        return hhmm >= str(cfg["report"]["time"] or "07:00")

    def _mark_report_sent(self, day: str) -> None:
        """Persist today's date as sent to prevent re-send on restart."""
        state = self._store.load()
        state["report"] = {**(state.get("report") or {}), "last_report_day": day}
        self._store.save(state)

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
            try:
                self._run_alerts(connection, cfg, now)
            except Exception:  # noqa: BLE001
                LOG.exception("notify: alerts tick failed")

        if self._report_due(cfg, time.localtime(now)):
            day = time.strftime("%Y-%m-%d", time.localtime(now))
            self._mark_report_sent(day)
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

    def _run_alerts(self, connection, cfg: dict, now: float) -> None:
        """Collect snapshot → reconcile → persist → dispatch via channels."""
        alerts_cfg = cfg["alerts"]

        # Load committed state from disk.
        state = self._store.load()
        prev_devices: dict[str, DeviceStatus] = state.get("devices") or {}

        # Collect current device snapshot + which kinds fetched successfully.
        snapshot, fetched_kinds = collect_device_snapshot(
            connection, self._app_config
        )

        # Reconcile: pure function, no I/O. Devices of a kind that FAILED to
        # fetch this tick are carried forward (not marked offline).
        reconcile_cfg = {
            "debounce_seconds": int(alerts_cfg.get("debounce_seconds", 120)),
            "recovery": bool(alerts_cfg.get("recovery", True)),
            "offline_threshold": int(alerts_cfg.get("offline_threshold", 1)),
        }
        events, new_devices = OutageEngine.reconcile(
            prev_devices, snapshot, reconcile_cfg, now=now,
            fetched_kinds=fetched_kinds,
        )

        # Persist new state BEFORE dispatch (save-first semantics — see spec §4.8).
        state["devices"] = new_devices
        self._store.save(state)

        if not events:
            return

        # Render + dispatch.
        group_by = str(alerts_cfg.get("group_by", "site"))
        note = render_alert(events, group_by=group_by)

        for ch_name, channel in CHANNELS.items():
            if channel.is_configured(cfg):
                try:
                    channel.send(cfg, self._secrets, note)
                    LOG.info("notify: sent %d outage event(s) via %s",
                             len(events), ch_name)
                except Exception:  # noqa: BLE001 — per-channel isolation
                    LOG.exception("notify: channel %s failed", ch_name)
