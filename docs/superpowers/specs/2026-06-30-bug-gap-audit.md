# SP7 — RUCKUS Dashboard Bug / Gap Audit (verified)

**Date:** 2026-06-30
**Status:** Audit (findings + fixes). Verified against the code by direct read; each
finding cites `file:line`. Confidence: **confirmed** = read and reproduced in code;
**likely** = strong inference; **speculative** = needs triage.
**Source:** consolidates the prior manual review + the four parallel auditors
(security, concurrency/correctness, frontend, errors/tests) + cross-confirmation from
the SP1/SP3/SP6 design specs that read the same files.

Repo root: `C:\Users\sshoaib\OneDrive - Mohamed & Obaid Almulla LLC\Documents\RUCKUS-Dashboard`.
Package: `RUCKUS\ruckus_dashboard\`.

---

## Summary table

| # | Sev | Title | Location | Confidence |
|---|-----|-------|----------|------------|
| 1 | **High** | SSRF allow-list bypass via HTTP redirect | `clients/base.py:234` | confirmed |
| 2 | **High** | `available_ops` is a process-global shared across all sessions | `app.py:50`, `routes/connect.py:113,142`, `routes/modules.py:81` | confirmed |
| 3 | **High** | SSRF allow-list is allow-all when unset (default-open) | `net/allowlist.py:42,63-66` | confirmed |
| 4 | Medium | Alert baseline-spam: pre-existing outages re-fire on every (re)connect/restart | `notify/rules.py:14`, `notify/scheduler.py:102-103` | confirmed |
| 5 | Medium | Daily-report dedup non-durable + fires immediately if started after report time | `notify/scheduler.py:115-122,159` | confirmed |
| 6 | Medium | `ParallelFetcher` per-task timeout is illusory | `infra/parallel_fetch.py:37-59` | confirmed |
| 7 | Medium | Drill endpoints leak raw exception text (info disclosure) | `routes/modules.py:148,185` | confirmed |
| 8 | Low | Report path bypasses capability gate (empty gate) | `notify/scheduler.py:29` | confirmed |
| 9 | Low | Secret-key/profiles `chmod(600)` after write (POSIX race window) | `auth/secrets.py:79-95`, `auth/profiles.py:69` | confirmed |
| 10 | Low | `notifications.json` never `chmod`'d (SMTP password file) | `notify/config.py:64-66` | confirmed |
| 11 | Low | DPAPI uses `LOCAL_MACHINE` scope (any local user can decrypt) | `auth/secrets.py:27` | confirmed |
| 12 | Low | Secret silently dropped when `cryptography` missing | `auth/secrets.py:128`, `auth/profiles.py:102`, `notify/config.py:60` | confirmed |
| 13 | Low | `save_config` section-merge can drop saved sub-keys on partial POST | `notify/config.py:56` | likely |
| 14 | Low | `state_from_data` counts missing/zero alarm count as 1 | `notify/scheduler.py:49` | confirmed |
| 15 | Low | `ConnectionStore` eviction-on-access only (stale tokens linger) | `auth/session_store.py:63` | confirmed |

Coverage gaps (not bugs, but risk): `routes/notifications.py` 54%, `security/validator.py`
74%, `routes/modules.py` 71% — the untested paths are the per-tab/report email handlers,
CVE matching, and the partial-failure envelope branches.

---

## High

### 1. SSRF allow-list bypass via HTTP redirect — `clients/base.py:234`
`request_json` runs `assert_host_allowed(_host_label(url), config)` on the **initial**
host (`:227-228`) then `requests.request(method, url, timeout=...)` with redirects
**enabled** (default). A `3xx` from a controller (or a MITM on a `verify_tls=False` lab
link) pointing at `http://169.254.169.254/` or any internal host is followed with no
re-check. RUCKUS APIs never legitimately redirect.
**Fix:** `allow_redirects=False`; if a redirect must be supported, re-run
`assert_host_allowed` on the `Location` target before following.

### 2. `available_ops` process-global shared across sessions — `app.py:50`
`app.available_ops = set()` is **one** mutable set per process. `/connect` unions a
connection's discovered ops into it (`routes/connect.py:142`), logout resets it to
`set()` (`:113`), and `module_data` builds the capability gate from it
(`routes/modules.py:81`). With one operator this is fine; with two concurrent operators
on different controllers it is a **correctness + boundary bug**: operator B's logout
wipes A's gating, and B's controller capabilities leak into A's module visibility. Same
class of single-slot global affects `warmup_scheduler` (`app.py:39`, replaced per
connect).
**Fix:** make capability state per-connection (a `CapabilityRegistry` keyed by
`connection_id`); build the gate from the session's own connection ids. (This is also
SP6's Phase-A1 seam.)

### 3. SSRF allow-list default-open when unset — `net/allowlist.py:42`
`self.enabled = bool(self.names or self.networks)` and `host_allowed` returns `True`
when `not self.enabled` (`:63-66`). So with `RUCKUS_ALLOWED_HOSTS` empty the guard is
**off** — every host allowed. README/DEPLOY require operators to set it for non-loopback
binds, but the safe default is inverted for any exposed deployment.
**Fix:** deny-by-default when bound to a non-loopback interface (config-driven);
keep allow-all only for explicit loopback dev.

