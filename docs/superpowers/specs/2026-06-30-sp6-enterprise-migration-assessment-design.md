# SP6 — Enterprise-Class Migration Assessment (Design Spec)

**Status:** Decision gate (no implementation). Shapes SP2/SP3.
**Date:** 2026-06-30
**Scope:** Architecture assessment only. This document contains **no implementation code** beyond tiny illustrative signatures. It reads the current code, diagnoses the limits, proposes three target architectures, and recommends a phased path with milestones.

Repo root used for all paths below:
`C:\Users\sshoaib\OneDrive - Mohamed & Obaid Almulla LLC\Documents\RUCKUS-Dashboard` (referred to as `<root>`).

---

## 1. Problem statement + current behavior (grounded in code)

The dashboard today is an **excellent single-operator appliance** and a **poor enterprise multi-user service**. Every design decision optimizes for "one operator, one box, on a NOC wall," and those decisions are load-bearing throughout the codebase. Migrating to enterprise-class means changing the **state model** and the **trust model**, not just the deployment topology.

### 1.1 State lives in one Python process, in RAM

- **Authenticated controller connections are in-memory only.** `app.connection_store = ConnectionStore(...)` is constructed per process in `RUCKUS/ruckus_dashboard/app.py:34`. The store is a plain `dict` guarded by an `RLock` with eviction-on-access (`RUCKUS/ruckus_dashboard/auth/session_store.py:29-71`). There is no persistence and no shared backend. **Consequence:** a process restart drops every active connection; operators must re-login (confirmed by the DEPLOY backup note "Lose `secret_key` → existing browser sessions invalidate", `docs/DEPLOY.md:213`). Two processes cannot share connections, so **horizontal scale is impossible without sticky sessions, and even then state is lost on the node that holds it**.
- **`available_ops` (capability set) is a single process-global mutable set.** `app.available_ops = set()` (`app.py:50`), mutated on connect via `current_app.available_ops = set(...) | set(ops)` (`routes/connect.py:142`) and reset to `set()` on logout (`routes/connect.py:113`). This is **shared across all sessions in the process** — there is exactly one global capability set, not one per connection. With one operator this is fine; with two operators on different controllers it is a correctness bug (operator B's logout wipes operator A's capability gating; operator B's controller capabilities leak into operator A's module visibility).
- **`warmup_scheduler` is a single process-global slot.** `app.warmup_scheduler = None` (`app.py:39`); every `/connect` cancels the previous one and replaces it (`routes/connect.py:72-83`). **One warmup at a time, process-wide** — a second operator logging in cancels the first operator's warmup.
- **The module result cache and in-flight deduper are in-process** (`app.module_cache = ModuleResultCache()` `app.py:38`; `app.inflight = InFlightDeduper()` `app.py:46`; cache impl `infra/cache.py`). Not shared, lost on restart.

**Net:** the unit of state is the OS process. This is the single most important fact for the migration.

### 1.2 Credentials are per-session and process-resident

- On `/connect`, `authenticate_connection(...)` produces a `ConnectionConfig` containing a live `auth_token` (SmartZone serviceTicket / RUCKUS One OAuth bearer), stored in RAM and keyed by an opaque token (`auth/session_store.py:14-43`). The browser cookie holds only `connection_ids` (`routes/connect.py:61`). **Secrets-at-rest** (`auth/secrets.py`) only ever encrypts *saved profile passwords* and the *SMTP password* — never the live controller tokens, which exist only in process memory.
- There is **no concept of a user**. `session["auth"] = True` (`routes/connect.py:61`) is a boolean. Anyone who can reach the port and complete a controller login is "the operator." There are **no user accounts, no roles, no per-user authorization** — `module_data` gates only on `session.get("auth")` and the global capability set (`routes/modules.py:72,81-82`).

### 1.3 Synchronous Flask + daemon threads + dev server

