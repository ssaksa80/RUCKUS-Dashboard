# SP2 — Connection/Device Outage Alerting — Design

Date: 2026-06-30
Status: Proposed (design only — no implementation)
Supersedes the alerting portions of `2026-06-10-alerting-reporting-design.md`
(daily Excel report is unchanged and out of scope here).

---

## 1. Problem & current behavior (grounded in code)

Operators want an e-mail when a device goes **offline** — one device or many —
across **all device types** (APs, switches, controller nodes), grouped per
**site/zone/group**, with **debounce** (don't fire on a one-poll blip),
**recovery / "back online"** notifications, and **state that survives a
process restart**. Two known defects block this today.

### 1.1 Alerts are count-based, not device-based

The scheduler reduces every poll to three integers + one AP-name list:

- `notify/scheduler.py:42-53` `state_from_data()` returns
  `{"aps_offline": int, "switches_offline": int, "critical_alarms": int,
  "poor_aps": [str]}`. Device identity is discarded the instant data is
  collected.
- `notify/rules.py:11-44` `evaluate()` fires only when a **count rises**
  (`_rose()` at `rules.py:17-18`: `current[key] > prev[key]`).

Consequences:

- **No recovery notifications are possible.** A *falling* count produces no
  event (`_rose` is strictly `>`), so "back online" can never be sent — the
  data needed (which device recovered) was never retained.
- **No per-device / per-site grouping.** The message is
  `"Access points offline: 5 (was 3)."` (`rules.py:22-23`) — operators can't
  see *which* APs or *which* zone. The AP `zone`/`zone_id` fields
  (`modules/aps.py:98-99`) and switch `group`/`stack` fields
  (`modules/switches.py:176,183`) exist but are thrown away by
  `state_from_data`.
- **Flapping churn.** Count 3→5→3→6 fires twice with no debounce; a device
  that flaps every poll generates an e-mail every time the count ticks up.
- **Controller nodes are not monitored at all.** `collect_report_data`
  (`scheduler.py:32-33`) fetches only `aps/clients/alarms/switches`; the
  `controller` module (nodes with `state`, `modules/controller.py:33-40`) is
  never polled for alerting, so a SmartZone **node going down** raises no alert.

### 1.2 Baseline-spam on (re)connect

`set_connection()` resets `self._prev_state = None` (`scheduler.py:100-103`),
and `clear_connection`/login churn means `prev` is frequently `None`.
`evaluate(None, current, …)` treats `prev` as `{}` (`rules.py:13`), so on the
**first poll after every connect** any pre-existing outage looks like a fresh
upward transition and fires. The unit test even codifies this as intended:
`evaluate(None, {"aps_offline": 2}, …)` returns one alert
(`tests/unit/notify/test_notify.py:56-57`). Every reconnect, app restart, or
session re-auth re-pages the NOC for outages they were already told about.

### 1.3 Dedup durability — alerts have none; the daily report's is non-durable

- **Alerts keep no durable state.** `_prev_state` lives only in memory
  (`scheduler.py:84`). A restart loses it; combined with §1.2, the first poll
  after restart re-alerts on everything currently down.
- **Daily report dedup is in-memory + start-after-time fires immediately.**
  `_last_report_day` is in-memory (`scheduler.py:86`); `_report_due` returns
  true whenever `now >= report.time` and the day hasn't been marked
  (`scheduler.py:115-122`). Restart after the configured time re-sends the
  report. (Report behavior is documented here for completeness but its fix is
  out of scope for SP2 except where it shares the new state store.)

### 1.4 Channel coupling

Alert dispatch is hard-wired to SMTP: the tick calls `send_email(...)`
directly (`scheduler.py:149-156`). There is no seam for Slack/Teams/webhook.

### 1.5 Other observations (context, not in scope to fix here)

- `notifications.json` is written without `chmod` (`config.py:64-66`) — SMTP
  password is Fernet-encrypted so this is low-risk, but the new state file
  should follow whatever hardening the project adopts.
- Per-task timeouts in the parallel fetcher are weak; `collect_report_data`
  runs fetchers **serially** (`scheduler.py:34-38`) so a slow controller can
  stall a tick. Noted under Open Questions.

---

## 2. Approaches considered

All three keep the existing pure-function + due-logic test seams
(`evaluate`, `_alerts_due`, `_report_due`) and the SMTP mailer untouched. They
differ in **where outage state lives** and **how durable it is**.

### Approach A — Per-device snapshot diff with a JSON state file

Replace count-state with a **device inventory snapshot**:
`{device_key: {type, name, group, status, since}}`. Each tick diffs the new
snapshot against the previous one to produce **transition events**
(`went_offline` / `came_online`). Persist the snapshot + a small debounce
ledger to `<instance>/notify_state.json` (same dir/pattern as
`notifications.json`).

- **+** Minimal new infra — reuses the JSON-in-instance pattern the codebase
  already uses everywhere (config, profiles, secrets). No new dependency.
- **+** Durable across restart: load snapshot on boot, so a pre-existing
  outage is *not* re-alerted (fixes §1.2 and alert half of §1.3 together).
- **+** Diff naturally yields recovery events and per-device/per-site grouping.
- **−** Hand-rolled atomic write + (light) concurrency care (single writer
  thread, so low risk). JSON file grows with fleet size (a few hundred KB for
  thousands of devices — acceptable; can prune online devices).
- **−** No history/audit beyond the latest snapshot.

### Approach B — SQLite event + state store

A `notify_state.db` (stdlib `sqlite3`) with a `device_state` table (current
status, since, last-notified) and an `alert_log` table (audit of every
event/notification).

- **+** Durable, transactional, supports a future "alert history" UI and richer
  debounce/escalation queries.
- **+** Natural dedup via upsert + a `notified_at` column.
- **−** New persistence primitive the project has deliberately avoided so far
  (no `sqlite3`/`shelve`/`pickle` anywhere in `ruckus_dashboard/` today —
  verified). Adds schema/migration surface and threading/`check_same_thread`
  care.
- **−** Heavier than the problem needs for the single-writer daemon.

### Approach C — Keep count-state; add hysteresis + persist counts only

Persist `prev_state` counts to JSON and add an N-consecutive-polls debounce on
the counts, plus a "count fell" recovery message.

- **+** Smallest diff; closest to today's code and tests.
- **−** Does **not** deliver the core requirement: counts can't name *which*
  device or *which* site, and "offline count fell by 1" is a poor recovery
  notice (which device? operators need the name). Recovery and per-site
  grouping are explicitly requested. **Rejected** as not meeting the goal.

---

## 3. Recommendation

**Adopt Approach A — per-device snapshot diff with a durable JSON state file**,
structured behind a small **state-store interface** and an extensible
**notification-channel interface**.

Rationale: it directly satisfies every SP2 requirement (per-device + per-site
grouping, recovery events, debounce, restart-durability, all three device
types) while staying faithful to the codebase's established "small JSON files
in `instance_path`, encrypted where sensitive, no DB" convention. The
state-store is defined as an interface so Approach B (SQLite) becomes a
drop-in later if an alert-history UI is wanted — without re-touching rules or
the scheduler. SQLite (B) is deferred, not discarded.

---

## 4. Design of the recommended approach

### 4.1 Data model

**Device key (stable identity).** `f"{type}:{id}"` where `type ∈
{ap, switch, controller}` and `id` is:

- AP → `mac` (falls back to `name`) — `modules/aps.py:95,105`.
- Switch → `id`/`mac` — `modules/switches.py:169,185`.
- Controller node → `nodeId`/`nodeName` — `modules/controller.py:36`.

**DeviceStatus snapshot** (one entry per known device), produced each poll:

```text
DeviceStatus = {
  key:    str,            # "ap:aabbcc..."
  type:   str,            # ap | switch | controller
  name:   str,
  group:  str | None,     # AP zone | switch group/stack | "controller"
  online: bool,           # derived: status == "online"/"in_service"/node-online
  raw_status: str,        # the normalized status string for the message
  last_change: float,     # epoch when online flipped (carried forward)
}
```

`online` derivation reuses each module's existing normalization so we do not
re-implement vendor status vocab:
- AP: `status == "online"` (`aps.py:86-93`).
- Switch: `status not in {offline,...}` already normalized to `online`
  (`switches.py:158-166`).
- Controller node: `state.lower() in controller._NODE_ONLINE`
  (`controller.py:16-17`) — exposed via a tiny helper so the constant isn't
  duplicated.

**PersistedState** (`<instance>/notify_state.json`):

```text
{
  "version": 1,
  "devices": { "<key>": {type,name,group,online,raw_status,last_change,
                         pending_since,pending_target} },
  "report":  { "last_report_day": "YYYY-MM-DD" }   # moved off in-memory field
}
```

`pending_since` / `pending_target` implement **debounce**: when a device's
observed `online` differs from its committed `online`, we record the candidate
new state and the time it was first seen. The change is only *committed* (and
an event emitted) once it has persisted for `debounce_seconds`
(or `debounce_polls`). This survives restart because it is in the file.

### 4.2 New configuration (additive, backward-compatible)

Extend `DEFAULTS["alerts"]` in `notify/config.py:17-20` (merge logic at
`config.py:29-37` already deep-merges new keys, so old files upgrade cleanly):

- `recovery: true` — also send "back online" notifications.
- `debounce_seconds: 120` — a status change must hold this long before it
  fires. (`0` = fire on first observation, preserving current eagerness.)
- `group_by: "site"` — `site` (AP zone / switch group) or `none` (flat list).
- `suppress_known_on_start: true` — on first run with **no prior state file**,
  seed the snapshot silently (no alerts) so a fresh install / first-ever boot
  doesn't page on the entire current outage backlog.
- `channels` — see 4.5. Email remains the default channel; existing
  `recipients` is reinterpreted as the email channel's recipients for
  backward-compatibility.

`report.time` stays; `report.last_report_day` migrates from the in-memory
field to `notify_state.json` (4.4).

### 4.3 Components & data flow

```text
            ┌────────────────── NotifyScheduler._tick ──────────────────┐
 connection │                                                            │
 ──────────>│ collect_device_snapshot(conn, cfg)   # aps+switches+ctrl   │
            │        │  (reuses module fetchers; adds controller)        │
            │        ▼                                                    │
            │  snapshot: dict[key -> DeviceStatus]                       │
            │        │                                                    │
   state    │        ▼                                                    │
 ┌────────┐ │  OutageEngine.reconcile(prev_state, snapshot, cfg)         │
 │ store  │<┼──────────────┐  -> (events[], new_state)                   │
 │(.json) │ │              │     events = OutageEvent(kind=offline|online,│
 └────────┘ │   store.save(new_state)   device, group, ts)              │
            │        │                                                    │
            │        ▼ group + render                                     │
            │  render_alert(events, group_by) -> [Notification]          │
            │        │                                                    │
            │        ▼ for each enabled channel                          │
            │  channel.send(Notification)   # EmailChannel today         │
            └────────────────────────────────────────────────────────────┘
```

**`OutageEngine.reconcile(prev, snapshot, cfg)` — pure function (testable).**
Inputs: previous PersistedState `devices`, current snapshot, alert config.
Logic per device key (union of prev ∪ snapshot keys):

1. Determine `observed_online` from snapshot (a key absent from snapshot but
   present in prev = "device no longer reported" → treated as **offline**
   after debounce; configurable, see Open Questions).
2. Compare to committed `online`. If equal → clear any `pending_*`.
3. If different and no pending → set `pending_since = now`,
   `pending_target = observed_online`.
4. If different and pending matured (`now - pending_since >= debounce_seconds`)
   → **commit**: flip `online`, set `last_change=now`, clear pending, emit an
   `OutageEvent` (`offline` or `online`).
5. Recovery events only emitted when `cfg.recovery` is true.

This single function replaces both `rules.evaluate` *and* the implicit baseline
behavior: because committed state is loaded from disk, a pre-existing outage
has `online=false` already committed → **no event** on restart/reconnect
(fixes §1.2 + §1.3-alerts).

**Grouping & rendering.** `render_alert(events, group_by)` produces one
Notification with a structured body: events grouped by `group` (zone/switch
group/"controller"), offline section then recovered section, each line
`name (type) — was online for / down since …`. A subject summarizing counts,
e.g. `"[RUCKUS DSO] 4 devices offline, 1 recovered (HQ, Branch-2)"`.

**Threshold semantics.** `offline_threshold` is reinterpreted: instead of "fire
when the global count ≥ N", it becomes "only fire a batch when **≥ N devices**
are newly offline in this tick" (default 1 = every device). Keeps the config
key meaningful without count-state. (Confirm in Open Questions.)

### 4.4 Durable state store (interface seam)

```text
class OutageStateStore(Protocol):
    def load(self) -> PersistedState: ...
    def save(self, state: PersistedState) -> None: ...
```

Default impl `JsonOutageStateStore(instance_path)`:
- Path `<instance>/notify_state.json`.
- **Atomic write**: write `notify_state.json.tmp` then `os.replace` (mirrors
  the proven pattern in `auth/secrets.py:89-91`); best-effort `chmod(0o600)`.
- Tolerant load: missing/corrupt file → empty `PersistedState`
  (mirror `config.load_config`'s `except (OSError, ValueError)` at
  `config.py:45-46`).
- Single writer (the daemon thread), so no cross-process locking needed; the
  scheduler already serializes via `self._lock` (`scheduler.py:83`).

Swapping in a `SqliteOutageStateStore` later satisfies the same Protocol.

### 4.5 Notification-channel interface (extensible; email only now)

```text
@dataclass(frozen=True)
class Notification:
    subject: str
    body: str
    events: tuple[OutageEvent, ...]        # structured, for non-text channels

class NotificationChannel(Protocol):
    name: str                              # "email" | "slack" | ...
    def is_configured(self, cfg: dict) -> bool: ...
    def send(self, cfg: dict, secrets, note: Notification) -> None: ...
```

- **`EmailChannel`** — the only implementation in SP2. `send()` wraps the
  existing `mailer.send_email` (`notify/mailer.py:60`) using
  `note.subject`/`note.body` and the email channel's recipients. **No change
  to `mailer.py`.**
- A `CHANNELS` registry maps name→channel (same lightweight pattern as the
  module `register()` registry, `modules/__init__.py:7-11`). The scheduler
  iterates configured channels; today only `email` is configured.
- Config `alerts.channels` example (forward-compatible, unused keys ignored):
  ```text
  "channels": { "email": {"enabled": true, "recipients": ["noc@x"]} }
  ```
  Backward-compat: if `channels` is absent, synthesize
  `{"email": {"enabled": alerts.enabled, "recipients": alerts.recipients}}`
  from existing fields so current configs keep working with zero migration.
- **Out of scope (designed-for, not built):** `SlackChannel`,
  `TeamsChannel`, `WebhookChannel` — each is a new file implementing
  `NotificationChannel`; the only wiring is one `register()` line and a config
  block. No core changes required to add them. SSRF note: a future
  webhook/Slack channel posts to an **operator-entered URL**, so it must route
  through the existing `net/allowlist.py` host check — flagged in Open
  Questions so it's not forgotten when those land.

### 4.6 Scheduler integration (`notify/scheduler.py`)

Changes are localized to `_tick` and the collector; the daemon/loop, locking,
and due-logic seams are preserved.

- `collect_report_data` (`scheduler.py:22-39`) is **kept as-is** for the daily
  report. Add a sibling `collect_device_snapshot(connection, config) ->
  dict[key, DeviceStatus]` that runs the `aps`, `switches`, and **`controller`**
  fetchers and normalizes to DeviceStatus. (APs/switches already carry
  `status`+identity+group; controller contributes node rows.)
- In `_tick` (`scheduler.py:132-156`) the alerts branch becomes: load state →
  `collect_device_snapshot` → `OutageEngine.reconcile` → `store.save` →
  `render_alert` → dispatch via channels. `self._prev_state` (in-memory) is
  removed in favor of the store.
- `set_connection` (`scheduler.py:100-103`) **stops nulling prev state** — the
  durable store is the source of truth; reconnect must not re-baseline. (This
  is the core §1.2 fix.) On a *new* connection we still load committed state;
  `suppress_known_on_start` only suppresses when the file is **absent**.
- `_report_due` (`scheduler.py:115-122`) reads/writes `last_report_day` from the
  store instead of the in-memory field, fixing the report half of §1.3. To
  stop the start-after-time immediate fire, persist `last_report_day` and add a
  guard so a report is sent only when the previous run day is strictly before
  today *and* we are within a grace window after `report.time` (e.g. don't
  back-fire if the app starts hours late — Open Question on exact policy).

### 4.7 Routes & UI (`routes/notifications.py`, templates/static)

- No new endpoints strictly required. The existing config GET/POST
  (`routes/notifications.py:33-51`) carries the new `alerts.*` keys for free
  (JSON passthrough + `_merged`).
- `POST /api/notifications/test` (`notifications.py:54-83`): extend the
  `kind == "alerts"` branch to optionally render a **sample grouped outage**
  body so operators preview the new format. The route already catches and
  surfaces `send_email` errors; keep that.
- UI (`notifications.html` + `notifications.js`): add controls for `recovery`,
  `debounce_seconds`, and `group_by`. (Frontend detail; this spec only notes
  the new fields. The HTML-escaping test for controller strings still applies
  to any device name we render client-side.)

### 4.8 Error handling

- **Per-channel isolation:** a channel `send()` failure is caught, logged
  (`LOG.exception`), and must **not** prevent other channels or block the tick
  — mirrors the existing best-effort tick (`scheduler.py:129-130,155-156`).
- **State-store durability vs. duplicate suppression:** commit the engine's new
  state to the store **before** dispatching notifications. If a send then
  fails, we have already recorded the device as offline, so we won't re-alert
  on the next tick. Trade-off: a transient SMTP failure means that one outage
  notification is lost rather than duplicated. This is the safer default for
  "stop the spam" (alternative — save after successful send — risks loops on a
  persistently failing SMTP server). Called out in Open Questions.
- **Collector failures:** if a device-type fetch throws, that type is treated
  as "no data this tick" and its devices are **left unchanged** (not marked
  offline), preventing a controller API hiccup from paging the whole fleet.
  (Same defensive spirit as `collect_report_data`'s per-slug `try/except`,
  `scheduler.py:34-38`.)
- **Corrupt/old state file:** load returns empty state; with
  `suppress_known_on_start` the first post-corruption tick re-seeds silently.

### 4.9 Files & functions that change

New:
- `notify/outage.py` — `DeviceStatus`, `OutageEvent`, `OutageEngine.reconcile`
  (pure), `render_alert`, `device_online()` helpers. **Core, fully unit-tested.**
- `notify/state_store.py` — `OutageStateStore` Protocol + `JsonOutageStateStore`
  (atomic write, tolerant load).
- `notify/channels.py` — `Notification`, `NotificationChannel` Protocol,
  `EmailChannel`, `CHANNELS` registry.

Modified:
- `notify/config.py` — extend `DEFAULTS["alerts"]` (`config.py:17-20`) with
  `recovery`, `debounce_seconds`, `group_by`, `suppress_known_on_start`,
  `channels`; keep deep-merge (`config.py:29-37`) so existing files upgrade.
- `notify/scheduler.py` — add `collect_device_snapshot`; rewrite the alerts
  branch of `_tick` (`scheduler.py:140-156`) to engine+store+channels; remove
  `_prev_state` (`scheduler.py:84,103,147`); move `last_report_day`
  (`scheduler.py:86,119,159`) into the store; stop nulling state in
  `set_connection` (`scheduler.py:102-103`).
- `notify/rules.py` — **retired** for outage alerting (replaced by
  `OutageEngine`). Keep the `poor_client_ap` degradation rule if still wanted,
  or fold it into the engine as a non-device "advisory" event. (Open Question.)
- `routes/notifications.py` — optional richer `kind=="alerts"` test body
  (`notifications.py:61-66`).
- `templates/notifications.html`, `static/notifications.js` — new fields.

Unchanged: `notify/mailer.py`, `reports/excel.py`, `app.py` wiring
(`app.py:41-45`), `routes/connect.py` `set_connection` call site
(`connect.py:86-87`).

### 4.10 Testing

Pure-function tests (no I/O), extending `tests/unit/notify/test_notify.py`:

- **Baseline suppression:** load a state with `ap:x` already `online=false`;
  `reconcile` over a snapshot where `ap:x` is still offline → **no events**
  (the §1.2 regression test; explicitly inverts the current
  `test_rules_fire_on_transition_only` baseline assumption at
  `test_notify.py:56-57`).
- **Offline transition:** previously-online device disappears/offline for
  ≥ `debounce_seconds` → one `offline` event with name+group.
- **Debounce:** offline for < debounce → no event; matures on a later tick.
  Flap (offline→online within debounce) → no event (no churn).
- **Recovery:** offline→online after debounce with `recovery:true` → `online`
  event; with `recovery:false` → none.
- **Grouping:** mixed AP-zone + switch-group + controller events render into
  the right sections; subject counts correct.
- **Controller node down:** node `state` leaves `_NODE_ONLINE` → offline event
  typed `controller`.
- **Threshold:** `offline_threshold=3` with 2 new-offline → suppressed.

Store tests:
- Roundtrip save/load; corrupt file → empty state; atomic-replace leaves no
  `.tmp`; `chmod` best-effort doesn't raise on Windows.

Channel tests:
- `EmailChannel.send` calls `mailer.send_email` with the rendered
  subject/body/recipients (monkeypatched smtp, like
  `test_notify.py:172-194`); a raising channel is swallowed by the dispatcher
  and doesn't stop a second channel.

Scheduler tests (preserve existing seams):
- `_alerts_due` / `_report_due` unit tests still pass; add a
  `_report_due` test proving restart-after-time doesn't re-send when
  `last_report_day == today` is loaded from the store
  (extends `test_report_due_once_per_day_after_time`,
  `test_notify.py:92-104`).

Integration (`tests/integration/test_notifications_api.py`):
- Config roundtrip now carries `recovery`/`debounce_seconds`/`group_by`
  (extends `test_notifications_config_roundtrip_masks_password`,
  `test_notifications_api.py:27-41`); auth/CSRF still enforced.

---

## 5. Open questions for the user

1. **Debounce default.** Is `120 s` (≈2–4 polls at `check_seconds=300`/tick
   30 s) the right default, and should it be expressed in seconds or in
   consecutive-poll count? Note `check_seconds` default is 300
   (`config.py:18`), so a 120 s debounce effectively means "must still be down
   at the next alert check."
2. **"Device disappeared from inventory" = offline?** If a fetch returns a
   device list that omits a previously-known AP (vs. listing it as offline),
   should we treat the omission as offline (after debounce), or only trust an
   explicit offline status? Affects false positives when the controller
   paginates/filters.
3. **Recovery default on or off?** Some NOCs want "back online" noise; others
   only want outage pages. Proposed default `recovery: true`.
4. **Send-vs-save ordering on SMTP failure.** Proposed: commit state first, so
   a failed send drops that one notification rather than risking a re-alert
   loop. Acceptable, or must every outage be retried until delivered (which
   reintroduces spam risk on a dead SMTP server)? A bounded retry/outbox is a
   possible middle ground (larger scope).
5. **`offline_threshold` re-interpretation.** OK to redefine it as
   "min newly-offline devices per batch" (default 1)? Today it gates a global
   count (`rules.py:21`).
6. **Fate of the `poor_client_ap` degradation rule** (`rules.py:36-42`). Keep
   it as a separate advisory alert, fold it into the engine as a non-device
   event, or drop it from SP2? It is not an outage and doesn't fit the
   device-state model cleanly.
7. **Per-site recipient routing.** SP2 sends all outage events to the single
   alert recipient list. Do you want per-zone/per-group recipient routing now,
   or is fleet-wide one list sufficient for this round?
8. **State file location/retention.** Confirm `<instance>/notify_state.json`
   (alongside `notifications.json`) and that pruning recovered/online devices
   from the file (to bound size) is acceptable, vs. keeping a full inventory.
9. **Multi-controller.** Prior design declared "first active connection wins"
   (`2026-06-10` non-goals); `set_connection` still holds one connection
   (`scheduler.py:100`). Keep single-connection for SP2, or must outage state
   span multiple controllers (device keys are globally unique by MAC, so the
   store could, but the scheduler holds one connection today)?
10. **Webhook/Slack SSRF.** Confirm that when the deferred channels land, their
    target URLs must pass `net/allowlist.py` (operator-entered URLs are an SSRF
    vector). Design assumes yes.
