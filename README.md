# RUCKUS DSO Assurance Dashboard

A self-contained Flask dashboard for **RUCKUS SmartZone** (on-prem controller
public API) and **RUCKUS One** (cloud), built for a Digital Services Operations
(DSO) wall display.

Provide controller credentials once → the dashboard auto-discovers the
controller's API capabilities and warms up every applicable module so live
data appears without clicking.

## Features

- **18 live modules** across three domains:
  - **Wireless** — Overview, Zones, Access Points, WLANs, Wireless Clients,
    Alarms & Events, Rogues, Controller
  - **Switching** — Switches, Switch Groups, Ports, Traffic, PoE, Stack, VLANs
  - **Cross-cutting** — Firmware posture, Security (CISA KEV + NVD CVE), API Explorer
- **Auto-discovery + warmup** — after login, capability discovery runs and every
  module fetcher pre-populates its tile in parallel, streamed live to the browser
  via Server-Sent Events.
- **Per-column filtering** — every column on every tab gets a filter (select /
  search / numeric range), inferred from the column type, with server-side
  push-down where the controller query API supports it.
- **Outage alerting** — per-device online→offline detection across APs, switches,
  and the controller, with recovery ("back online") notifications, per-site
  grouping, debounce, and durable state that survives a restart; delivered over
  configurable SMTP (extensible channel interface). Configured in the UI.
- **Full-coverage reporting** — a daily/on-demand Excel report covering all 18
  modules (summary + column list + drill samples + raw field maps), plus an
  **"Email this tab"** button that mails the current tab honoring its active filters.
- **Topology views** — a logical hierarchy map with a NOC **health-glow wall**
  (severity-weighted glow, live status ribbon, problems-only filter) and a
  **traffic-flow** (Sankey) view toggle; zero-dependency SVG.
- **Wall-display polish** — CSS glow + a tiny same-origin motion layer (count-up
  KPIs, health-state glow, live refresh pulse); `prefers-reduced-motion` aware and
  CSP-safe (no third-party scripts).
- **Multi-user + SSO + RBAC** — app-user accounts with roles (viewer / operator /
  admin), **OIDC single sign-on** against an on-prem IdP plus a local break-glass
  admin, per-tenant isolation, and an audit log — a login layer in front of the
  controller connection. SQLite-backed, no extra services. Toggle with
  `RUCKUS_AUTH_REQUIRED` (single-operator sites can leave it off).
- **Read-only** — observes the controller, never writes config.
- **Two platforms** — SmartZone service-ticket auth + RUCKUS One OAuth2.
- **Security-first** — self-signed HTTPS out of the box; an SSRF allow-list that
  never follows HTTP redirects and refuses a non-loopback bind without an
  allow-list; per-connection capability isolation; CSRF protection; secrets
  encrypted at rest (Fernet, DPAPI-wrapped on Windows); no credentials written to
  disk in plaintext.
- **Single-command install** — `./scripts/install.sh` (Linux/macOS) or
  `.\scripts\install.ps1` (Windows).

## Quickstart

### Linux / macOS

```bash
git clone https://github.com/ssaksa80/RUCKUS-Dashboard.git
cd RUCKUS-Dashboard
./scripts/install.sh        # prompts for host/port, generates .env, launches
# Ctrl+C when satisfied, then:
./scripts/start.sh
```

### Windows

```powershell
git clone https://github.com/ssaksa80/RUCKUS-Dashboard.git
cd RUCKUS-Dashboard
.\scripts\install.ps1       # prompts for host/port, generates .env, launches
# Ctrl+C when satisfied, then:
.\scripts\start.ps1
```

Then open the printed URL (default `https://127.0.0.1:8444`). The cert is
self-signed — accept the browser warning. Log in with your SmartZone host +
username + password, or RUCKUS One tenant + client credentials.

