# Alert Notifications + Smart Excel Reporting — Design

Date: 2026-06-10
Status: Approved

## Problem

The dashboard shows problems but cannot tell anyone. Operators want
(1) automated e-mail alerts when the fabric degrades and (2) a scheduled
daily Excel report (charts + key data) delivered over SMTP.

## Components

### 1. Notification config (`notify/config.py`)

`NotificationConfig` persisted as JSON at
`<instance>/notifications.json`:

```json
{
  "smtp": {"host": "", "port": 587, "use_tls": true, "username": "",
           "password_enc": "<fernet>", "from_addr": ""},
  "alerts": {"enabled": false, "recipients": [],
             "check_seconds": 300,
             "rules": {"ap_offline": true, "switch_offline": true,
                        "critical_alarm": true},
             "offline_threshold": 1},
  "report": {"enabled": false, "recipients": [], "time": "07:00"}
}
```

SMTP password encrypted with the app's existing Fernet secret-key machinery
(`auth/secrets.py` key); never stored or returned in plaintext (GET masks it).

### 2. Mailer (`notify/mailer.py`)

`send_email(cfg, subject, body, attachment=None, filename=None)` —
smtplib, STARTTLS when `use_tls`, optional xlsx attachment. Raises on
failure (callers decide; routes surface the message).

### 3. Alert rules (`notify/rules.py`)

`evaluate(prev, current)` over per-module state dicts
(`{aps_offline, switches_offline, critical_alarms}`) → list of alert strings,
fired on **transitions only** (new offline beyond threshold, new critical
alarms). Pure function, unit-tested.

### 4. Excel report (`reports/excel.py`, dependency: `openpyxl`)

`build_report(data) -> bytes` where `data` carries module results
(aps, clients, alarms, switches, traffic, zones). Workbook:

- **Overview** sheet: KPI table (totals/online/offline/alarms/clients).
- **APs by Zone**: table + **bar chart** (total vs offline per zone).
- **Clients**: by-band table + **pie chart**; top-10 talkers table.
- **Alarms**: severity table + **pie chart**; newest 50 alarm rows.
- **Switches**: inventory health table; top traffic **bar chart**.
- **Offline Devices**: list of offline APs/switches (name, zone/group, last seen).

### 5. Scheduler (`notify/scheduler.py`)

`NotifyScheduler` daemon thread (started in `create_app`, like warmup):
- Holds the active connection — `/connect` calls
  `app.notify_scheduler.set_connection(conn)`, logout clears it.
- Tick every 30 s: if alerts enabled + connection + due
  (`check_seconds` elapsed): fetch aps/switches/alarms via existing module
  fetchers, build state, `evaluate(prev, state)`, e-mail any alerts.
- Daily report: when `report.enabled` and local time crosses `report.time`
  (once per day), collect data via module fetchers, `build_report`, e-mail
  with the xlsx attached.
- Every action best-effort + logged; failures never crash the thread.

### 6. Routes (`routes/notifications.py`) + page

- `GET /api/notifications/config` (auth) — config with password masked.
- `POST /api/notifications/config` (auth+CSRF) — save; keeps stored password
  when the masked placeholder is posted back.
- `POST /api/notifications/test` (auth+CSRF) — send a test e-mail now;
  returns ok/error message.
- `GET /api/reports/generate` (auth) — build the report from live data and
  return it as an xlsx download (no e-mail).
- **Notifications page** `/notifications`: SMTP form, alert toggles +
  recipients + interval, report schedule + recipients, "Send test e-mail",
  "Download report now". Linked from the sidebar (below module groups).

## Security

- CSRF on all mutations; auth on everything.
- SMTP password Fernet-encrypted at rest; masked (`********`) on GET.
- Recipients/host validated non-empty before send.

## Non-goals

- Rule builder UI (fixed rule set with toggles).
- Webhooks/Slack (e-mail only this round).
- Multi-controller scheduling (first active connection wins).

## Testing

- Config roundtrip: password encrypted at rest, masked on GET, preserved on
  masked re-POST.
- Rules: transition-only firing, threshold respected.
- Excel: `build_report` output loads in openpyxl; sheets + charts present.
- Routes: 401 unauth, CSRF enforced, test-email path with `smtplib.SMTP`
  monkeypatched, report download content-type.
- Scheduler: due-time logic unit-tested (`_report_due`, `_alerts_due`).
