"""Settings domain models — hierarchical tenant configuration with audit.

Two tables:

* ``tenant_settings`` stores overrides: a row means "at this scope, this
  key has been explicitly set to this value". The absence of a row means
  "inherit from the parent scope". The resolver walks up the chain at
  read time; this table never stores inherited values.

* ``tenant_settings_history`` is append-only: every write (create, update,
  delete/reset) records who changed what, the before and after, and when.
  It is the audit trail that the operations team reads when a shop says
  "who changed my discount cap yesterday?".
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import (
    AppendOnlyCreatedAtMixin,
    IdMixin,
    TenantMixin,
    TimestampMixin,
)


class TenantSetting(TenantMixin, TimestampMixin, IdMixin, Base):
    """One explicitly-set configuration value at a specific scope.

    A row here means "someone deliberately set this key at this scope to
    this value". There is at most ONE row per (tenant, key, scope, scope_id).
    scope_id is NULL for tenant-level settings.

    ``value`` is JSONB wrapping the actual value as ``{"v": <value>}`` so
    every Python type (bool, int, str, list, dict) round-trips losslessly
    through one column.
    """

    __tablename__ = "tenant_settings"

    key: Mapped[str] = mapped_column(String(127), nullable=False)
    # allowed: tenant | branch | warehouse | pos_profile | register |
    #         channel | user
    scope: Mapped[str] = mapped_column(String(31), server_default="tenant")
    # The id of the scope entity (workspace_id for branch, warehouse_id for
    # warehouse, etc.). NULL = tenant-level.
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # {"v": <actual_value>} — always a dict with one key.
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Who last set this value.
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        # At most one override per (tenant, key, scope, scope_id), NULL included.
        UniqueConstraint(
            "tenant_id",
            "key",
            "scope",
            "scope_id",
            name="uq_tenant_settings_key_scope",
            # NULL scope_id (tenant level) must collide with itself.
            postgresql_nulls_not_distinct=True,
        ),
        # Tenant level has no scope id; every other scope must name its entity.
        CheckConstraint(
            "(scope = 'tenant') = (scope_id IS NULL)",
            name="ck_tenant_settings_scope_id",
        ),
        Index("ix_tenant_settings_tenant_key", "tenant_id", "key"),
        Index("ix_tenant_settings_tenant_scope", "tenant_id", "scope", "scope_id"),
    )


class TenantSettingHistory(TenantMixin, AppendOnlyCreatedAtMixin, IdMixin, Base):
    """Append-only audit of every settings change.

    Every time a setting is created, updated, or reset (deleted), one row
    is appended here. The row records the before/after, who did it, when,
    and optionally why. The settings table itself only knows the current
    value; this table knows the full timeline.
    """

    __tablename__ = "tenant_settings_history"

    setting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_settings.id", ondelete="SET NULL"),
        nullable=True,
    )
    key: Mapped[str] = mapped_column(String(127), nullable=False)
    scope: Mapped[str] = mapped_column(String(31), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # allowed: set | reset | bulk_set
    action: Mapped[str] = mapped_column(String(15), server_default="set")
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    change_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index(
            "ix_tenant_settings_history_tenant_key",
            "tenant_id",
            "key",
            "created_at",
        ),
        Index(
            "ix_tenant_settings_history_tenant_time",
            "tenant_id",
            "created_at",
        ),
    )
