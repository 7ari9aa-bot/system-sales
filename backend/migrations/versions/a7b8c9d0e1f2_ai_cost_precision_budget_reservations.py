"""AI cost precision + durable budget reservations (spec §42)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-20

Two problems, both of which made the AI budget decorative:

1. COST PRECISION. `agent_runs.cost`, `model_calls.cost` and `ai_usage.cost`
   are MONEY = Numeric(14,2). A realistic single call costs a fraction of a
   cent, so every row rounded to 0.00 — the monthly spend summed to 0.00 and
   the hard cap could never be reached. Numeric(18,8) keeps sub-cent precision
   while staying exact Decimal arithmetic (ADR-001: never float for money).
   Order/payment money keeps Numeric(14,2): that is a different concern.

2. NO RESERVATION. `enforce_budget` only read the spend so far, so N concurrent
   runs all passed the same preflight and all spent — the cap could be overshot
   by the concurrency factor. A reservation row is taken BEFORE the provider
   call and settled AFTER, which is what makes the cap hold under load.
   `expires_at` matters: a run that crashes between reserve and settle must not
   hold budget forever.

The new table is tenant-scoped, so it needs the same RLS treatment as every
other tenant table — RLS was applied to tables that existed at the time, and a
table created afterwards would otherwise be unprotected.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    # 1. cost precision: 2 decimals cannot express a per-call cost.
    op.alter_column("agent_runs", "cost", type_=sa.Numeric(18, 8))
    op.alter_column("model_calls", "cost", type_=sa.Numeric(18, 8))
    op.alter_column("ai_usage", "cost", type_=sa.Numeric(18, 8))

    # 2. durable budget reservations.
    op.create_table(
        "ai_budget_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount", sa.Numeric(18, 8), nullable=False),
        # allowed: active | settled | expired
        sa.Column(
            "status", sa.String(length=15), nullable=False, server_default="active"
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_ai_budget_reservations_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_budget_reservations_active",
        "ai_budget_reservations",
        ["tenant_id", "status"],
    )

    # 3. RLS: a table created after the RLS migration has no policy yet.
    op.execute("ALTER TABLE public.ai_budget_reservations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.ai_budget_reservations FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON public.ai_budget_reservations"
    )
    op.execute(
        f"""CREATE POLICY tenant_isolation ON public.ai_budget_reservations
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )


def downgrade() -> None:
    op.drop_index("ix_ai_budget_reservations_active", table_name="ai_budget_reservations")
    op.drop_table("ai_budget_reservations")
    op.alter_column("ai_usage", "cost", type_=sa.Numeric(14, 2))
    op.alter_column("model_calls", "cost", type_=sa.Numeric(14, 2))
    op.alter_column("agent_runs", "cost", type_=sa.Numeric(14, 2))
