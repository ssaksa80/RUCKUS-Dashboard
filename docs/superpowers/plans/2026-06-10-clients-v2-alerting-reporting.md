# Clients v2 + Alerting/Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fix the clients drill 404 and expand the clients module; add SMTP alert notifications and a scheduled daily Excel report with charts.

**Architecture:** Clients drill derives from the proven `query/client` list (sub-project A). Sub-project B adds a `notify/` package (config + mailer + rules + scheduler thread), `reports/excel.py` (openpyxl workbook with bar/pie charts), `/api/notifications/*` + `/api/reports/generate` routes, and a `/notifications` settings page; the scheduler gets its connection from `/connect`.

**Tech Stack:** Flask, openpyxl (new dependency), smtplib, pytest.

---

### A1: clients.py v2 (drill from list, band/quality, KPIs, columns)

Files: `RUCKUS/ruckus_dashboard/modules/clients.py`, `tests/unit/modules/test_clients.py`

- [ ] Failing tests: drill match from mocked `query/client` (identity/connection/usage sections), not-found note, `_band`/`_quality` derivations, KPI math + top_talker, `raw_rows` present.
- [ ] Implement per spec (defensive `.get` everywhere; drill walks `smartzone_query_paged`).
- [ ] Suite green; commit `feat(clients): drill from query/client + band/quality/KPI expansion`.

### B1: notify/config.py + tests

- [ ] `load_config(instance_path)` / `save_config(instance_path, cfg, fernet)` with password encrypt/mask/preserve semantics from the spec; defaults when file missing.
- [ ] Commit `feat(notify): persisted notification config with encrypted SMTP password`.

### B2: notify/mailer.py + notify/rules.py + tests

- [ ] `send_email(cfg, subject, body, attachment=None, filename=None)` (STARTTLS path; tested with monkeypatched smtplib).
- [ ] `evaluate(prev, current, rules, threshold)` transition-only alerts.
- [ ] Commit `feat(notify): mailer + transition alert rules`.

### B3: reports/excel.py + tests (openpyxl)

- [ ] Add `openpyxl` to pyproject dependencies.
- [ ] `build_report(data) -> bytes`: Overview, APs-by-zone (+BarChart), Clients (+PieChart by band, top talkers), Alarms (+PieChart), Switches (+BarChart traffic), Offline Devices.
- [ ] Test: output loads via `openpyxl.load_workbook`, sheet names + chart counts asserted.
- [ ] Commit `feat(reports): Excel report builder with bar/pie charts`.

### B4: notify/scheduler.py + wiring + tests

- [ ] `NotifyScheduler(app)` daemon: `set_connection/clear_connection`, `_alerts_due`, `_report_due(now)` (once-per-day at HH:MM), tick loop 30 s; collect data via module fetchers (dump-style FetcherContext); best-effort try/except + logging.
- [ ] Wire: start in `create_app`, set/clear in `/connect`/`logout` next to warmup scheduler.
- [ ] Unit tests: due-logic only (no thread).
- [ ] Commit `feat(notify): background scheduler for alerts + daily report`.

### B5: routes/notifications.py + page + tests

- [ ] Routes per spec (GET config masked / POST save / POST test / GET report download). CSRF via existing `validate_csrf`.
- [ ] `templates/notifications.html` settings form + buttons; `static/notifications.js` (CSP: external file); sidebar link in `base.html`.
- [ ] Tests: 401s, roundtrip mask/preserve, test-email monkeypatched, report download mimetype.
- [ ] Commit `feat(notify): settings page + API routes`.

### B6: Full suite + push

- [ ] `python -m pytest -q` green, `node -c` JS files, merge to main, push.

---

## Self-Review

- Spec coverage: A fully in A1; B components 1-6 map to B1-B5 + wiring. Covered.
- Placeholders: signatures fixed here; full code at implementation (inline execution).
- Consistency: `cfg` dict shape shared by config/mailer/scheduler/routes; `build_report(data)` consumed by scheduler + route.
