"""Shared building blocks for ORM models across all modules.

Conventions:
- Money: Numeric(14, 2) via MONEY.
- Enum-like values: String columns; allowed values are documented inline and
  enforced in domain services — never sa.Enum (avoids PG ENUM migration churn).
- Tenant scoping: TenantMixin on every tenant-scoped table. RLS policies are
  issued by migration for every table carrying tenant_id.
- Sharding readiness: tenant_id present and leading its indexes / scoped unique
  constraints, so a tenant can later move to a dedicated database.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

MONEY = Numeric(14, 2)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class VersionMixin:
    """Optimistic-concurrency counter (attached to concrete models by migration)."""

    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)


class TenantMixin:
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class AppendOnlyCreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
