#!/usr/bin/env bash
# RUCKUS DSO Dashboard — launcher (Linux / macOS).
# Sources RUCKUS/.env, activates the venv, runs the dashboard in the foreground.
# Daemonize with systemd / nohup / tmux as you prefer (see docs/DEPLOY.md).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -f "RUCKUS/.env" ] || [ ! -d ".venv" ]; then
  echo "ERROR: not installed. Run ./scripts/install.sh first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source RUCKUS/.env
set +a

# shellcheck disable=SC1091
source .venv/bin/activate
exec python -m ruckus_dashboard --no-browser
