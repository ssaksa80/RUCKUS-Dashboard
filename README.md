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

CLI flags override env: `--bind`, `--port`, `--smartzone-port`,
`--allowed-hosts`, `--no-browser`, `--no-auto-port`, `--debug`, `--version`.

## Architecture

Installable package `ruckus_dashboard/`:

```
ruckus_dashboard/
├── app.py / cli.py / config.py / certs.py / logging_setup.py
├── auth/        session store, secrets (Fernet+DPAPI), profiles, CSRF
├── net/         SSRF allow-list, port scanner
├── clients/     smartzone, switchm, ruckus_one, capabilities (OpenAPI discovery)
├── infra/       cache, envelope, capability_gate/registry, inflight, warmup, parallel_fetch
├── modules/     one file per dashboard module (18 total)
├── security/    CISA KEV + NVD CVE validator
├── notify/      outage engine, durable state store, e-mail channels, scheduler
├── reports/     report model + generic collector, Excel renderer
├── routes/      pages, modules API, connect/logout, warmup SSE, notifications, topology layout
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
- `RUCKUS/instance/` holds the generated cert, session key, and encrypted
  profile/notification blobs — back it up, never commit it (already in `.gitignore`).
- Read-only by design: no controller configuration is ever modified.

## License

Internal use.