---

## Medium

### 4. Alert baseline-spam — `notify/rules.py:14` + `notify/scheduler.py:102-103`
`evaluate(prev, ...)` does `prev = prev or {}`, and `_rose(key)` is `current > prev(0)`,
so on the first check after connect **every pre-existing outage looks like a new
upward transition** and fires. `set_connection` nulls `_prev_state` (`scheduler.py:103`),
so this recurs on every reconnect/restart. `test_notify.py` even codifies the spam as
expected.
**Fix:** seed baseline silently on first check (`prev is None` → store state, emit
nothing); persist `_prev_state` across restart. Invert the test.

### 5. Daily-report dedup non-durable — `notify/scheduler.py:115-122,159`
`_last_report_day` is in-memory; a restart re-sends the day's report. And `_report_due`
fires on the first tick where `hhmm >= time`, so starting the service any time after the
configured hour sends a "daily" report immediately.
**Fix:** persist `last_report_day` to `instance/notify_state.json`; gate the
immediate-fire to a small window past the target.

### 6. `ParallelFetcher` timeout illusory — `infra/parallel_fetch.py:37-59`
`run()` waits with `concurrent.futures.wait(timeout=)` then exits the
`with ThreadPoolExecutor()` block, whose `__exit__` calls `shutdown(wait=True)` —
blocking until straggler threads finish; `future.cancel()` can't stop a running task. So
a hung upstream holds a thread past `RUCKUS_WARMUP_TIMEOUT`. Masked today only by
`request_json`'s own socket timeout.
**Fix:** `shutdown(wait=False, cancel_futures=True)` (no `with`), and bound the upstream
socket timeout so no task can outlive the window.

### 7. Drill endpoints leak raw exception text — `routes/modules.py:148,185`
`module_drill` / `module_drill_tab` `return jsonify({"error": str(exc), ...}), 502`
unconditionally, while `module_data` correctly routes errors through `_upstream_message`
which gates raw bodies behind `RUCKUS_SHOW_DEBUG` (`:28-37`). Inconsistent info
disclosure.
**Fix:** route drill errors through `_upstream_message` / a generic message when debug
off.

---

## Low

- **8. Report bypasses capability gate** — `notify/scheduler.py:29` builds
  `CapabilityGate(set())` (empty), so `collect_report_data` runs fetchers ungated unlike
  the HTTP path (`routes/modules.py:82-89`). Surfaced by the SP3 design; fix by passing
  the live `available_ops`.
- **9. `chmod(600)` after write** — `auth/secrets.py:79-95`, `auth/profiles.py:69`: tmp
  file is created with umask perms, then chmod'd after `replace` → brief world-readable
  window on POSIX. Use `os.open(..., 0o600)`.
- **10. `notifications.json` not chmod'd** — `notify/config.py:64-66` writes the
  Fernet-encrypted SMTP password file with no `chmod` (profiles.py does). Add parity.
- **11. DPAPI `LOCAL_MACHINE` scope** — `auth/secrets.py:27`: any local user/process can
  unprotect the master key. Document, or switch to `CURRENT_USER` for a dedicated service
  account.
- **12. Silent secret drop** — `auth/secrets.py:128` `encrypt()` returns `""` when
  `cryptography` is absent; callers store the empty blob (`profiles.py:102`,
  `notify/config.py:60`) → password silently lost, no operator warning.
- **13. Shallow config merge** — `notify/config.py:56` `{**current, **incoming-dicts}`
  per section; a partial POST could drop previously-saved sub-keys (currently safe only
  because the UI round-trips the full object).
- **14. `count or 1`** — `notify/scheduler.py:49` `int(a.get("count") or 1)` counts a
  missing/zero alarm count as 1.
- **15. Eviction-on-access only** — `auth/session_store.py:63`: idle connections (holding
  live auth tokens in RAM) are only evicted when the store is next touched; no background
  sweep.

---

## Speculative / needs-triage

- **Frontend XSS surface** — `static/dashboard.js` / `topology.js` rebuild DOM via
  `innerHTML` each poll. A test enforces HTML-escaping of controller-sourced strings
  (`_escape`/`_esc`), but any new render path that interpolates a controller value
  without `_escape` would be injectable. Recommend a focused pass over every
  `innerHTML`/template-literal sink that embeds payload fields. (Confidence: speculative —
  the escape helper exists and is tested; risk is in future/uncovered sinks.)
- **CSRF on SSE/GET** — warmup SSE and module GETs are unauthenticated-readable only after
  `session["auth"]`; confirm no state-changing GET exists. (Likely fine.)

---

## Suggested fix order

1. **#1, #3 (SSRF redirect + default-open)** — security, tiny diffs, highest risk.
2. **#2 (`available_ops` per-connection)** — correctness boundary; also the SP6 Phase-A1
   seam, so doing it now de-risks both multi-user and the migration.
3. **#4, #5 (alert baseline-spam + durable report dedup)** — they actively misfire today;
   also prerequisites for SP2 (outage alerting) being trustworthy.
4. **#6, #7 (fetch timeout, drill error leak)**.
5. **#8–#15** — batch as a hardening sweep (maps to SP6 Milestone A2).

Most of these are SP6 Milestone A1/A2 — i.e. fixing them *is* the first migration phase.
