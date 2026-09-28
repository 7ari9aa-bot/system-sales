"""AUTOMATION domain — tenant-owned workflows run in our internal engine.

Every execution records a WorkflowExecution row; failures land in
WorkflowFailure for retry/compensation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7
from app.core.model_kit import (
    TenantMixin,
    TimestampMixin,
    VersionMixin,
    WorkspaceScopeMixin,
)


class Workflow(TenantMixin, TimestampMixin, VersionMixin, WorkspaceScopeMixin, Base):
    """§17: ``version`` (row CAS) is distinct from ``current_version`` — the
    latter is the definition-snapshot number, the former gates concurrent
    writes to the row itself."""

    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    trigger_event: Mapped[str] = mapped_column(String(127))  # e.g. order.created
    # allowed: draft | active | paused | archived
    status: Mapped[str] = mapped_column(String(15), server_default="draft")
    current_version: Mapped[int] = mapped_column(Integer, server_default="1")

    __table_args__ = (
        Index(
            "ix_workflows_tenant_trigger",
            "tenant_id",
            "trigger_event",
            "status",
        ),
    )


class WorkflowVersion(TenantMixin, TimestampMixin, Base):
    """Immutable definition snapshot — running executions pin their version.

    ``TenantMixin`` is load-bearing, not tidiness: the b2c3d4e5f6a7 RLS sweep is
    dynamic over "tables that have a tenant_id column", so this table was walked
    past and had no policy at all. ``GET /workflows/{id}/versions`` filtered on
    ``workflow_id`` only and relied on the ``WorkflowService.get()`` in front of
    it. Migration a1f2c3d4e5b6 backfills the value from the parent workflow,
    aborts if any row has no parent, and puts FORCE RLS on the table.

    Writers MUST set it: the column is NOT NULL with no server default, so an
    insert that omits it fails rather than guessing a tenant.
    """

    __tablename__ = "workflow_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSONB)  # steps/conditions AST

    __table_args__ = (
        # Was a unique INDEX of the same name; a named CONSTRAINT is a FK target,
        # visible in pg_constraint, and — the part that matters — droppable by a
        # name that resolves when a downgrade runs.
        UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),
    )


class WorkflowExecution(TenantMixin, WorkspaceScopeMixin, Base):
    __tablename__ = "workflow_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE")
    )
    workflow_version: Mapped[int] = mapped_column(Integer)
    # allowed: running | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(15), server_default="running")
    trigger_event_type: Mapped[str | None] = mapped_column(String(127))
    trigger_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    context: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_wf_exec_tenant_workflow_started",
            "tenant_id",
            "workflow_id",
            "started_at",
        ),
    )


class WorkflowFailure(TenantMixin, WorkspaceScopeMixin, Base):
    __tablename__ = "workflow_failures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_executions.id", ondelete="CASCADE")
    )
    step: Mapped[str | None] = mapped_column(String(127))
    error: Mapped[str] = mapped_column(Text)
    # allowed: retry_scheduled | dead | compensated
    resolution: Mapped[str] = mapped_column(String(31), server_default="dead")

    __table_args__ = (Index("ix_wf_failures_execution", "execution_id"),)