- The app is served by the **Werkzeug development server** with `threaded=True`: `app.run(host=..., ssl_context=(cert,key), debug=False, use_reloader=False, threaded=True)` (`cli.py:260-262`). There is **no WSGI/ASGI production server** (no gunicorn/uwsgi/waitress in `pyproject.toml:10-17` — deps are flask, requests, urllib3, cryptography, python-dotenv, openpyxl only). DEPLOY runs this same `python -m ruckus_dashboard` under systemd/NSSM (`docs/DEPLOY.md:83,113`).
- **All upstream I/O is synchronous `requests`.** `request_json(...)` calls `requests.request(method, url, timeout=...)` (`clients/base.py:234`). Each module fetch blocks a worker thread for the full upstream round-trip.
- **Two daemon threads carry background work.** `NotifyScheduler` is a single daemon thread on a 30 s tick (`notify/scheduler.py:91-95,125-130`); `WarmupScheduler` spawns a `warmup` daemon thread that itself drives a `ThreadPoolExecutor` (`infra/warmup.py:99-102`, `infra/parallel_fetch.py:37`). State for both lives in instance attributes / module-globals.
- **The per-task timeout in `ParallelFetcher` is illusory.** `run()` uses `concurrent.futures.wait(..., timeout=...)` then exits the `with ThreadPoolExecutor()` block (`infra/parallel_fetch.py:37-59`). The context manager's `__exit__` calls `shutdown(wait=True)`, which **blocks until the straggler thread actually finishes**; `future.cancel()` cannot cancel an already-running task. So a hung upstream call holds a thread until the OS socket timeout, regardless of the configured warmup timeout. This is a concurrency-model smell that becomes a real availability problem under multi-user load.

### 1.4 Single-tenant, single-node persistence

- The only durable state is **files in `instance/`**: `secret_key` (`config.py:59-70`), the self-signed cert/key (referenced in `cli.py:249` and `docs/DEPLOY.md:49`), Fernet master key `.secret_master` (`auth/secrets.py:118`), `profiles.json` (`auth/profiles.py:49`), and `notifications.json` (`notify/config.py:25`). **There is no database.** All writes are local-filesystem `tmp + replace` (`auth/profiles.py:63-74`, `notify/config.py:64-66`). DEPLOY explicitly says back up `instance/` and that it "survives the upgrade" (`docs/DEPLOY.md:198-211`) — i.e. node-local durability only.
- **Notification config is global, not per-tenant/per-user.** One `notifications.json` (`notify/config.py:25`) → one SMTP server, one alert recipient list, one report schedule for the whole deployment.

### 1.5 TLS and trust posture

- **Self-signed HTTPS by default** generated on first boot (`cli.py:249`, `docs/DEPLOY.md:49`). Enterprise TLS is delegated to an nginx reverse proxy with `proxy_ssl_verify off` (`docs/DEPLOY.md:147`). No mTLS, no cert lifecycle.
- **SSRF allow-list defaults to disabled** when empty (`net/allowlist.py:42` sets `self.enabled = bool(self.names or self.networks)`; `host_allowed` returns `True` when `not self.enabled`, `:63-66`). README/DEPLOY require operators to set `RUCKUS_ALLOWED_HOSTS` for non-loopback binds (`README.md:76,127-129`). The known SSRF-via-redirect gap (no `allow_redirects=False` in `clients/base.py:234`) means a 3xx from a controller can still bypass the allow-list. **For an internet-exposed multi-tenant service these defaults invert (must be deny-by-default).**

### 1.6 Observability

- Logging only: a `request_id` is minted per request (`app.py:90`) and used in the error handler (`app.py:98-100`); `configure_logging` writes to `instance/` (`app.py:32`). **No metrics, no tracing, no health/readiness split beyond `/healthz`** (`app.py:102-104`), no structured-log shipping. Adequate for one box; insufficient to operate a fleet.

### 1.7 What is already enterprise-friendly (assets to preserve)

The migration is **not** a rewrite. The codebase has strong seams:

