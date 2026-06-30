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
               "offline_threshold": 1},
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
    return out


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
