# Deployment Guide — RUCKUS DSO Dashboard

Production deployment for another server. Covers Linux (systemd), Windows
(NSSM), reverse proxy, firewall, upgrades, and backup.

## 1. Prerequisites

| Need | Detail |
|---|---|
| OS | Linux (Ubuntu 22.04+ / RHEL 9+) or Windows Server 2019+ |
| Python | 3.10 / 3.11 / 3.12 / 3.13 |
| Outbound | HTTPS to SmartZone (TCP 8443) and/or RUCKUS One cloud (TCP 443) |
| Inbound | TCP 8444 (or your chosen `--port`) from operator browsers |
| Disk | ~50 MB code + deps |
| Account | non-root service user (e.g. `ruckus`) |

## 2. Copy the code

```bash
git clone https://github.com/ssaksa80/RUCKUS-Dashboard.git /opt/ruckus-dashboard
cd /opt/ruckus-dashboard
```

Air-gapped? Tar it on a connected machine and copy:

```bash
tar --exclude='.git' --exclude='.venv' --exclude='RUCKUS/instance' \
    --exclude='__pycache__' --exclude='.pytest_cache' \
    -czf ruckus-dashboard.tar.gz .
```

## 3. Install

```bash
./scripts/install.sh
```

Or non-interactively (CI / unattended):

```bash
RUCKUS_INSTALL_NONINTERACTIVE=1 \
RUCKUS_INSTALL_HOST=127.0.0.1 \
RUCKUS_INSTALL_PORT=8444 \
RUCKUS_INSTALL_NEWUI=y \
RUCKUS_INSTALL_BROWSER=n \
./scripts/install.sh
```

First launch auto-generates `RUCKUS/instance/{cert.pem,key.pem,secret_key}`.

## 3.1 First-boot admin & app-user auth (Phase B)

App-user login is **on by default** (`RUCKUS_AUTH_REQUIRED=1`). Set the break-glass
admin password before first launch (otherwise a random one is logged **once** to the
log/stderr — capture it):

```bash
# RUCKUS/.env
RUCKUS_ADMIN_PASSWORD=change-me-strong
```

First boot creates `RUCKUS/instance/ruckus.db` (SQLite) with a default tenant + the
local `admin`. Browse to `/login`, sign in as `admin`, then connect to your
controller. Manage accounts at `/admin/users`.

**OIDC SSO (optional; on-prem IdP such as Keycloak / AD FS):**

```bash
# RUCKUS/.env
RUCKUS_OIDC_ISSUER=https://idp.internal/realms/ruckus
RUCKUS_OIDC_CLIENT_ID=ruckus-dashboard
RUCKUS_OIDC_CLIENT_SECRET=...
RUCKUS_OIDC_GROUP_ROLES=ruckus-admins:admin,noc:operator   # unmapped => viewer
```

Register the redirect URI `https://<host>/auth/callback` at the IdP. SSO stays
**disabled** until issuer + client id + secret are all set; the local break-glass
login always remains available (vital if the IdP is unreachable on an air-gapped
network). Set `RUCKUS_AUTH_REQUIRED=0` for single-operator mode (controller login
only, pre-Phase-B behavior).

## 4. Production certificate (recommended)

Replace the self-signed cert with a CA-signed one:

```bash
cp your.crt RUCKUS/instance/cert.pem
cp your.key RUCKUS/instance/key.pem
chmod 600 RUCKUS/instance/key.pem
```

Or point at external paths via env in `RUCKUS/.env`:

```
RUCKUS_CERT_FILE=/etc/ssl/certs/ruckus.crt
RUCKUS_KEY_FILE=/etc/ssl/private/ruckus.key
```

## 5a. Linux service (systemd)

`/etc/systemd/system/ruckus-dashboard.service`:

```ini
[Unit]
Description=RUCKUS DSO Dashboard
After=network.target

[Service]
Type=simple
User=ruckus
Group=ruckus
WorkingDirectory=/opt/ruckus-dashboard
EnvironmentFile=/opt/ruckus-dashboard/RUCKUS/.env
ExecStart=/opt/ruckus-dashboard/.venv/bin/python -m ruckus_dashboard --no-browser
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

# Hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/ruckus-dashboard/RUCKUS/instance
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

```bash
useradd -r -s /sbin/nologin -d /opt/ruckus-dashboard ruckus
chown -R ruckus:ruckus /opt/ruckus-dashboard
systemctl daemon-reload
systemctl enable --now ruckus-dashboard
systemctl status ruckus-dashboard
journalctl -u ruckus-dashboard -f
```

## 5b. Windows service (NSSM)

```powershell
nssm install RuckusDashboard `
  "C:\opt\ruckus-dashboard\.venv\Scripts\python.exe" `
  "-m" "ruckus_dashboard" "--no-browser"
nssm set RuckusDashboard AppDirectory "C:\opt\ruckus-dashboard"
nssm set RuckusDashboard AppEnvironmentExtra `
  "RUCKUS_DASHBOARD_HOST=0.0.0.0" `
  "RUCKUS_DASHBOARD_PORT=8444" `
  "RUCKUS_ENABLE_NEW_UI=1" `
  "RUCKUS_ALLOWED_HOSTS=sz1.example.com"
