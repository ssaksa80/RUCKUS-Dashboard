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
- **Read-only** — observes the controller, never writes config.
- **Two platforms** — SmartZone service-ticket auth + RUCKUS One OAuth2.
- **Security-first** — self-signed HTTPS out of the box, SSRF allow-list,
  CSRF protection, secrets encrypted at rest (Fernet, DPAPI-wrapped on Windows),
  no credentials written to disk in plaintext.
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
| `RUCKUS_ALLOWED_HOSTS` | _(empty)_ | SSRF allow-list (CSV of hosts/CIDRs). **Required** for non-loopback bind. |
| `RUCKUS_OPEN_BROWSER` | `1` | Auto-open browser on launch |
| `RUCKUS_VERIFY_TLS` | `true` | Verify SmartZone cert (`false` for self-signed controllers) |
| `RUCKUS_SECURITY_LOOKUPS` | `1` | Enable CISA KEV + NVD CVE matching |
| `RUCKUS_WARMUP_WORKERS` | `4` | Parallel module-fetch workers on login |
| `RUCKUS_WARMUP_TIMEOUT` | `30` | Per-module warmup timeout (seconds) |
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
├── infra/       cache, envelope, capability_gate, inflight, warmup, parallel_fetch
├── modules/     one file per dashboard module (18 total)
├── security/    CISA KEV + NVD CVE validator
├── routes/      pages, modules API, connect/logout, warmup SSE
├── templates/   sidebar shell + per-module page + partials
└── static/      styles.css, dashboard.js, logo
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
  bind you **must** set `RUCKUS_ALLOWED_HOSTS` (prevents the server being used
  to reach arbitrary internal hosts).
- `RUCKUS/instance/` holds the generated cert, session key, and encrypted
  profile blobs — back it up, never commit it (already in `.gitignore`).
- Read-only by design: no controller configuration is ever modified.

## License

Internal use.