- **App-factory pattern** (`create_app(test_config)` `app.py:23`) — trivially supports config injection and multiple worker processes.
- **Blueprint-per-concern routing** (`app.py:52-66`) and **one-file-per-module `ModuleSpec` registry** (README architecture, `routes/modules.py:6`) — clean extension points untouched by the migration.
- **All controller state already flows through three injectable singletons** (`connection_store`, `module_cache`, `available_ops`) attached to `app`. Swapping their *implementation* (RAM → Redis/Postgres) is a contained change because callers go through `current_app.connection_store.get(...)` etc. (`routes/modules.py:76`, `routes/connect.py:55`).
- **A `FetcherContext` already abstracts a fetch** (`routes/modules.py:95`, `infra/warmup.py:131`) — the same fetcher runs in request, warmup, and notify paths. This is the natural unit to move onto an async worker.
- **CSRF, security headers, redaction, capability gating** are already implemented (`auth/csrf.py`, `app.py:68-86`, `clients/base.py:67-79`).

---

## 2. Approaches (target architectures) with trade-offs

Three targets, matching the brief: (A) hardened single-node appliance, (B) multi-user enterprise, (C) phased A→B.

### Approach A — Hardened single-node appliance

Keep the single-process model; fix the rough edges so it is a *defensible* product for the "one NOC, one box" use case. No DB, no Redis, no horizontal scale.

