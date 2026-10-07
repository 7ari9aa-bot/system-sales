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
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import (
    AI_COST,
    AppendOnlyCreatedAtMixin,
    TenantMixin,
    TimestampMixin,
    VersionMixin,
    WorkspaceScopeMixin,
)


class Agent(TenantMixin, TimestampMixin, WorkspaceScopeMixin, VersionMixin, Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kind: Mapped[str] = mapped_column(String(63), server_default="customer")
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(127))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    temperature: Mapped[float] = mapped_column(Numeric(3, 2), default=0.7, server_default="0.7")
    max_output_tokens: Mapped[int | None] = mapped_column()
    # Per-agent execution guardrails; omitted keys use runtime defaults.
    run_limits: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", name="uq_agents_tenant_kind"),
    )


class AgentTool(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
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


class Prompt(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
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


class ModelConfig(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
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


class Memory(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
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
    # §158: governed provenance — "customer said X" ≠ "system verified X"
    # allowed sources: customer_stated | system_verified | agent_inferred | staff_entered
    source: Mapped[str] = mapped_column(String(31), server_default="customer_stated")
    # §158: every claim records WHO wrote it (staff audit + invalidation trail)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), server_default="0.5")
    # §158: staff can take a claim out of service without losing the audit
    # trail — allowed: active | invalidated
    status: Mapped[str] = mapped_column(String(15), server_default="active")
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # kind: summary | preference | fact
    kind: Mapped[str] = mapped_column(String(15))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_memories_tenant_customer", "tenant_id", "customer_id"),
    )


class KnowledgeItem(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
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
    # §157 visibility: retrieval filters on this BEFORE context injection
    # allowed: customer_facing | staff_only | internal | admin_only
    visibility: Mapped[str] = mapped_column(
        String(15), server_default="customer_facing"
    )

    # §45 full text — DATABASE-DERIVED, never assign. Complements the pgvector
    # `embedding`: the vector answers "what is about this", this answers "what
    # literally contains this word", and `simple` is pinned because a GENERATED
    # column needs an IMMUTABLE expression (the 1-argument to_tsvector is only
    # STABLE) and is the only configuration that treats mixed Arabic+Latin
    # knowledge content without stemming one of them. Migration b2e3d4f5a6c7.
    search_ts: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "(setweight(to_tsvector('simple', coalesce(title, '')), 'A') "
            "|| setweight(to_tsvector('simple', coalesce(content, '')), 'B'))",
            persisted=True,
        ),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_knowledge_tenant_status", "tenant_id", "status"),
    )


class AgentRun(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
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
    # status: running | succeeded | failed | timeout | WAITING_APPROVAL
    # (31 chars — "WAITING_APPROVAL" is 16 and must fit §135's durable state)
    status: Mapped[str] = mapped_column(String(31), server_default="running")
    input: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int] = mapped_column(default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(default=0, server_default="0")
    cost: Mapped[Decimal] = mapped_column(AI_COST, default=0, server_default="0")
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


class ToolCall(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
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
    # §15-16: idempotency key = f"{run_id}:{tool_call_id}" — a retried run or
    # replayed event that re-issues the same tool call finds the prior row
    # and skips execution, preventing duplicate side-effects (double orders,
    # double tags). The unique constraint makes the check atomic.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # status: ok | error | denied | awaiting_approval
    # (31 chars — "awaiting_approval" is 17 and the §135 gate writes it here;
    # varchar(15) made the first gated tool call raise TruncationError.)
    status: Mapped[str] = mapped_column(String(31))
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column()

    __table_args__ = (
        Index("ix_tool_calls_tenant_run", "tenant_id", "run_id"),
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_tool_calls_tenant_idempotency"
        ),
    )


class ModelCall(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
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
    cost: Mapped[Decimal] = mapped_column(AI_COST, default=0, server_default="0")
    latency_ms: Mapped[int | None] = mapped_column()
    # status: ok | error
    status: Mapped[str] = mapped_column(String(15), server_default="ok")

    __table_args__ = (
        Index("ix_model_calls_tenant_created", "tenant_id", "created_at"),
    )


class AIUsage(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
    """Daily per-bucket AI usage rollup: one row per (tenant, day, bucket).

    A ROLLUP, not an event log — the point of the row is that writes accumulate
    into it. ``ai/usage.py`` writes it as ``INSERT ... ON CONFLICT ... DO UPDATE``,
    and an upsert is only as good as its conflict target, which is why the two
    keys below are described in terms of what each can *match*:

    * ``uq_ai_usage_tenant_period_agent`` arbitrates the per-agent bucket. A plain
      UNIQUE compares NULLs as DISTINCT (the SQL standard default, and the reason
      ``NULLS NOT DISTINCT`` exists since PG 15), so this key is void for a row
      whose ``agent_id`` IS NULL: ``agent_id = NULL`` never matches, the UPDATE
      branch is unreachable, and each write inserts. ``agent_id`` stays nullable
      because it is a real FK — deleting an agent must not delete or orphan-block
      its cost history, hence ``ON DELETE SET NULL``.
    * ``PRIMARY KEY (id, period_date)`` therefore arbitrates the agent-less
      bucket, whose ``id`` is derived from the bucket key rather than random
      (``ai/usage.bucket_row_id``). ``(id, period_date)`` and not ``(id)`` because
      ``f7a2c9d4e8b1`` made the table a monthly RANGE partition on ``period_date``
      and Postgres refuses a unique key that omits the partition column; that is
      also why ``ai_usage.id`` is no longer globally unique at the database level,
      so the ORM must not claim it alone as the row's identity.
    """

    __tablename__ = "ai_usage"

    # (id, period_date): both columns are `primary_key=True`, and declaration
    # order puts `id` first, which is the column order the migrated key has.
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # The bucket's business day, and the partition key — so it is part of the
    # identity, not merely a column that happens to be indexed.
    period_date: Mapped[date] = mapped_column(Date, primary_key=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    tokens_in: Mapped[int] = mapped_column(default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(default=0, server_default="0")
    cost: Mapped[Decimal] = mapped_column(AI_COST, default=0, server_default="0")
    model_calls: Mapped[int] = mapped_column(default=0, server_default="0")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "period_date", "agent_id", name="uq_ai_usage_tenant_period_agent"
        ),
        Index("ix_ai_usage_tenant_period", "tenant_id", "period_date"),
    )


class ApprovalRequest(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """Spec §135: durable human-in-the-loop approval for HIGH-risk AI actions.

    The AI run persists WAITING_APPROVAL state; approval resumes/rejects it.
    Stale on new customer message (re-evaluate context, never auto-continue).
    """

    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    # requested_by: ai | automation | system
    requested_by: Mapped[str] = mapped_column(String(31), server_default="ai")
    entity_type: Mapped[str] = mapped_column(String(63))
    entity_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(127))
    # allowed: LOW | MEDIUM | HIGH
    risk_level: Mapped[str] = mapped_column(String(15), server_default="HIGH")
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # §135 (review G-02): SHA-256 of the canonicalised arguments this approval
    # authorizes. `payload` alone records what was approved but nothing ever
    # compared it, so a resume matched on the ACTION NAME ONLY — a human could
    # approve `create_order(quantity=1)` and the resumed run would execute
    # whatever arguments it computed this time. NULL means "not bound" and is
    # deliberately never matched, so rows predating this column fail closed.
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    # allowed: PENDING | APPROVED | REJECTED | EXPIRED | CANCELLED
    status: Mapped[str] = mapped_column(String(15), server_default="PENDING")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # §135: an approval authorizes exactly ONE execution of the action. Set when
    # the gated tool actually runs, so a resumed run cannot reuse it.
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_approvals_tenant_status", "tenant_id", "status", "expires_at"),
    )


class BudgetPolicy(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """Spec §42: per-tenant AI budget with reserve/settle + alert thresholds."""

    __tablename__ = "ai_budget_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scope: Mapped[str] = mapped_column(String(15), server_default="tenant")  # tenant|agent
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE")
    )
    period: Mapped[str] = mapped_column(String(15), server_default="monthly")  # daily|monthly
    hard_cap: Mapped[Decimal] = mapped_column(AI_COST, server_default="0")
    warning_threshold: Mapped[int] = mapped_column(default=80)  # percent
    # allowed: block | fallback | warn
    on_exceed: Mapped[str] = mapped_column(String(15), server_default="block")
    fallback_alias: Mapped[str | None] = mapped_column(String(31))

    __table_args__ = (
        UniqueConstraint("tenant_id", "scope", "period", "agent_id", name="uq_budget_scope"),
    )


class AIProviderPolicy(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """Spec §43: per-tenant provider allow/deny + data governance."""

    __tablename__ = "ai_provider_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(31))
    # allowed: allowed | denied
    status: Mapped[str] = mapped_column(String(15), server_default="allowed")
    allowed_models: Mapped[list] = mapped_column(JSONB, server_default="[]")
    pii_redaction_required: Mapped[bool] = mapped_column(Boolean, server_default="false")
    data_classification: Mapped[str] = mapped_column(String(31), server_default="internal")
    # §43 Data residency: a region token the tenant's data may not leave
    # ("eu", "me", ...). Enforced against the model config's resolved region;
    # a declared residency with an unknown provider region FAILS CLOSED.
    data_residency: Mapped[str | None] = mapped_column(String(31))
    # §43 Retention: documented provider data-processing/retention terms.
    # Stored on the row so "where did this data go, for how long" is auditable.
    retention_terms: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_ai_provider_policy"),
    )


class AIHandover(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
    """Spec §37/§150: AI → human handover with reason and outcome."""

    __tablename__ = "ai_handovers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    # allowed: budget | policy | low_confidence | customer_request | failure | guardrail
    reason: Mapped[str] = mapped_column(String(31))
    # allowed: pending | claimed | resolved
    status: Mapped[str] = mapped_column(String(15), server_default="pending")
    claimed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_handovers_tenant_status", "tenant_id", "status", "created_at"),
    )


class AIEvaluation(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """Spec §169: offline evaluation of an agent/prompt version before rollout."""

    __tablename__ = "ai_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE")
    )
    prompt_version: Mapped[int] = mapped_column(default=1)
    dataset_ref: Mapped[str | None] = mapped_column(String(255))
    # allowed: pending | running | passed | failed | approved | rolled_back
    status: Mapped[str] = mapped_column(String(15), server_default="pending")
    quality_metrics: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # allowed: none | canary | full
    rollout_status: Mapped[str] = mapped_column(String(15), server_default="none")
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_evaluations_tenant_agent", "tenant_id", "agent_id", "created_at"),
    )


class AIBudgetReservation(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    """Spec §42: budget taken BEFORE a provider call, settled after.

    A preflight that only reads the spend so far lets N concurrent runs all
    pass the same check and all spend — the cap is then overshot by the
    concurrency factor. Reserving first makes the cap hold under load.

    `expires_at` is the safety valve: a run that crashes between reserve and
    settle must not hold budget forever, so a sweep expires stale rows.

    Deliberately NOT workspace-scoped: a budget is per tenant/agent, so the
    extra scope columns would be dead weight (and the migration does not create
    them — the model and the table must agree).
    """

    __tablename__ = "ai_budget_reservations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    amount: Mapped[Decimal] = mapped_column(AI_COST, nullable=False)
    # allowed: active | settled | expired
    status: Mapped[str] = mapped_column(String(15), server_default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_ai_budget_reservations_active", "tenant_id", "status"),
    )


class ProductEmbedding(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
    """Spec §12.6/§20: one vision vector per approved product image.

    The spec names the source table ``product_media``; the catalog's
    append-only gallery is ``product_images`` and is the same thing —
    approved, ordered product photos. model + model_version ride every row
    so a provider-model change is a full re-index by construction: the
    UNIQUE constraint makes mixed-model vectors impossible, and the HNSW
    index answers the retrieval path's cosine top-k.
    """

    __tablename__ = "product_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_images.id", ondelete="CASCADE")
    )
    # Denormalized from the image's product so retrieval filters by product
    # liveness without a join inside the vector query.
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE")
    )
    vector = mapped_column(Vector(768), nullable=False)
    model: Mapped[str] = mapped_column(String(127))
    model_version: Mapped[str] = mapped_column(String(63), server_default="1")
    # allowed: image | image+text — what the item embedded carried.
    content_kind: Mapped[str] = mapped_column(String(15), server_default="image")

    __table_args__ = (
        UniqueConstraint(
            "product_image_id",
            "model",
            "model_version",
            name="uq_product_embeddings_image_model_version",
        ),
        Index(
            "ix_product_embeddings_vector_hnsw",
            "vector",
            postgresql_using="hnsw",
            postgresql_ops={"vector": "vector_cosine_ops"},
        ),
        Index("ix_product_embeddings_tenant_product", "tenant_id", "product_id"),
    )


class ProductAttribute(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
    """Spec §12.6: Qwen-derived structured attributes per product.

    Pre-filter inputs and the attribute-consistency factor of the vision
    Decision Engine read these; the agent never writes them at reply time —
    the indexer derives them offline, like the embeddings.
    """

    __tablename__ = "product_attributes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE")
    )
    color: Mapped[str | None] = mapped_column(String(63))
    material: Mapped[str | None] = mapped_column(String(63))
    style: Mapped[str | None] = mapped_column(String(63))
    category: Mapped[str | None] = mapped_column(String(63))
    model: Mapped[str] = mapped_column(String(127))
    model_version: Mapped[str] = mapped_column(String(63), server_default="1")

    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "model",
            "model_version",
            name="uq_product_attributes_product_model_version",
        ),
    )


class ConversationAgentState(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """Spec §8/§20: the per-conversation agent state the system owns.

    The model proposes a state_patch; the validator applies it atomically
    against state_version (optimistic concurrency). shown_items/sent_media
    power the Referent Resolver ("التاني", reply-on-image) and the
    no-resend rule for media.
    """

    __tablename__ = "conversation_agent_states"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), unique=True
    )
    state: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    shown_items: Mapped[list] = mapped_column(JSONB, server_default="[]")
    sent_media: Mapped[list] = mapped_column(JSONB, server_default="[]")
    state_version: Mapped[int] = mapped_column(Integer, server_default="1")