nssm start RuckusDashboard
```

(Env vars can also live in `RUCKUS\.env` — NSSM picks up the launcher's dotenv load.)

## 6. Reverse proxy (nginx, optional)

Front the dashboard with nginx for a real cert on port 443. Bind the dashboard
to loopback:

`RUCKUS/.env`:
```
RUCKUS_DASHBOARD_HOST=127.0.0.1
RUCKUS_DASHBOARD_PORT=8444
```

nginx:
```nginx
server {
  listen 443 ssl http2;
  server_name dso.example.com;
  ssl_certificate     /etc/letsencrypt/live/dso.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/dso.example.com/privkey.pem;

  location / {
    proxy_pass https://127.0.0.1:8444;
    proxy_ssl_verify off;              # upstream is self-signed
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto https;

    # Server-Sent Events (warmup stream) needs buffering off + long read
    proxy_buffering off;
    proxy_read_timeout 3600s;
    proxy_set_header Connection "";
  }
}
```

The `proxy_buffering off` line is important — without it the warmup SSE
progress stream is held back by nginx. The dashboard already sends
`X-Accel-Buffering: no`, which nginx honors, but setting it explicitly is safe.

### 6.1 Production WSGI server (waitress, plain HTTP to nginx)

The default above proxies to Werkzeug's self-signed HTTPS listener. For a
production reverse-proxy deployment you can instead run the app on the
`waitress` WSGI server, which serves **plain HTTP** and lets nginx terminate
TLS (no self-signed cert, no `proxy_ssl_verify off`):

```bash
pip install -e 'RUCKUS[server]'        # installs waitress
```

Launch with `--server waitress` (or set `RUCKUS_WSGI_SERVER=waitress`; the
flag wins). It binds plain HTTP — keep it on loopback:

```bash
ruckus-dashboard --server waitress --bind 127.0.0.1 --port 8444 --no-browser
```

Then change only the upstream scheme in the nginx `location /` block above —
`http`, and drop the self-signed line:

```nginx
    proxy_pass http://127.0.0.1:8444;
    # proxy_ssl_verify off;   # not needed — upstream is plain HTTP
```

Notes:
- **Single process.** waitress runs one process with a thread pool
  (`RUCKUS_WSGI_THREADS`, default 4). Do **not** run multiple workers/processes:
  the connection store and capability registry are in-RAM and process-local, so
  a second worker would not see the first's session — operators would appear
  logged out at random. Scale with threads, not processes.
- **TLS is nginx's job.** waitress has no TLS; never expose its HTTP port
  directly. The startup banner prints the `http://…` URL as a reminder.
- The default `--server werkzeug` (self-signed HTTPS) is unchanged and remains
  the standalone-appliance path.

## 7. Firewall

```bash
# ufw
ufw allow 8444/tcp
# firewalld
firewall-cmd --permanent --add-port=8444/tcp && firewall-cmd --reload
```

```powershell
New-NetFirewallRule -DisplayName "RUCKUS Dashboard" -Direction Inbound `
  -Protocol TCP -LocalPort 8444 -Action Allow
```

## 8. Verify

```bash
curl -k https://<server>:8444/healthz
# {"ok":true,"app":"RUCKUS NOC Assurance Dashboard","version":"..."}

curl -k https://<server>:8444/api/modules | python -c 'import sys,json; print(len(json.load(sys.stdin)["modules"]))'
# 18
```

## 9. Upgrade

```bash
cd /opt/ruckus-dashboard
sudo systemctl stop ruckus-dashboard
sudo -u ruckus git pull
sudo -u ruckus .venv/bin/pip install -e RUCKUS
sudo systemctl start ruckus-dashboard
```

`RUCKUS/instance/` (cert, key, secret, profiles) survives the upgrade.

## 10. Backup

Back up these (everything else is reproducible from git):

```
RUCKUS/.env                       # config + FLASK_SECRET_KEY
RUCKUS/instance/cert.pem
RUCKUS/instance/key.pem
RUCKUS/instance/secret_key        # session signing
RUCKUS/instance/*fernet*          # profile/DB-secret encryption key
RUCKUS/instance/ruckus.db         # app users, tenants, profiles, notification config, audit (Phase B)
RUCKUS/instance/profiles.json     # legacy profiles (pre-Phase-B; now imported into ruckus.db, kept as backup)
```

- Lose `secret_key` → existing browser sessions invalidate (operators re-login).
- Lose the Fernet key → saved profile / SMTP passwords in `ruckus.db` become unreadable.
- Lose `ruckus.db` → all app users, tenants, and config are gone; a fresh boot
  re-seeds the break-glass `admin` (from `RUCKUS_ADMIN_PASSWORD` or a logged random).
- Cert + key regenerate automatically if missing (self-signed).

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: ruckus_dashboard` | `pip install -e RUCKUS` from repo root |
| All modules show `—` (disabled) | Capability discovery found the controller doesn't expose those ops; check controller version / API permissions |
| Tiles stuck on skeleton `…` | SSE blocked by proxy — set `proxy_buffering off` (section 6) |
| 401 on every `/api/modules/*` | Session expired or not logged in — reconnect |
| Port busy | `--port 0` (OS-assigned) or pick another port |
| "non-loopback bind without allow-list" warning | Set `RUCKUS_ALLOWED_HOSTS` |
| Cert warning won't clear | Replace `RUCKUS/instance/cert.pem` with a CA-signed cert (section 4) |