## Manual run (no scripts)

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -e RUCKUS
python -m ruckus_dashboard --bind 127.0.0.1 --port 8444
```

Backward-compat: `python RUCKUS/ruckus_dashboard.py` also works.

## Configuration

All settings are environment variables (the installer writes them to
`RUCKUS/.env`, auto-loaded on launch):

| Variable | Default | Meaning |
|---|---|---|
| `RUCKUS_DASHBOARD_HOST` | `127.0.0.1` | Bind interface |
| `RUCKUS_DASHBOARD_PORT` | `8444` | HTTPS port (0 = OS-assigned) |
| `RUCKUS_ENABLE_NEW_UI` | `0` | `1` = new sidebar UI; `0` = legacy placeholder |
| `RUCKUS_ALLOWED_HOSTS` | _(empty)_ | SSRF allow-list (CSV of hosts/CIDRs). **Required** for a non-loopback bind — the server refuses to start on a non-loopback interface without it. |
| `RUCKUS_OPEN_BROWSER` | `1` | Auto-open browser on launch |
| `RUCKUS_VERIFY_TLS` | `true` | Verify SmartZone cert (`false` for self-signed controllers) |
| `RUCKUS_SECURITY_LOOKUPS` | `1` | Enable CISA KEV + NVD CVE matching |
| `RUCKUS_WARMUP_WORKERS` | `4` | Parallel module-fetch workers on login |
| `RUCKUS_WARMUP_TIMEOUT` | `30` | Per-module warmup timeout (seconds) |
| `RUCKUS_DPAPI_SCOPE` | `machine` | Windows secret-at-rest scope: `machine` (any local user can decrypt) or `user` (current account only) |
| `FLASK_SECRET_KEY` | _(auto)_ | Session signing key (installer generates one) |
| **App users / SSO (Phase B)** | | |
| `RUCKUS_AUTH_REQUIRED` | `1` | Require an app-user login. `0` = single-operator mode (controller login only, pre-Phase-B behavior). |
| `RUCKUS_ADMIN_PASSWORD` | _(auto)_ | First-boot break-glass admin password; if unset, a random one is logged **once** at startup. |
| `RUCKUS_DATABASE_URL` | `sqlite:///<instance>/ruckus.db` | App DB (users, tenants, profiles, notification config, audit). SQLAlchemy URL — swaps to Postgres if ever needed. |
| `RUCKUS_OIDC_ISSUER` | _(empty)_ | OIDC issuer base URL (on-prem IdP). SSO stays **off** unless issuer + client id + secret are all set. |
| `RUCKUS_OIDC_CLIENT_ID` / `RUCKUS_OIDC_CLIENT_SECRET` | _(empty)_ | OIDC client credentials. |
| `RUCKUS_OIDC_SCOPES` | `openid email profile` | OIDC scopes requested. |
| `RUCKUS_OIDC_GROUPS_CLAIM` | `groups` | ID-token/userinfo claim carrying the user's groups. |
| `RUCKUS_OIDC_GROUP_ROLES` | _(empty)_ | Group→role map, e.g. `admins:admin,noc:operator`. Unmapped users default to `viewer`. |

CLI flags override env: `--bind`, `--port`, `--smartzone-port`,
`--allowed-hosts`, `--no-browser`, `--no-auto-port`, `--server {werkzeug,waitress}`,
`--debug`, `--version`.

## Users & access (Phase B)

Access is **two layers**:

1. **App-user login** (who the operator is) — a local username/password or **OIDC
   SSO**, gated by `RUCKUS_AUTH_REQUIRED` (on by default).
2. **Controller connection** (which RUCKUS controller) — the existing SmartZone /
   RUCKUS One login, now owned by the logged-in user.

- **First boot** seeds a **break-glass local admin** (`admin`). Set
  `RUCKUS_ADMIN_PASSWORD` before first launch, or read the one-time random password
  logged at startup. The local login always works even if the IdP is unreachable —
  essential on an air-gapped box.
