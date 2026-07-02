"""Notification configuration persisted in the app instance folder.

The SMTP password is Fernet-encrypted at rest via the app's SecretsManager
and masked on read-for-display; posting the mask back preserves the stored
secret."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PASSWORD_MASK = "********"

DEFAULTS: dict[str, Any] = {
    "smtp": {"host": "", "port": 587, "security": "starttls", "username": "",
             "password_enc": "", "from_addr": ""},
    "alerts": {"enabled": False, "recipients": [], "check_seconds": 300,
               "rules": {"ap_offline": True, "switch_offline": True,
                         "critical_alarm": True, "poor_client_ap": True},
               "offline_threshold": 1,
               # SP2 additions (additive, backward-compatible):
               "recovery": True,
               "debounce_seconds": 120,
               "group_by": "site",
               "suppress_known_on_start": True,
               "channels": {"email": {"enabled": True, "recipients": []}}},
    "report": {"enabled": False, "recipients": [], "time": "07:00"},
}


def _path(instance_path: str) -> Path:
    return Path(instance_path) / "notifications.json"


def _merged(stored: dict) -> dict:
    out = json.loads(json.dumps(DEFAULTS))  # deep copy
    for section in out:
        if isinstance(stored.get(section), dict):
            out[section].update(stored[section])
    if isinstance(stored.get("alerts", {}).get("rules"), dict):
        out["alerts"]["rules"] = {**DEFAULTS["alerts"]["rules"],
                                  **stored["alerts"]["rules"]}
    if isinstance(stored.get("alerts", {}).get("channels"), dict):
        out["alerts"]["channels"] = {
            **DEFAULTS["alerts"]["channels"],
            **stored["alerts"]["channels"],
        }
    # Backward-compat: if channels absent but recipients exist, propagate.
    if not stored.get("alerts", {}).get("channels"):
        legacy = (stored.get("alerts") or {}).get("recipients") or []
        if legacy:
            out["alerts"]["channels"]["email"]["recipients"] = legacy
    return out


def _merge_incoming(current: dict, incoming: dict, secrets) -> dict:
    """Deep-merge a display-shaped ``incoming`` config onto ``current``.

    Section dicts are shallow-updated then run through :func:`_merged` (so
    DEFAULTS/rules/channels behaviour is uniform). The SMTP password is
    encrypted; the mask (or a blank/absent password) keeps the previously
    stored secret. Returns the merged config (plaintext ``password`` stripped).

    Storage-agnostic: shared by the file-based ``save_config`` and the
    DB-backed :class:`NotificationConfigStore` so both behave identically.
    """
    sections = {}
    for k, v in current.items():
        sections[k] = dict(v) if isinstance(v, dict) else v
    for k, v in incoming.items():
        if isinstance(v, dict) and isinstance(sections.get(k), dict):
            sections[k].update(v)
        elif isinstance(v, dict):
            sections[k] = dict(v)
    merged = _merged(sections)
    pw = (incoming.get("smtp") or {}).get("password")
    if pw and pw != PASSWORD_MASK:
        merged["smtp"]["password_enc"] = secrets.encrypt(pw)
    else:
        merged["smtp"]["password_enc"] = current["smtp"].get("password_enc", "")
    merged["smtp"].pop("password", None)
    return merged


def load_config(instance_path: str) -> dict:
    try:
        stored = json.loads(_path(instance_path).read_text(encoding="utf-8"))
        if not isinstance(stored, dict):
            stored = {}
    except (OSError, ValueError):
        stored = {}
    return _merged(stored)


def save_config(instance_path: str, incoming: dict, secrets) -> dict:
    """Merge an incoming (display-shaped) config and persist it.

    ``incoming["smtp"]["password"]`` (plaintext) is encrypted; the mask keeps
    the previously stored secret."""
    current = load_config(instance_path)
    merged = _merge_incoming(current, incoming, secrets)
    path = _path(instance_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=1), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return merged


def display_config(cfg: dict) -> dict:
    """Shape for the UI: password masked (or empty when unset)."""
    out = json.loads(json.dumps(cfg))
    has_pw = bool(out["smtp"].pop("password_enc", ""))
    out["smtp"]["password"] = PASSWORD_MASK if has_pw else ""
    return out


def smtp_password(cfg: dict, secrets) -> str:
    enc = cfg.get("smtp", {}).get("password_enc", "")
    if not enc:
        return ""
    try:
        return secrets.decrypt(enc)
    except Exception:  # noqa: BLE001 — key rotated/corrupt → treat as unset
        return ""


class NotificationConfigStore:
    """DB-backed, per-tenant notification config (PB3).

    Persists one JSON blob per tenant in the ``notification_config`` table
    instead of ``instance/notifications.json``. The config *shape* and all
    SP2/SP7 behaviour (DEFAULTS, deep section-merge, password masking /
    ``password_enc``, channels, outage defaults) are identical to the file
    functions — this class only swaps the storage layer, reusing the same pure
    helpers (:func:`_merged`, :func:`_merge_incoming`).

    ``load_config`` / ``save_config`` / ``display_config`` / ``smtp_password``
    take a ``tenant_id`` (the default tenant when unspecified) so a request can
    pass ``g.tenant_id`` and the scheduler can pass its active connection's
    tenant.
    """

    def __init__(self, app, default_tenant_id: int = 1) -> None:
        self._app = app
        self._default_tenant_id = default_tenant_id

    def _tid(self, tenant_id: int | None) -> int:
        return self._default_tenant_id if tenant_id is None else tenant_id

    def _stored(self, tenant_id: int) -> dict:
        """Raw stored blob for a tenant ({} when no row yet)."""
        from ..db import session_scope
        from ..db.models import NotificationConfig

        with session_scope(self._app) as s:
            row = (
                s.query(NotificationConfig)
                .filter(NotificationConfig.tenant_id == tenant_id)
                .one_or_none()
            )
            return dict(row.config) if row and isinstance(row.config, dict) else {}

    def load_config(self, tenant_id: int | None = None) -> dict:
        """Return the merged config for a tenant (DEFAULTS when no row)."""
        return _merged(self._stored(self._tid(tenant_id)))

    def save_config(
        self, incoming: dict, secrets, tenant_id: int | None = None
    ) -> dict:
        """Merge a display-shaped ``incoming`` config and persist it per tenant.

        Same semantics as the file-based ``save_config``: password encrypted,
        mask preserves the stored secret, sections deep-merged onto current.
        """
        from ..db import session_scope
        from ..db.models import NotificationConfig

        tid = self._tid(tenant_id)
        current = _merged(self._stored(tid))
        merged = _merge_incoming(current, incoming, secrets)
        with session_scope(self._app) as s:
            row = (
                s.query(NotificationConfig)
                .filter(NotificationConfig.tenant_id == tid)
                .one_or_none()
            )
            if row is None:
                s.add(NotificationConfig(tenant_id=tid, config=merged))
            else:
                row.config = merged
                s.add(row)
        return merged

    @staticmethod
    def display_config(cfg: dict) -> dict:
        return display_config(cfg)

    @staticmethod
    def smtp_password(cfg: dict, secrets) -> str:
        return smtp_password(cfg, secrets)
