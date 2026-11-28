"""Effect Ledger domain models (V12 Wave C §30).

Every side effect outside our database (and critical internal state changes)
must be registered in the Effect Ledger with a deterministic idempotency key:
H(tenant + operation + args + workflow + task).

Key features:
- AMBIGUOUS state support: when an external provider call times out or drops,
  the effect is marked AMBIGUOUS instead of failed or succeeded, triggering
  reconciliation without duplicated charges or side-effects.
- Durable lineage: links back to decision_id and authority lease_id.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import TenantMixin

EFFECT_STATUSES: frozenset[str] = frozenset(
    {"PENDING", "EXECUTING", "COMPLETED", "FAILED", "AMBIGUOUS"}
)


class EffectLedger(TenantMixin, Base):
    """The central ledger for all non-database effects and external side effects."""

    __tablename__ = "effect_ledger"

    effect_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_id: Mapped[str | None] = mapped_column(String(128))
    task_id: Mapped[str | None] = mapped_column(String(128))
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(32), server_default="PENDING", nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64))
    provider_reference: Mapped[str | None] = mapped_column(String(255))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_effect_ledger_tenant_idempotency"
        ),
        Index("ix_effect_ledger_tenant_status", "tenant_id", "status"),
        Index("ix_effect_ledger_tenant_decision", "tenant_id", "decision_id"),
        Index("ix_effect_ledger_tenant_created", "tenant_id", "created_at"),
    )
