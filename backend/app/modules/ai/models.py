"""AI domain models — agents, tools, prompts, model configs, memories,
knowledge items, agent runs, tool calls, model calls, usage rollups.

All tables are tenant-scoped (TenantMixin first) so RLS policies and sharding
conventions apply uniformly. Cross-module FKs reference tenants.id, users.id,
customers.id and conversations.id only; FKs between AI-owned tables are local
to this module.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import (
    MONEY,
    AppendOnlyCreatedAtMixin,
    TenantMixin,
    TimestampMixin,
)


class Agent(TenantMixin, TimestampMixin, Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(127))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    temperature: Mapped[float] = mapped_column(Numeric(3, 2), default=0.7, server_default="0.7")
    max_output_tokens: Mapped[int | None] = mapped_column()
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class AgentTool(TenantMixin, TimestampMixin, Base):
    __tablename__ = "agent_tools"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(63))
    # policy: allowed_actions[], requires_approval, budget caps (JSONB)
    policy: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", "name", name="uq_agent_tools_tenant_agent_name"),
    )


class Prompt(TenantMixin, TimestampMixin, Base):
    __tablename__ = "prompts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(127))
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    template: Mapped[str] = mapped_column(Text)
    variables: Mapped[list[str]] = mapped_column(ARRAY(String(63)), server_default="{}")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "version", name="uq_prompts_tenant_name_version"),
    )


class ModelConfig(TenantMixin, TimestampMixin, Base):
    __tablename__ = "model_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # alias: fast | strong | cheap | embedding | fallback
    alias: Mapped[str] = mapped_column(String(31))
    provider: Mapped[str] = mapped_column(String(31))
    model: Mapped[str] = mapped_column(String(127))
    config: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    __table_args__ = (UniqueConstraint("tenant_id", "alias", name="uq_model_configs_tenant_alias"),)


class Memory(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    # kind: summary | preference | fact
    kind: Mapped[str] = mapped_column(String(15))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_memories_tenant_customer", "tenant_id", "customer_id"),
    )


class KnowledgeItem(TenantMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(255))
    # source_type: text | file | url | qa
    source_type: Mapped[str] = mapped_column(String(15))
    source_ref: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    # status: pending | indexed | failed
    status: Mapped[str] = mapped_column(String(15), server_default="pending")

    __table_args__ = (
        Index("ix_knowledge_tenant_status", "tenant_id", "status"),
    )


class AgentRun(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    # status: running | succeeded | failed | timeout
    status: Mapped[str] = mapped_column(String(15), server_default="running")
    input: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int] = mapped_column(default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(default=0, server_default="0")
    cost: Mapped[float] = mapped_column(MONEY, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_agent_runs_tenant_agent_created",
            "tenant_id",
            "agent_id",
            "created_at",
        ),
    )


class ToolCall(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE")
    )
    agent_tool_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_tools.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(63))
    args: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # status: ok | error | denied
    status: Mapped[str] = mapped_column(String(15))
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column()

    __table_args__ = (Index("ix_tool_calls_tenant_run", "tenant_id", "run_id"),)


class ModelCall(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    __tablename__ = "model_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    # alias: fast | strong | cheap | embedding | fallback
    alias: Mapped[str | None] = mapped_column(String(31))
    provider: Mapped[str | None] = mapped_column(String(31))
    model: Mapped[str | None] = mapped_column(String(127))
    tokens_in: Mapped[int] = mapped_column(default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(default=0, server_default="0")
    cost: Mapped[float] = mapped_column(MONEY, default=0, server_default="0")
    latency_ms: Mapped[int | None] = mapped_column()
    # status: ok | error
    status: Mapped[str] = mapped_column(String(15), server_default="ok")

    __table_args__ = (
        Index("ix_model_calls_tenant_created", "tenant_id", "created_at"),
    )


class AIUsage(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    """Daily per-agent AI usage rollup."""

    __tablename__ = "ai_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    period_date: Mapped[date] = mapped_column(Date)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    tokens_in: Mapped[int] = mapped_column(default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(default=0, server_default="0")
    cost: Mapped[float] = mapped_column(MONEY, default=0, server_default="0")
    model_calls: Mapped[int] = mapped_column(default=0, server_default="0")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "period_date", "agent_id", name="uq_ai_usage_tenant_period_agent"
        ),
        Index("ix_ai_usage_tenant_period", "tenant_id", "period_date"),
    )
