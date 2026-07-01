# Phase B — Identity, RBAC & Multi-Tenancy (single-node, air-gapped Windows) — Design Spec

**Status:** Design (no implementation). The re-scoped Phase B from the SP6 migration assessment.
**Date:** 2026-06-30.
**Decisions locked (user):** single Windows Server node, **no HA**, **on-prem/air-gapped**, **OIDC** against an on-prem IdP **+ a local break-glass admin**, **SQLite**, infra decided later (build infra-agnostic).

## 1. Scope — what Phase B is, and what the constraints removed

The SP6 assessment's Phase B was "Postgres + Redis + Celery + k8s + SSO." The locked constraints **collapse most of that**:

| SP6 Phase-B piece | Verdict under the constraints |
|---|---|
| **Redis** (shared state across replicas, SSE fan-out) | **Dropped.** One node, no HA → nothing to share. Durability comes from the DB. |
| **Celery** (async workers, scale-out) | **Dropped.** Poorly supported on Windows; no scale need. Keep the existing daemon-thread `NotifyScheduler` + `WarmupScheduler`. |
| **k8s / multi-replica / LB** | **Dropped.** Runs as an NSSM Windows service (DEPLOY already covers it). |
| **Postgres** | **→ SQLite.** Embedded file in `instance/`, zero extra service on the air-gapped box. SQLAlchemy + Alembic keep Postgres a one-line swap if scale ever appears. |
| **SSO / RBAC / multi-tenancy / audit** | **Kept — this is the actual ask.** |

**Phase B (re-scoped) = an enterprise identity + RBAC + multi-tenancy + audit layer on a single node, SQLite-backed, OIDC + local break-glass, no new runtime services.**

**Explicitly out of scope:** Redis, Celery, containers/k8s, horizontal scale, cross-replica anything. Live controller tokens stay in RAM (short-lived serviceTickets; re-login on restart is acceptable and avoids persisting controller credentials at rest).

## 2. Current state (what exists to build on)

- **No app-user concept.** `session["auth"] = True` is a boolean meaning "a controller connection exists" (`routes/connect.py`). Routes gate only on that + the per-connection `CapabilityRegistry` (SP7). Anyone who can reach the port and complete a controller login is "the operator."
- **File-based durable state** in `instance/`: `profiles.json` (`auth/profiles.py`), `notifications.json` (`notify/config.py`), Fernet master key, cert. All **global**, not per-user/tenant.
- **Strong seams already present:** app-factory (`create_app`), blueprint-per-concern, `SecretsManager` (Fernet+DPAPI) for encryption at rest, CSRF, security headers, the SP7 `CapabilityRegistry`/`ConnectionStore` interfaces, and `/readyz` (SP6 Phase A).

## 3. Architecture

### 3.1 Two-layer auth (the core new idea)

```
   Browser ──▶ [ Layer 1: APP-USER auth  ]  ← NEW (Phase B)
                 login (OIDC or local), session["user_id"], role, tenant_id
                        │
                        ▼
               [ Layer 2: CONTROLLER connection ]  ← existing (unchanged)
                 /connect → ConnectionConfig, session["connection_ids"], CapabilityRegistry
                        │
                        ▼
               [ Layer 3: controller CAPABILITY gate ]  ← existing (SP7)
```

- **Layer 1 is new**: a logged-in *app user* (who the operator is). `before_request` loads `g.user`/`g.tenant_id`/`g.role` from `session["user_id"]`.
- **Layer 2 unchanged**: a user then connects to one or more RUCKUS controllers exactly as today; those connections are now *owned by* the user/tenant.
- Every data route requires **both** a logged-in user (Layer 1) **and** a controller connection (Layer 2). The existing `session["auth"]` (controller-connected flag) is kept; a new `_require_user` gate is added in front.

### 3.2 New package `db/` (SQLAlchemy + Alembic)