**Changes:** replace Werkzeug dev server with **waitress** (pure-Python, Windows-friendly, matches the existing cross-platform story) or gunicorn on Linux with **a single worker** (multi-worker breaks the in-RAM store — see §4.1); add `allow_redirects=False` in `clients/base.py`; make the SSRF allow-list **deny-by-default** for non-loopback; durable daily-report dedup (`_last_report_day` → a tiny `instance/notify_state.json`); fix `ParallelFetcher` straggler semantics (bound socket timeouts so threads can't outlive the warmup window); chmod `notifications.json`; switch DPAPI to `CURRENT_USER` scope or document the LOCAL_MACHINE risk; add `/readyz`; ship structured JSON logs.

| | |
|---|---|
| **Effort** | Low (≈1–2 dev-weeks). Mostly hardening existing code; the 7 "known issues" plus a production WSGI server. |
| **Risk** | Low. No data-model change, existing 301 tests largely still apply. |
| **Scale** | None. One process, one operator-set, vertical scale only. |
| **Multi-user / RBAC / SSO** | Not delivered. |
| **HA / restart resilience** | Still loses connections on restart (acceptable: operator re-logs in). |
| **Fit** | Correct if the product is and remains a wall-display appliance. |

### Approach B — Multi-user enterprise (target end-state)

Re-platform the state and trust model: **Postgres** (users, roles, tenants, saved profiles, notification configs, audit log), **Redis** (shared session/connection store, cache, in-flight dedup, Celery broker, pub/sub for SSE fan-out), **proper auth** (app user accounts + **OIDC/SAML SSO**, **RBAC**), **async workers (Celery)** for warmup/fetch/notify, **containerized** (Docker) and orchestrated (**k8s** or Compose), real TLS (ingress-terminated, optional mTLS to controllers), and **observability** (Prometheus metrics, OpenTelemetry traces, structured logs to a collector).

The in-RAM singletons become **service interfaces** with Redis/Postgres-backed implementations. Controller credentials move out of process memory into Redis (encrypted with the existing Fernet/`SecretsManager` envelope), keyed by `(user_id, connection_id)`. Warmup/notify become Celery tasks; SSE reads progress from Redis pub/sub so any web replica can serve the stream. `available_ops` becomes per-connection state in Redis, not a process global.

| | |
|---|---|
| **Effort** | High (≈8–14 dev-weeks, plus infra/ops setup). New persistence layer, auth subsystem, worker tier, container/CI/CD, migrations. |
| **Risk** | High if done big-bang. Touches every stateful seam; reworks the security model; introduces 3 new runtime dependencies (Postgres, Redis, broker). |
| **Scale** | Horizontal: N stateless web replicas + M workers; HA via managed Postgres/Redis. |
| **Multi-user / RBAC / SSO** | Delivered. Per-user connections, roles, tenant isolation, SSO. |
| **HA / restart resilience** | Connections survive web-tier restarts (state in Redis); rolling deploys possible. |
| **Fit** | Correct if the product must serve many operators / multiple customers / be centrally operated. |

### Approach C — Phased A→B (recommended)

Do **A first** (ship a hardened appliance, capture the value immediately and de-risk the security gaps now), then evolve to **B** behind **stable service interfaces** introduced during A. The key architectural move is to **extract three Protocols early** — `ConnectionStore`, `ResultCache`, and a new `CapabilityRegistry` (replacing the `available_ops` global) — so the RAM→Redis swap in phase B is an implementation change, not a caller rewrite. Auth is layered next (local accounts → SSO/RBAC) as a gate *in front of* the existing controller-login flow, not a replacement for it.

| | |
|---|---|
| **Effort** | A then B incrementally; same total as B but value lands in week 2, not month 3. |
| **Risk** | Low-then-medium. Each phase ships independently with green tests; no big-bang cutover. |
| **Scale** | Appliance now; horizontal later, gated on real demand. |
| **Fit** | Correct when the future is "probably multi-user, but prove the product first" — which matches a dashboard still adding modules. |

---

## 3. Recommendation

**Adopt Approach C (phased A→B), and start by executing Phase A in full while introducing the Phase-B service interfaces as seams.**

Rationale grounded in what the code is:

1. **The hardening work (A) is unavoidable regardless of destination.** The SSRF-redirect gap, alert baseline-spam, non-durable report dedup, illusory parallel-fetch timeout, dev-server-in-prod, and the secrets chmod/DPAPI-scope issues are liabilities *today*, on the appliance, for the single operator. They must be fixed before any enterprise exposure. Doing A first banks that value in ~2 weeks.
2. **The codebase is unusually well-seamed for the RAM→shared-state swap.** Because all controller state already routes through `current_app.connection_store`, `current_app.module_cache`, and `current_app.available_ops`, converting those three to interfaces (Phase A1) makes Phase B a backend swap rather than a refactor. We should **not** rewrite to async/Celery speculatively — the current sync model is fine for one node, and premature re-platforming is the larger risk.
3. **The biggest correctness landmine for multi-user is the `available_ops` process-global** (`app.py:50`, `routes/connect.py:113,142`). It is wrong the instant a second concurrent operator exists. Phase C makes fixing it (move to per-connection capability state) a milestone with a test, rather than discovering it in production.
4. **Defer the heavy infra (Postgres/Redis/Celery/k8s) until there is a committed multi-user requirement.** Approach B's cost is dominated by ops surface, not code. The phased path lets the business decide at the §5 "Gate B" milestone with a working product in hand.

**Do not** pick pure A if multi-tenant is a known near-term requirement (you'll pay the interface-extraction cost twice). **Do not** pick big-bang B (highest risk, longest time-to-value, and you'd be re-platforming a still-evolving module set).

---

## 4. Design of the recommended approach (Phase C)

### 4.0 Guiding principle

Introduce **interfaces at the three stateful seams now**, ship the appliance hardening behind them, then add **auth as a front gate** and **Redis/Postgres/Celery as alternate implementations** later. No caller in `routes/*` or `modules/*` should know whether state lives in RAM or Redis.

### 4.1 Components and the target topology

```
                         ┌──────────────────────────────────────────┐
   Browser ──TLS──▶ Ingress (real cert, OIDC at edge optional)       │
                         │                                            │
                ┌────────▼─────────┐        ┌──────────────────┐      │
                │  Web (Flask/WSGI │        │  Worker (Celery) │      │
                │  waitress→gunic.)│◀──────▶│  warmup / notify │      │
                │  N replicas (B)  │ broker │  / fetch tasks   │      │
                └───┬───────┬──────┘        └────────┬─────────┘      │
                    │       │                        │                │
        AppState interfaces │                        │                │
        ┌───────────┴───────┴────────┐               │                │
        │ ConnectionStore             │   ┌───────────▼──────────┐     │
        │ ResultCache                 │──▶│ Redis (B): sessions, │     │
        │ CapabilityRegistry          │   │ cache, dedup, broker,│     │
        │ NotifyStateStore            │   │ SSE pub/sub          │     │
        └───────────┬─────────────────┘   └──────────────────────┘     │
                    │                      ┌──────────────────────┐     │
                    └─────────────────────▶│ Postgres (B): users, │     │
                                           │ roles, tenants,      │     │
   Phase A: all interfaces backed by       │ profiles, notify cfg,│     │
   in-RAM / instance-file impls;           │ audit                │     │
   single process. Redis/PG are            └──────────────────────┘     │
   the Phase-B implementations.            (upstream: SmartZone/RUCKUS One via requests)
```

**Phase A topology** is identical minus Redis/Postgres/Worker: one WSGI process (waitress on Windows, gunicorn `--workers 1 --threads N` on Linux), interfaces backed by the existing RAM/file implementations. *Multi-worker is explicitly forbidden in Phase A* because the in-RAM `ConnectionStore` is not shared — a 4xx "Connection expired" would appear on whichever worker lacks the connection. This is enforced by a config assertion (see §4.5).

### 4.2 The three seam interfaces (Phase A1 — the load-bearing change)

Define Protocols and make the existing classes the default implementations. Illustrative signatures only:

```python
# auth/connection_store.py (interface)
class ConnectionStore(Protocol):
    def put(self, conn: ConnectionConfig, *, owner: str | None = None) -> str: ...
    def get(self, token: str, *, owner: str | None = None) -> ConnectionConfig | None: ...
    def remove(self, token: str) -> None: ...

# infra/capability_registry.py  (replaces app.available_ops global)
class CapabilityRegistry(Protocol):
    def set_for(self, connection_id: str, ops: set[tuple[str, str]]) -> None: ...
    def get_for(self, connection_ids: Sequence[str]) -> set[tuple[str, str]]: ...
    def clear(self, connection_id: str) -> None: ...
```

- **`ConnectionStore`**: today's `auth/session_store.py:ConnectionStore` becomes `InMemoryConnectionStore` implementing the Protocol. Add an `owner` parameter (unused/`None` in Phase A; carries `user_id` in Phase B). Phase-B impl: `RedisConnectionStore` storing the `ConnectionConfig` **with `auth_token` encrypted via the existing `SecretsManager`** (`auth/secrets.py:128-139`), TTL = `CREDENTIAL_TTL_SECONDS`.
- **`CapabilityRegistry`**: replaces the `app.available_ops` set. Phase A impl keeps a `dict[connection_id, set]` in RAM (fixes the multi-operator leak even on the appliance). Callers change: `routes/connect.py:142` → `registry.set_for(new_id, ops)`; `routes/modules.py:81` builds the gate from `registry.get_for(conn_ids)` instead of the global; `routes/connect.py:113` logout → `registry.clear(cid)`.
- **`ResultCache`**: today's `infra/cache.py:ModuleResultCache` already has a clean key/TTL surface; lift a Protocol over it. Phase-B impl: `RedisResultCache` (same key tuple, JSON value).
- **`NotifyStateStore`** (small, new): persists `_last_report_day` and `_prev_state` so the notify daemon is restart-safe. Phase A impl: `instance/notify_state.json`; Phase B impl: Postgres row / Redis key. This directly resolves the "daily-report dedup non-durable" and "alert baseline-spam on restart" issues.

All four are attached in `create_app` exactly where the current singletons are wired (`app.py:34-50`), selected by a `RUCKUS_STATE_BACKEND` config value (`memory` default; `redis` in Phase B).

### 4.3 Data flow (unchanged shape, swapped backing)

**Login (`/connect`)** — `routes/connect.py`:
1. (Phase B) Edge/OIDC authenticates the *user*; `before_request` populates `g.user`. Phase A: unchanged (controller login is the only auth).
2. `authenticate_connection(form, config)` → `ConnectionConfig` (unchanged, `connect.py:45`).
3. `connection_store.put(conn, owner=g.user.id)` → `connection_id` (interface call; RAM or Redis).
4. `capability_registry.set_for(connection_id, discovered_ops)` (replaces the global mutation at `connect.py:142`).
5. Warmup: Phase A keeps `WarmupScheduler.run_in_thread()` (`connect.py:84`); Phase B enqueues `warmup_task.delay(connection_id)` to Celery and the scheduler writes progress to Redis pub/sub.

**Module fetch (`/api/modules/<slug>`)** — `routes/modules.py:67-120`: identical control flow; the only change is the gate is built from `capability_registry.get_for(conn_ids)` and the cache is the `ResultCache` interface. The per-controller error envelope (`modules.py:100-120`) is preserved verbatim — it is already correct.

**Warmup SSE (`/api/warmup`)** — `routes/warmup.py:23-63`: Phase A unchanged (reads the in-process scheduler). Phase B: the generator subscribes to a Redis channel keyed by `connection_id` instead of `scheduler.add_listener()`, so any web replica can serve the stream regardless of which worker ran the warmup.

**Notify daemon** — `notify/scheduler.py`: Phase A keeps the daemon thread but reads/writes `NotifyStateStore` for dedup and loads `_prev_state` on boot (fixing baseline-spam and restart re-send). Phase B converts the 30 s tick to a **Celery beat** schedule; `collect_report_data` (`notify/scheduler.py:22-39`) becomes a task. Per-tenant notification config is read from Postgres instead of the single `notifications.json`.

### 4.4 Auth, RBAC, SSO (Phase B, layered in front)

- **App users** table in Postgres (`id, email, display_name, password_hash|null, is_active`). Local login for air-gapped installs; **OIDC/SAML** for enterprise (Authlib for OIDC; SAML via an IdP-fronted proxy). The session cookie carries `user_id`; `session["auth"]` stays as the controller-connected flag (`modules.py:72`), so the existing checks compose.
- **RBAC** as a decorator over blueprints: roles `viewer` (read tiles), `operator` (also manage own connections/notifications), `admin` (tenants, users, SMTP). Enforced in `before_request`/route decorators; the capability gate (`infra/capability_gate.py`) stays as the *controller-capability* layer beneath RBAC.
- **Tenancy**: every `ConnectionConfig`, profile, and notification config row carries `tenant_id`; `connection_store.get(token, owner=...)` rejects cross-tenant access. This makes "one SMTP / one recipient list" (`notify/config.py:14-22`) into per-tenant config.

### 4.5 Error handling

- **Backend unavailability (Phase B):** Redis/Postgres outages must degrade, not 500. `ConnectionStore.get` on a Redis error → treat as "connection expired" (return `None`), which the existing `modules.py:78-79` path already renders as a clean re-auth 401. Postgres outage on a read path → 503 from a readiness probe; writes (save profile/config) surface the existing "could not persist" warning pattern (`auth/profiles.py:73-74`).
- **Worker failures (Phase B):** a Celery task crash maps to the existing `WarmupStatus(status="failed", error_message=...)` envelope (`infra/warmup.py:91-93`) so the UI is unchanged.
- **Config guardrail:** in `create_app`, if `RUCKUS_STATE_BACKEND == "memory"` **and** the server is launched with >1 worker, fail fast with a clear error (prevents the silent "connection expired on every other request" failure mode). If `RUCKUS_STATE_BACKEND == "redis"`, assert connectivity at boot and refuse to start otherwise (fail-closed).
- **SSRF hardening (Phase A):** add `allow_redirects=False` to `requests.request` in `clients/base.py:234` and re-run `assert_host_allowed` on any redirect target; flip the allow-list to deny-by-default when bind is non-loopback (today `net/allowlist.py:42` is allow-all-when-empty). These are correctness fixes, not new features.

### 4.6 Concrete files / functions that change

**Phase A (hardening + seams), all under `<root>\RUCKUS\ruckus_dashboard\`:**

| File / function | Change |
|---|---|
| `pyproject.toml:10-17` | Add `waitress` (Win) / `gunicorn` (Linux) as a production server; pin a `[server]` extra. |
| `cli.py:259-262` (`main`) | Stop using `app.run(... threaded=True)` for non-dev; launch via waitress/gunicorn. Keep `app.run` only behind `--debug`. |
| `clients/base.py:234` (`request_json`) | `allow_redirects=False`; re-assert allow-list on 3xx `Location`. |
| `net/allowlist.py:42,63-66` | Deny-by-default for non-loopback binds (config-driven). |
| `app.py:34,38,50` (`create_app`) | Wire `ConnectionStore`/`ResultCache`/`CapabilityRegistry`/`NotifyStateStore` interfaces selected by `RUCKUS_STATE_BACKEND`; add `>1 worker + memory` guardrail. |
| `auth/session_store.py` | Rename concrete class → `InMemoryConnectionStore`; add `owner` param to `put/get`; declare Protocol (new `auth/connection_store.py`). |
| New `infra/capability_registry.py` | `CapabilityRegistry` Protocol + in-memory impl. |
| `routes/connect.py:113,142` (`_refresh_available_ops`, `logout`) | Use the registry per-connection instead of the `available_ops` global. |
| `routes/modules.py:81` (`module_data`) | Build gate from `capability_registry.get_for(conn_ids)`. |
| New `notify/state_store.py` + `notify/scheduler.py:115-123,158-159` | Durable `_last_report_day`/`_prev_state`; load on boot. |
| `notify/config.py:64-66` (`save_config`) | `chmod(0o600)` the written `notifications.json` (parity with profiles `auth/profiles.py:69-72`). |
| `auth/secrets.py:27,45-46` | Document/parameterize DPAPI scope (LOCAL_MACHINE → consider CURRENT_USER); fix chmod-after-write ordering. |
| `infra/parallel_fetch.py:37-59` (`run`) | Make per-task timeout real: bound the upstream socket timeout so threads cannot outlive the warmup window; don't block on stragglers in `__exit__`. |
| `app.py:102` | Add `/readyz` (readiness) distinct from `/healthz` (liveness). |
| `logging_setup` (referenced `app.py:32`) | Structured JSON log option for shipping. |

**Phase B (additive implementations, mostly new files):**

| Area | Files |
|---|---|
| Redis impls | `auth/connection_store_redis.py`, `infra/cache_redis.py`, `infra/capability_registry_redis.py` |
| Persistence | new `db/` package (SQLAlchemy models + Alembic migrations): users, roles, tenants, profiles, notify_config, audit |
| Auth/RBAC/SSO | new `auth/users.py`, `auth/oidc.py`, `auth/rbac.py`; decorators applied in `routes/*` |
| Workers | new `tasks/` (Celery app, `warmup_task`, `notify_task`, `fetch_task`); `notify/scheduler.py` → Celery beat |
| SSE fan-out | `routes/warmup.py:30-58` generator reads Redis pub/sub |
| Packaging/infra | `Dockerfile`, `docker-compose.yml` (web/worker/redis/postgres), k8s manifests/Helm, CI/CD additions to `.github/workflows/ci.yml` |
| Observability | Prometheus `/metrics`, OpenTelemetry instrumentation, log shipping |

### 4.7 Testing strategy

- **Phase A — reuse the existing 301-test suite as a regression net.** The interface extraction must be behavior-preserving: existing tests for `ConnectionStore`, the module routes, and warmup should pass unchanged against the in-memory implementations (the dashboard-string-escaping test and the partial-envelope tests are the key guards).
- **New Phase A unit tests:** (a) SSRF redirect is blocked (mock a 3xx `Location` to a disallowed host); (b) `CapabilityRegistry` isolates two connections (operator-A ops do not leak to operator-B; B's logout doesn't clear A) — this is the regression test for the `available_ops` global bug; (c) `NotifyStateStore` survives a simulated restart (no duplicate daily report; no baseline-spam when `_prev_state` is reloaded); (d) `parallel_fetch` returns within `timeout + ε` even with a deliberately hung task; (e) boot guardrail rejects `memory + >1 worker`.
- **Phase B — contract tests over the Protocols:** run the *same* test suite against in-memory and Redis implementations of `ConnectionStore`/`ResultCache`/`CapabilityRegistry` (parametrized fixture) to prove behavioral equivalence. Add `testcontainers`-style Postgres/Redis integration tests in CI; RBAC/tenant-isolation tests (cross-tenant `get` denied); an SSE fan-out test (warmup on worker, stream from a different web process via Redis pub/sub).
- **CI matrix** stays Ubuntu+Windows×3.10–3.12; Phase B adds a Linux-only job for the container/integration tests (Redis/Postgres services).

---

## 5. Milestones (phased path)

| Milestone | Content | Exit criterion |
|---|---|---|
| **A1 — Seams** | Extract `ConnectionStore`/`ResultCache`/`CapabilityRegistry`/`NotifyStateStore` Protocols; in-memory impls; per-connection capability fix. | 301 tests green + new isolation test; no behavior change. |
| **A2 — Security hardening** | SSRF redirect fix, deny-by-default allow-list, `notifications.json` chmod, DPAPI scope decision, parallel-fetch timeout. | New SSRF/timeout tests green; `/security-review` clean on the diff. |
| **A3 — Production serving + ops** | waitress/gunicorn (single worker), `/readyz`, structured logs, durable notify state. | Runs under systemd/NSSM via WSGI server, not Werkzeug; restart no longer re-sends the daily report. **Ship the hardened appliance.** |
| **— Gate B —** | Business decision: is multi-user/multi-tenant committed? | Go/No-Go. If No, stop at A3 (Approach A delivered). |
| **B1 — Shared state** | Redis impls of the three interfaces; encrypted `auth_token` at rest in Redis; contract tests across impls; web tier becomes stateless (N replicas behind sticky-optional ingress). | Same suite green on Redis backend; survives web-replica restart. |
| **B2 — Identity** | Postgres + users/roles/tenants; local login + OIDC/SAML; RBAC decorators; per-tenant notification config. | RBAC + tenant-isolation tests green; SSO login works against a test IdP. |
| **B3 — Async + scale-out** | Celery workers + beat for warmup/notify/fetch; SSE via Redis pub/sub; Docker/Compose then k8s; Prometheus/OTel. | Warmup runs on a worker and streams to any web replica; metrics/traces visible; rolling deploy with no dropped sessions. |

---

## 6. Open questions for the user

1. **Is multi-user/multi-tenant actually required, and on what timeline?** This is the Gate-B decision and it determines whether we stop at Approach A (appliance) or invest in B. The whole recommendation hinges on it.
2. **Deployment OS for the enterprise target — Linux, Windows, or both?** It affects the WSGI server choice (gunicorn vs waitress), container strategy, and the DPAPI-vs-Fernet credential-at-rest story (`auth/secrets.py` is Windows-DPAPI-specific). DEPLOY supports both today (`docs/DEPLOY.md:5a/5b`).
3. **Air-gapped vs. internet-connected enterprise install?** Air-gapped rules out hosted IdPs (SSO) and managed Postgres/Redis, and changes the SSRF/TLS posture. The current product is explicitly air-gap-friendly (`docs/DEPLOY.md:24-30`).
4. **Identity provider standard** — OIDC (Okta/Entra/Auth0) or SAML? And is edge-terminated auth (ingress/oauth2-proxy) acceptable, or must auth live in-app for air-gapped local accounts?
5. **Expected scale** — peak concurrent operators, number of controllers/tenants, and tile-poll frequency? This sizes the worker tier and decides whether async (Celery) is even warranted over "single node, more RAM."
6. **Data residency / retention for the audit log and reports** — does enterprise require an audit trail (who connected to which controller, when) and report archival? That expands the Postgres schema in B2.
7. **Managed vs. self-hosted Postgres/Redis** in the target environment — drives the HA/ops effort estimate for B and whether k8s is justified or Compose suffices.
8. **Who operates the fleet?** If the customer runs it themselves, packaging/runbooks dominate; if it's centrally hosted (SaaS), multi-tenancy isolation and per-tenant secrets become first-class (and stricter).
