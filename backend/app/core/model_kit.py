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

from app.core.tenancy import current_scope

MONEY = Numeric(14, 2)


def _current_workspace_id() -> uuid.UUID | None:
    return current_scope()[0]


def _current_location_id() -> uuid.UUID | None:
    return current_scope()[1]


# AI spend needs sub-cent precision: a single model call costs a fraction of a
# cent, so Numeric(14,2) rounded every row to 0.00, the monthly total summed to
# zero and the hard cap could never be reached. Still exact Decimal (ADR-001).
AI_COST = Numeric(18, 8)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


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


class WorkspaceScopeMixin:
    """Optional finer scoping columns (spec §151). Nullable = tenant-wide.

    Declared with real FKs so every tenant-scoped table can optionally pin a
    row to a workspace and/or location; NULL keeps the row tenant-wide.
    ondelete SET NULL keeps the rows alive when a hierarchy node is removed.

    §151 Q4: the INSERT default reads the request-scoped current_scope() —
    a mutation inside a scoped request stamps its rows automatically, while
    unscoped writers (workers, jobs) keep the NULL = tenant-wide semantics.
    """

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        default=_current_workspace_id,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        default=_current_location_id,
    )


class AppendOnlyCreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
