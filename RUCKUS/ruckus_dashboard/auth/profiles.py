"""Connection profiles — save/load/delete; passwords/secrets encrypted at rest.

PB3: DB-backed + tenant-scoped. Profiles now live in the ``profiles`` table
(migrated off ``instance/profiles.json``) rather than a JSON file. Every method
operates within a ``tenant_id`` so tenant A can never see, resolve, or delete
tenant B's rows. Secrets are still Fernet-encrypted via ``SecretsManager`` — the
DB stores ciphertext (``enc_secret_fields``), never plaintext.

The plain/secret field split and the ``_PROFILE_PW_SENTINEL`` (UI "unchanged"
marker) behaviour are preserved verbatim from the file-based implementation
(monolith lines 2565, 2698-2802); only the storage layer changed.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..db import session_scope
from ..db.models import Profile
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
    """Tenant-scoped, DB-backed store for controller-connection profiles.

    Constructed with the Flask ``app`` (for the scoped DB session) and the
    app's ``SecretsManager``. ``default_tenant_id`` is used when a caller does
    not pass an explicit ``tenant_id`` (single-tenant installs / startup work).
    """

    def __init__(
        self,
        app,
        secrets_manager: SecretsManager,
        default_tenant_id: int = 1,
    ) -> None:
        self._app = app
        self.secrets = secrets_manager
        self._default_tenant_id = default_tenant_id

    def _tid(self, tenant_id: int | None) -> int:
        return self._default_tenant_id if tenant_id is None else tenant_id

    def list_masked(self, tenant_id: int | None = None) -> list[dict[str, Any]]:
        tid = self._tid(tenant_id)
        with session_scope(self._app) as s:
            rows = (
                s.query(Profile)
                .filter(Profile.tenant_id == tid)
                .order_by(Profile.name)
                .all()
            )
            result = []
            for row in rows:
                plain = row.plain_fields or {}
                enc = row.enc_secret_fields or {}
                masked: dict[str, Any] = {"name": row.name}
                for field in PROFILE_PLAIN_FIELDS:
                    if field in plain:
                        masked[field] = plain[field]
                masked["has_secret"] = any(
                    enc.get(ef) for ef in PROFILE_SECRET_FIELDS.values()
                )
                masked["saved_at"] = (
                    row.saved_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                    if row.saved_at
                    else ""
                )
                result.append(masked)
        return result

    def save(
        self, name: str, form: dict[str, Any], tenant_id: int | None = None
    ) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Profile name is required.")
        tid = self._tid(tenant_id)

        plain: dict[str, Any] = {}
        for field in PROFILE_PLAIN_FIELDS:
            value = form.get(field)
            if value not in (None, ""):
                plain[field] = value
        enc: dict[str, Any] = {}
        for plain_field, enc_field in PROFILE_SECRET_FIELDS.items():
            secret = form.get(plain_field) or ""
            if secret and secret != _PROFILE_PW_SENTINEL:
                enc[enc_field] = self.secrets.encrypt(secret)

        with session_scope(self._app) as s:
            row = (
                s.query(Profile)
                .filter(Profile.tenant_id == tid, Profile.name == name)
                .one_or_none()
            )
            # Preserve an existing encrypted secret when the form left it
            # untouched (sentinel / blank), matching the file-based behaviour.
            existing_enc = dict(row.enc_secret_fields or {}) if row else {}
            for enc_field in PROFILE_SECRET_FIELDS.values():
                if enc_field not in enc and existing_enc.get(enc_field):
                    enc[enc_field] = existing_enc[enc_field]

            from ..db.models import _utcnow

            if row is None:
                s.add(
                    Profile(
                        tenant_id=tid,
                        name=name,
                        plain_fields=plain,
                        enc_secret_fields=enc,
                        saved_at=_utcnow(),
                    )
                )
            else:
                row.plain_fields = plain
                row.enc_secret_fields = enc
                row.saved_at = _utcnow()
                s.add(row)

    def delete(self, name: str, tenant_id: int | None = None) -> None:
        tid = self._tid(tenant_id)
        with session_scope(self._app) as s:
            row = (
                s.query(Profile)
                .filter(Profile.tenant_id == tid, Profile.name == name)
                .one_or_none()
            )
            if row is not None:
                s.delete(row)

    def resolve_secret(
        self, name: str, plain_field: str, tenant_id: int | None = None
    ) -> str:
        enc_field = PROFILE_SECRET_FIELDS.get(plain_field)
        if not enc_field:
            return ""
        tid = self._tid(tenant_id)
        with session_scope(self._app) as s:
            row = (
                s.query(Profile)
                .filter(Profile.tenant_id == tid, Profile.name == name)
                .one_or_none()
            )
            enc = (row.enc_secret_fields or {}).get(enc_field, "") if row else ""
        return self.secrets.decrypt(enc)

    def count(self, tenant_id: int | None = None) -> int:
        tid = self._tid(tenant_id)
        with session_scope(self._app) as s:
            return s.query(Profile).filter(Profile.tenant_id == tid).count()