- **OIDC SSO** is opt-in: set `RUCKUS_OIDC_ISSUER` + client id/secret (an on-prem
  IdP such as Keycloak / AD FS). Users are provisioned on first sign-in; their role
  comes from `RUCKUS_OIDC_GROUP_ROLES` (default `viewer`).
- **Roles:** `viewer` (read dashboards) < `operator` (+ manage own connections /
  notifications / reports) < `admin` (+ users, global config, audit). Admins manage
  accounts at `/admin/users`.
- **Multi-tenant:** every profile, notification config, and audit row is scoped to a
  tenant; single-site installs just run one default tenant transparently.
- **Single-operator mode:** set `RUCKUS_AUTH_REQUIRED=0` to skip app-user login
  entirely and keep the pre-Phase-B behavior (controller login only).

## Architecture

Installable package `ruckus_dashboard/`:

```
ruckus_dashboard/
├── app.py / cli.py / config.py / certs.py / logging_setup.py
├── auth/        app users (argon2) + RBAC + OIDC SSO, session store, secrets (Fernet+DPAPI), profiles, CSRF, audit
├── db/          SQLAlchemy models (users/tenants/audit/profiles/notify config) + SQLite engine + first-boot migration
├── net/         SSRF allow-list, port scanner
├── clients/     smartzone, switchm, ruckus_one, capabilities (OpenAPI discovery)
├── infra/       cache, envelope, capability_gate/registry, inflight, warmup, parallel_fetch
├── modules/     one file per dashboard module (18 total)
├── security/    CISA KEV + NVD CVE validator
├── notify/      outage engine, durable state store, e-mail channels, scheduler
├── reports/     report model + generic collector, Excel renderer
├── routes/      pages, modules API, connect/logout, warmup SSE, notifications, topology layout, auth (login/SSO/admin users)
├── templates/   sidebar shell + per-module page + partials
└── static/      styles.css, dashboard.js, motion.js, topology.js, logo
```

Each module is a single file declaring a `ModuleSpec`: fetcher, summary,
drill-in, filters, normalization, multi-controller merge, required capabilities.
Adding a module = one file + one import line.

## Testing

```bash
pip install -e RUCKUS[test]
pytest -q
```

CI runs the suite on Ubuntu + Windows × Python 3.10/3.11/3.12 (see
`.github/workflows/ci.yml`).

## Deployment

See [docs/DEPLOY.md](docs/DEPLOY.md) for production deployment: systemd unit,
Windows service (NSSM), nginx reverse proxy with a real certificate, firewall,
upgrades, and backup.

## Security notes

- Bind to `127.0.0.1` unless fronted by a reverse proxy. For a non-loopback
  bind you **must** set `RUCKUS_ALLOWED_HOSTS`; the server now **refuses to start**
  on a non-loopback interface without one (fail-closed, prevents use as an open
  SSRF proxy to internal hosts).
- Upstream requests never follow HTTP redirects, so a controller response cannot
  redirect the allow-list check to an unchecked host.
- Controller capabilities are isolated **per connection** — one operator's session
  cannot see or clear another's capability gating.
- On Windows, secrets at rest are DPAPI-wrapped; set `RUCKUS_DPAPI_SCOPE=user` to
  scope them to the current account instead of the whole machine.
- **App-user auth (Phase B):** passwords are argon2id-hashed (never stored
  plaintext); login rate-limited + audited; OIDC tokens validated by the IdP (no
  hand-rolled JWT) and never linked to an existing account by an unverified email
  claim. Keep `RUCKUS_ADMIN_PASSWORD` secret and change the seeded admin password.
- `RUCKUS/instance/` holds the generated cert, session key, encrypted
  profile/notification blobs, and the app DB (`ruckus.db` — users/tenants/config/
  audit, secrets encrypted within it). Back it up, never commit it (already in
  `.gitignore`).
- Read-only by design: no controller configuration is ever modified.

## License

Internal use.
