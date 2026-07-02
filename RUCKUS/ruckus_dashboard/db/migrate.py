"""One-time import of file-based state into the DB (PB3).

On boot, if ``instance/profiles.json`` / ``instance/notifications.json`` exist
AND the corresponding DB table is empty for the default tenant, their contents
are imported under the default tenant. Idempotent: once rows exist we never
re-import, so a second boot cannot duplicate. The JSON files are kept on disk as
backups; runtime writes go to the DB from now on (the file-writing code paths
are no longer invoked at runtime).

Encrypted secret fields carry over verbatim — they are already Fernet
ciphertext, so no re-encryption (and no plaintext) is involved.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from . import session_scope
from .models import NotificationConfig, Profile
from ..auth.profiles import PROFILE_PLAIN_FIELDS, PROFILE_SECRET_FIELDS

LOG = logging.getLogger("ruckus_dashboard.db.migrate")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        LOG.warning("could not read %s for migration", path, exc_info=True)
        return None


def import_profiles(app, tenant_id: int) -> int:
    """Import ``profiles.json`` into the ``profiles`` table for ``tenant_id``.

    No-op if the file is missing or the tenant already has any profile rows
    (idempotent). Returns the number of profiles imported.
    """
    path = Path(app.instance_path) / "profiles.json"
    data = _read_json(path)
    if not data:
        return 0

    from .models import _utcnow

    with session_scope(app) as s:
        existing = (
            s.query(Profile).filter(Profile.tenant_id == tenant_id).count()
        )
        if existing:
            return 0  # already migrated — never duplicate
        count = 0
        for name, prof in data.items():
            if not isinstance(prof, dict):
                continue
            plain = {f: prof[f] for f in PROFILE_PLAIN_FIELDS if f in prof}
            enc = {
                ef: prof[ef]
                for ef in PROFILE_SECRET_FIELDS.values()
                if prof.get(ef)
            }
            s.add(
                Profile(
                    tenant_id=tenant_id,
                    name=name,
                    plain_fields=plain,
                    enc_secret_fields=enc,
                    saved_at=_utcnow(),
                )
            )
            count += 1
    if count:
        LOG.info("migrated %d profile(s) from profiles.json into the DB", count)
    return count


def import_notification_config(app, tenant_id: int) -> bool:
    """Import ``notifications.json`` into ``notification_config`` for ``tenant_id``.

    No-op if the file is missing or a config row already exists for the tenant
    (idempotent). The stored blob is merged through the config defaults so the
    imported shape matches a freshly-saved config. Returns True if imported.
    """
    path = Path(app.instance_path) / "notifications.json"
    data = _read_json(path)
    if data is None:
        return False

    from ..notify.config import _merged

    with session_scope(app) as s:
        existing = (
            s.query(NotificationConfig)
            .filter(NotificationConfig.tenant_id == tenant_id)
            .one_or_none()
        )
        if existing is not None:
            return False  # already migrated — never overwrite
        s.add(NotificationConfig(tenant_id=tenant_id, config=_merged(data)))
    LOG.info("migrated notifications.json into the DB for tenant %s", tenant_id)
    return True


def import_file_state(app, tenant_id: int) -> None:
    """Run all one-time file→DB imports for the default tenant. Best-effort."""
    try:
        import_profiles(app, tenant_id)
    except Exception:  # noqa: BLE001 - a migration hiccup must not block boot
        LOG.warning("profile migration failed", exc_info=True)
    try:
        import_notification_config(app, tenant_id)
    except Exception:  # noqa: BLE001
        LOG.warning("notification-config migration failed", exc_info=True)