```
db/
├── __init__.py     engine + scoped session factory; SQLite at instance/ruckus.db
│                   (URL from RUCKUS_DATABASE_URL, default sqlite:///<instance>/ruckus.db)
├── models.py       Tenant, User, Role(enum), AuditLog, Profile, NotificationConfig
└── migrations/     Alembic; create_all on first boot + versioned migrations
```

Models (illustrative):
```python
class Tenant:   id, name, created_at
class User:     id, tenant_id, email, display_name, password_hash|None, is_active,
                role (viewer|operator|admin), oidc_subject|None, created_at, last_login_at
class AuditLog: id, tenant_id, user_id, action, detail(json), ip, ts
class Profile:  id, tenant_id, name, plain_fields(json), enc_secret_fields(json)  # migrated from profiles.json
class NotificationConfig: tenant_id(pk), config(json)                            # migrated from notifications.json
```
Secrets inside `Profile`/`NotificationConfig` stay **Fernet-encrypted via the existing `SecretsManager`** — the DB stores ciphertext, never plaintext.

### 3.3 New auth modules

- `auth/users.py` — user store over `db`: `create_user`, `get_by_email`, `verify_password` (argon2 via `passlib`), `bootstrap_admin` (first-boot break-glass), JIT `upsert_oidc_user`.
- `auth/oidc.py` — Authlib OIDC client. `/login/oidc` → on-prem IdP → `/auth/callback` → validate, map claims (`sub`,`email`,`groups`) → `upsert_oidc_user` → session. Config via env (issuer, client id/secret, scopes, group→role map). Discovery doc fetched from the on-prem issuer (allow-listed).
- `auth/rbac.py` — `Role` order viewer<operator<admin; `@require_role(min_role)` decorator; `@require_user` decorator.
- `routes/auth.py` — `GET/POST /login` (local break-glass form), `GET /login/oidc` + `/auth/callback` (OIDC), `POST /logout` (app-user logout, distinct from controller `/logout`), `/admin/users` (admin CRUD).

### 3.4 Break-glass local admin
On first boot, if no users exist, seed one local `admin` user. Password from `RUCKUS_ADMIN_PASSWORD` (env) or a one-time random printed to the console/log (like the secret key). Local login (`/login`) always works even if the IdP is unreachable — essential air-gapped. Local accounts are limited to what an admin creates; OIDC is the normal path for everyone else.

### 3.5 RBAC
- **viewer** — read dashboards/tiles/reports.
- **operator** — viewer + manage *own* controller connections, profiles, notification config, send reports.
- **admin** — operator + manage users, tenants, SMTP/global config, view audit log.
Enforced by `@require_role` on blueprints/routes; composes *beneath* it with the existing controller-capability gate (RBAC = "may this user use this feature", capability gate = "does this controller expose this op").

