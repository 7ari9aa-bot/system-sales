"""V12 Wave C — Effects Ledger & Financial Double-Entry Plane.

Revision ID: e3c4d5f6a7b8
Revises: d2b3c4e5f6a7
Create Date: 2026-09-27

Four tenant-scoped tables implementing V12 §30–§31:
1. ``effect_ledger``          — deterministic idempotency key, ambiguous state & reconciliation.
2. ``chart_of_accounts``      — double-entry chart of accounts per tenant.
3. ``financial_transactions`` — atomic financial journal headers.
4. ``financial_entries``      — individual debit/credit entries, balanced per transaction.

RLS: all four tables get ENABLE + FORCE + ``tenant_isolation`` policy via the
standard ``app.tenant_id`` GUC.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e3c4d5f6a7b8"
down_revision: str | None = "d2b3c4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _enable_rls(table: str) -> None:
    """ENABLE + FORCE + the standard tenant_isolation policy for one table."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
    op.execute(
        f"CREATE POLICY tenant_isolation ON public.{table} "
        f"AS RESTRICTIVE "
        f"USING (tenant_id = {_TENANT_GUARD}) "
        f"WITH CHECK (tenant_id = {_TENANT_GUARD})"
    )


def upgrade() -> None:
    # ────────────────────────────────────────────────── 1. effect_ledger ───────
    op.create_table(
        "effect_ledger",
        sa.Column(
            "effect_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("workflow_id", sa.String(128), nullable=True),
        sa.Column("task_id", sa.String(128), nullable=True),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(32), server_default="PENDING", nullable=False),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column(
            "arguments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_effect_ledger_tenant_idempotency"
        ),
    )
    op.create_index(
        "ix_effect_ledger_tenant_status",
        "effect_ledger",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_effect_ledger_tenant_decision",
        "effect_ledger",
        ["tenant_id", "decision_id"],
    )
    op.create_index(
        "ix_effect_ledger_tenant_created",
        "effect_ledger",
        ["tenant_id", "created_at"],
    )
    _enable_rls("effect_ledger")

    # ────────────────────────────────────────────── 2. chart_of_accounts ───────
    op.create_table(
        "chart_of_accounts",
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("account_type", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(3), server_default="SAR", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "code", name="uq_chart_of_accounts_tenant_code"
        ),
    )
    op.create_index(
        "ix_chart_of_accounts_tenant_type",
        "chart_of_accounts",
        ["tenant_id", "account_type"],
    )
    _enable_rls("chart_of_accounts")

    # ───────────────────────────────────────── 3. financial_transactions ───────
    op.create_table(
        "financial_transactions",
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference_type", sa.String(64), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("effect_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("currency", sa.String(3), server_default="SAR", nullable=False),
        sa.Column("status", sa.String(32), server_default="POSTED", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "posted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_financial_transactions_tenant_ref",
        "financial_transactions",
        ["tenant_id", "reference_type", "reference_id"],
    )
    op.create_index(
        "ix_financial_transactions_tenant_posted",
        "financial_transactions",
        ["tenant_id", "posted_at"],
    )
    op.create_index(
        "ix_financial_transactions_tenant_decision",
        "financial_transactions",
        ["tenant_id", "decision_id"],
    )
    _enable_rls("financial_transactions")

    # ────────────────────────────────────────────── 4. financial_entries ───────
    op.create_table(
        "financial_entries",
        sa.Column(
            "entry_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("financial_transactions.transaction_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.account_id"),
            nullable=False,
        ),
        sa.Column("entry_type", sa.String(8), nullable=False),
        sa.Column("amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("memo", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_financial_entries_tenant_account",
        "financial_entries",
        ["tenant_id", "account_id"],
    )
    op.create_index(
        "ix_financial_entries_tenant_tx",
        "financial_entries",
        ["tenant_id", "transaction_id"],
    )
    _enable_rls("financial_entries")


def downgrade() -> None:
    op.drop_table("financial_entries")
    op.drop_table("financial_transactions")
    op.drop_table("chart_of_accounts")
    op.drop_table("effect_ledger")
