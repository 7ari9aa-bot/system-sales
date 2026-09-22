"""AUTOMATION domain (spec §136) — our Workflow is the source of truth.

Tenant Workflow definitions + versions live HERE. n8n (or the internal
engine) is only an EXECUTION adapter — n8n never owns business truth.
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
    # execution backend: internal (our engine) | n8n (adapter) — definition
    # stays HERE either way; n8n never owns the workflow.
    execution_backend: Mapped[str] = mapped_column(String(15), server_default="internal")
    # n8n adapter: remote workflow reference (secret refs only, never creds)
    n8n_workflow_ref: Mapped[str | None] = mapped_column(String(255))
    current_version: Mapped[int] = mapped_column(Integer, server_default="1")

    __table_args__ = (
        Index(
            "ix_workflows_tenant_trigger",
            "tenant_id",
            "trigger_event",
            "status",
        ),
    )


class WorkflowVersion(TimestampMixin, Base):
    """Immutable definition snapshot — running executions pin their version."""

    __tablename__ = "workflow_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSONB)  # steps/conditions AST

    __table_args__ = (
        Index(
            "uq_workflow_versions_workflow_version",
            "workflow_id",
            "version",
            unique=True,
        ),
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
