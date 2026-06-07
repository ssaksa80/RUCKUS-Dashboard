# Plan 2d — Cross-cutting Modules + Single-command Bootstrap

> Executed via subagent-driven-development. All tasks complete.

**Goal:** Promote the final 3 modules (firmware, security, api-explorer) from stub to real, and ship one-command install + start scripts for both Unix and Windows plus production deployment docs.

**Spec:** `docs/superpowers/specs/2026-06-06-ruckus-dashboard-plan2-design.md`

## Tasks (all complete)

1. **firmware module** — per-zone AP firmware catalog via `GET /rkszones` + `/rkszones/{id}/apFirmware`. Summary: supported/unsupported version counts. `RUCKUS/ruckus_dashboard/modules/firmware.py`.
2. **security module** — ported CISA KEV + NVD CVE validator into `RUCKUS/ruckus_dashboard/security/validator.py`; module validates AP inventory. Honors `RUCKUS_SECURITY_LOOKUPS=false` to skip network. `modules/security.py`.
3. **api-explorer module** — searchable browser over `available_ops` (discovered OpenAPI). Filter by source/method/search. `warmup=False`. `modules/api_explorer.py`.
4. **drop final stubs** — `_registry.py` `_DEFS` emptied; all 18 modules self-register from their own files.
5. **scripts/install.sh** — Unix installer: venv + deps + interactive `.env` + foreground verify. Non-interactive mode via `RUCKUS_INSTALL_*`.
6. **scripts/start.sh** — Unix launcher.
7. **scripts/install.ps1 + start.ps1** — Windows equivalents with ACL-restricted `.env`.
8. **README.md + docs/DEPLOY.md** — quickstart + production deployment (systemd, NSSM, nginx SSE-aware proxy, firewall, upgrade, backup).

## Outcome

- All 18 modules real (8 wireless + 7 switching + 3 cross-cutting).
- `git clone && ./scripts/install.sh` → dashboard live.
- 195 tests passing. install.ps1 verified non-interactive on Windows.

## Acceptance criteria — met

- [x] firmware, security, api-explorer have real fetchers
- [x] No stubs remain in registry (`_DEFS = []`)
- [x] install.sh / install.ps1 create venv, deps, .env, launch
- [x] start.sh / start.ps1 launch from saved config
- [x] Non-interactive install mode for CI
- [x] README + DEPLOY docs
- [x] Full suite green
