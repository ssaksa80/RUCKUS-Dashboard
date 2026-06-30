"""Connection profiles — save/load/delete; passwords/secrets encrypted at rest.

Ported verbatim from RUCKUS/ruckus_dashboard.py lines 2715-2802 (ProfileStore)
along with the supporting constants ``PROFILE_PLAIN_FIELDS``,
``PROFILE_SECRET_FIELDS`` (monolith lines 2698-2712), and ``_PROFILE_PW_SENTINEL``
(monolith line 2565).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from .secrets import SecretsManager


LOG = logging.getLogger("ruckus_dashboard")

# Sentinel sent by the UI when the password field was left unchanged.
_PROFILE_PW_SENTINEL = "__profile_password__"

PROFILE_PLAIN_FIELDS = (
    "platform",
    "smartzone_host",
    "smartzone_username",
    "smartzone_api_version",
    "smartzone_skip_tls_verify",
    "tenant_id",
    "client_id",
    "ruckus_one_region",
    "ruckus_one_custom_host",
)
PROFILE_SECRET_FIELDS = {
    "smartzone_password": "_enc_smartzone_password",
    "client_secret": "_enc_client_secret",
}


def _format_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


class ProfileStore:
    def __init__(self, instance_path: str, secrets_manager: SecretsManager) -> None:
        self.path = Path(instance_path) / "profiles.json"
        self.secrets = secrets_manager
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def _write(self, profiles: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            data = json.dumps(profiles, separators=(",", ":"))
            _binary = getattr(os, "O_BINARY", 0)  # Windows: prevent \n→\r\n translation
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _binary, 0o600)
            try:
                os.write(fd, data.encode("utf-8"))
            finally:
                os.close(fd)
            tmp.replace(self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        except OSError as exc:
            LOG.warning(f"Could not persist profiles: {exc}")

    def list_masked(self) -> list[dict[str, Any]]:
        with self._lock:
            profiles = self._load()
        result = []
        for name, prof in sorted(profiles.items()):
            masked = {"name": name}
            for field in PROFILE_PLAIN_FIELDS:
                if field in prof:
                    masked[field] = prof[field]
            masked["has_secret"] = any(prof.get(enc) for enc in PROFILE_SECRET_FIELDS.values())
            masked["saved_at"] = prof.get("saved_at", "")
            result.append(masked)
        return result

    def save(self, name: str, form: dict[str, Any]) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Profile name is required.")
        record: dict[str, Any] = {"saved_at": _format_now()}
        for field in PROFILE_PLAIN_FIELDS:
            value = form.get(field)
            if value not in (None, ""):
                record[field] = value
        for plain_field, enc_field in PROFILE_SECRET_FIELDS.items():
            secret = form.get(plain_field) or ""
            if secret and secret != _PROFILE_PW_SENTINEL:
                record[enc_field] = self.secrets.encrypt(secret)
        with self._lock:
            profiles = self._load()
            # Preserve an existing encrypted secret when the form left it untouched.
            existing = profiles.get(name, {})
            for enc_field in PROFILE_SECRET_FIELDS.values():
                if enc_field not in record and existing.get(enc_field):
                    record[enc_field] = existing[enc_field]
            profiles[name] = record
            self._write(profiles)

    def delete(self, name: str) -> None:
        with self._lock:
            profiles = self._load()
            if profiles.pop(name, None) is not None:
                self._write(profiles)

    def resolve_secret(self, name: str, plain_field: str) -> str:
        enc_field = PROFILE_SECRET_FIELDS.get(plain_field)
        if not enc_field:
            return ""
        with self._lock:
            prof = self._load().get(name, {})
        return self.secrets.decrypt(prof.get(enc_field, ""))

    def count(self) -> int:
        with self._lock:
            return len(self._load())