### 3.6 Multi-tenancy
- `User.tenant_id` sets `g.tenant_id` each request. `Profile`, `NotificationConfig`, `AuditLog` (and, if PB4 is built, persisted connections) all carry `tenant_id`. Every query filters by `g.tenant_id`; a cross-tenant fetch returns 404/403. Single-tenant installs just have one `Tenant` row (transparent).
- Notification config becomes **per-tenant** (today it's one global `notifications.json`).

### 3.7 What stays in RAM (not persisted)
Live `ConnectionConfig` (controller `auth_token`) and the `CapabilityRegistry` stay process-local as today — restart drops live connections and users re-login to their controllers. This avoids persisting controller credentials at rest and keeps Layer-2 unchanged. (PB4 below is the optional exception.)

## 4. Build slices (each its own plan → TDD build → PR)

- **PB1 — Persistence + users + RBAC + local login + break-glass.** `db/` package (SQLite, SQLAlchemy, Alembic, `create_all` on boot), `User/Tenant/Role/AuditLog` models, `auth/users.py` (argon2), `auth/rbac.py`, `routes/auth.py` local login/logout + `_require_user`/`@require_role`, `before_request` user gate, admin user CRUD, audit log for logins. Wire the user gate in front of existing routes. **Foundation.**
- **PB2 — OIDC SSO.** `auth/oidc.py` (Authlib), `/login/oidc` + `/auth/callback`, claims→user JIT + group→role mapping, on-prem issuer config. Local break-glass retained.
- **PB3 — Multi-tenancy + migrate file state into the DB.** `Profile`/`NotificationConfig` tables; one-time import of `profiles.json`/`notifications.json`; `tenant_id` scoping on all of it; `ProfileStore`/`notify.config` read/write the DB (behind their current interfaces so callers barely change); per-tenant notification config; cross-tenant denial tests.
- **PB4 — (optional) Durable controller connections.** Persist encrypted `ConnectionConfig` to the DB so restart restores connections. Deferred unless wanted (security trade-off: controller tokens at rest).

## 5. Dependencies (new, all air-gap-installable wheels)
`sqlalchemy>=2`, `alembic`, `passlib[argon2]` (or `argon2-cffi`), `authlib` (PB2 only), added to `RUCKUS/pyproject.toml`. No services. All pure-Python/wheel — installable on an air-gapped box from a local wheelhouse.

## 6. Testing
**SQLite makes this testable in the existing CI — no service containers.** Each slice: temp-file or `sqlite:///:memory:` DB fixture. Tests: password hash/verify, RBAC matrix (viewer/operator/admin allowed/denied per route), `_require_user` gates unauthenticated → login redirect/401, break-glass admin bootstrap + login-when-IdP-down, OIDC callback with a **mock IdP** (monkeypatched Authlib token/userinfo) → JIT user + role from group, tenant isolation (user A cannot read tenant B's profile/config), migration import (profiles.json→DB), audit rows written. Keep the current 518 suite green. CI matrix unchanged (Ubuntu+Windows×3.10–3.12) — SQLite is stdlib.

## 7. Backward-compat & migration
- First boot with an existing `instance/`: `create_all`, seed default `Tenant` + break-glass admin, **import** `profiles.json`/`notifications.json` into the DB under the default tenant (idempotent; keep the JSON as a backup, stop writing it). Existing env config still read.
- `RUCKUS_ENABLE_NEW_UI` and all current flows unchanged; the app-user login is an added gate, not a rewrite of the controller flow.
- New env: `RUCKUS_DATABASE_URL` (default SQLite), `RUCKUS_ADMIN_PASSWORD` (break-glass seed), OIDC vars (PB2), `RUCKUS_AUTH_REQUIRED` (default on; a single-operator site can leave app-auth off to preserve today's behavior during rollout).

## 8. Security notes
- Passwords: argon2id hashes only, never plaintext. OIDC: validate `iss`/`aud`/nonce/state; issuer discovery URL goes through the SSRF allow-list.
- Session already `HttpOnly`+`Secure`+`SameSite=Strict`; add app-user session fixation reset on login (rotate on privilege change), mirroring the controller-connect `session.clear()` pattern.
- Audit every auth event + config/user change.
- DB file (`instance/ruckus.db`) chmod 0600 (parity with the other instance secrets).
- Break-glass admin: rate-limit local login; log every use.

## 9. Open questions
1. **Group→role mapping source** for OIDC — a config map (`RUCKUS_OIDC_GROUP_ROLES="admins:admin,noc:operator"`), or all OIDC users default to `viewer` and an admin promotes them? Proposal: config map + default viewer.
2. **`RUCKUS_AUTH_REQUIRED` default** — on (enforce app-login immediately) vs off (opt-in during rollout). Proposal: default on, documented off-switch for single-operator sites.
3. **Tenancy depth now** — build the `tenant_id` columns + scoping from PB1 (recommended, cheap later), or single-tenant now and add tenancy in PB3? Proposal: carry `tenant_id` from PB1, one default tenant.
4. **PB4 durable connections** — wanted, or leave controller re-login on restart? Proposal: defer (don't persist controller tokens).
