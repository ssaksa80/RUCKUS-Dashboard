"""SQLAlchemy 2.x ORM models for the Phase B identity/RBAC/audit layer.

Single-node, SQLite-backed. Every user-scoped row carries ``tenant_id`` so
multi-tenancy (PB3) is a cheap later addition; single-tenant installs simply
have one ``Tenant`` row. Controller credentials are **never** persisted here
(they stay process-local in the connection store) — this schema holds only
*app users*, tenants, and the audit trail.
"""
from __future__ import annotations

import datetime as dt
from enum import IntEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class Role(IntEnum):
    """RBAC roles, ordered ``viewer < operator < admin``.

    Stored in ``User.role`` as the enum *name* (a short string) for readability
    in the DB, but compared as ints via this IntEnum so ``require_role`` can do a
    single ``>=`` check. Use :meth:`coerce` to turn a name/enum into a member.
    """

    viewer = 1
    operator = 2
    admin = 3

    @classmethod
    def coerce(cls, value: "Role | str") -> "Role":
        """Return the ``Role`` for a name (``"admin"``) or an existing member.

        Raises ``KeyError`` for an unknown name and ``ValueError`` for an
        unsupported type — callers treat either as "invalid role".
        """
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls[value]
        raise ValueError(f"cannot coerce {value!r} to Role")


def _utcnow() -> dt.datetime:
    # Timezone-aware UTC; stored naive by SQLite but consistent across the app.
    return dt.datetime.now(dt.timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )

    users: Mapped[list["User"]] = relationship(back_populates="tenant")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Tenant {self.id} {self.name!r}>"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # None for OIDC-only accounts (PB2); local/break-glass users have an argon2id
    # hash. Plaintext is NEVER stored.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Stored as the Role *name* ("viewer"/"operator"/"admin").
    role: Mapped[str] = mapped_column(
        String(16), default=Role.viewer.name, nullable=False
    )
    oidc_subject: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    last_login_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="users")

    @property
    def role_enum(self) -> Role:
        return Role.coerce(self.role)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<User {self.id} {self.email!r} role={self.role}>"


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id"), nullable=True, index=True
    )
    # Nullable: a failed login has no authenticated user yet.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ts: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<AuditLog {self.id} {self.action!r} user={self.user_id}>"


class Profile(Base):
    """A saved controller-connection profile (migrated from ``profiles.json``).

    ``plain_fields`` holds the non-secret form fields (host, username, …).
    ``enc_secret_fields`` holds the *Fernet ciphertext* of each secret keyed by
    its internal enc-field name (e.g. ``_enc_smartzone_password``) — plaintext
    is NEVER stored. Unique per ``(tenant_id, name)`` so a name is stable within
    a tenant but two tenants may reuse the same name.
    """

    __tablename__ = "profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_profiles_tenant_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plain_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enc_secret_fields: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    saved_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Profile {self.id} tenant={self.tenant_id} {self.name!r}>"


class NotificationConfig(Base):
    """Per-tenant notification/report config (migrated from ``notifications.json``).

    One row per tenant — ``tenant_id`` is the primary key. ``config`` is the
    full merged config blob (same shape as the file-based config), with the SMTP
    password held as Fernet ciphertext under ``smtp.password_enc``.
    """

    __tablename__ = "notification_config"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), primary_key=True
    )
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<NotificationConfig tenant={self.tenant_id}>"
