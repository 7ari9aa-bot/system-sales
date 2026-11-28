"""Analytics-domain ORM — the SI agent's durable analysis record (§12.4).

Tenant-scoped like every domain table; the evidence row is APPEND-ONLY and
content-hashed (§8.1 — recompute-and-diff compares hashes, never mutates).
Findings are stored beside their pack: a published answer is always
readable together with the graded claims it was built from.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import (
    AppendOnlyCreatedAtMixin,
    TenantMixin,
    WorkspaceScopeMixin,
)


class AnalysisEvidence(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
    """One immutable, content-hashed evidence snapshot (§8.1/§12.4)."""

    __tablename__ = "analysis_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Soft reference to ai's agent_runs.id — a plain UUID column, NOT an
    # FK: an FK would force analytics to import ai's ORM (§1.2 forbids the
    # reverse direction; cross-domain values ride as opaque ids, the
    # orders.deleted_by precedent).
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(31))
    pack: Mapped[dict] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(127))
    # P1-12 provenance: `model` is the ALIAS the agent asked for. An alias is
    # not a model — it can be re-pointed at a different provider next week —
    # so the provider and the concrete model behind it are recorded too. A
    # stored answer that cannot say which model produced it cannot be audited
    # when that model changes.
    provider: Mapped[str | None] = mapped_column(String(63))
    model_version: Mapped[str | None] = mapped_column(String(127))
    prompt_version: Mapped[str | None] = mapped_column(String(31))

    __table_args__ = (Index("ix_analysis_evidence_tenant_created", "tenant_id", "created_at"),)


class AnalysisFinding(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
    """One graded claim published with its evidence (§9.1)."""

    __tablename__ = "analysis_findings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_evidence.id", ondelete="CASCADE"),
    )
    statement: Mapped[str] = mapped_column(Text)
    finding_type: Mapped[str] = mapped_column(String(15))
    relationship: Mapped[str] = mapped_column(String(31))
    confidence: Mapped[str] = mapped_column(String(15))
    confidence_reasons: Mapped[dict] = mapped_column(JSONB, server_default="[]")
    materiality: Mapped[Decimal] = mapped_column(Numeric(18, 8), server_default="0")
    evidence_refs: Mapped[dict] = mapped_column(JSONB, server_default="[]")

    __table_args__ = (
        Index(
            "ix_analysis_findings_tenant_evidence",
            "tenant_id",
            "evidence_id",
        ),
    )
