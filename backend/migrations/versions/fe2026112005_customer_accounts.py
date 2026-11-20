"""customer accounts: credit terms and an append-only ledger.

Revision ID: fe2026112005
Revises: fe2026112004
Create Date: 2026-11-20 11:00:00.000000

The ledger is append-only in TWO layers: the application role is granted SELECT and INSERT only
(it cannot UPDATE or DELETE even by mistake), and a row trigger refuses both for any role that
slipped past the grants. A wrong entry is undone with a reversal entry, never an edit.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112005"
down_revision: str | None = "fe2026112004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_FN = "customer_ledger_append_only"


def _rls(table: str, grants: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )
    op.execute(
        f"""DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT {grants} ON TABLE {table} TO sales_app;
          END IF;
        END
        $$"""
    )


def upgrade() -> None:
    op.create_table(
        "customer_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("credit_limit", sa.Numeric(14, 2), nullable=True),
        sa.Column("note", sa.String(255), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "customer_id", name="uq_customer_accounts_tenant_customer"
        ),
        sa.CheckConstraint(
            "credit_limit IS NULL OR credit_limit >= 0", name="ck_customer_accounts_limit"
        ),
    )
    op.create_table(
        "customer_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entry_type", sa.String(31), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "order_id", sa.Uuid(), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=True
        ),
        sa.Column(
            "reverses_entry_id",
            sa.Uuid(),
            sa.ForeignKey("customer_ledger.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(127), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("balance_after", sa.Numeric(14, 2), nullable=False),
        sa.CheckConstraint(
            "entry_type IN ('charge','payment','deposit','deposit_applied',"
            "'adjustment','reversal')",
            name="ck_customer_ledger_type",
        ),
        sa.CheckConstraint("amount <> 0", name="ck_customer_ledger_nonzero"),
        sa.CheckConstraint(
            "(entry_type IN ('charge','deposit_applied') AND amount > 0) "
            "OR (entry_type IN ('payment','deposit') AND amount < 0) "
            "OR entry_type IN ('adjustment','reversal')",
            name="ck_customer_ledger_sign",
        ),
        sa.CheckConstraint(
            "entry_type <> 'adjustment' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_customer_ledger_adjustment_reason",
        ),
        sa.CheckConstraint(
            "(entry_type = 'reversal') = (reverses_entry_id IS NOT NULL)",
            name="ck_customer_ledger_reversal_link",
        ),
    )
    op.create_index(
        "ix_customer_ledger_tenant_customer",
        "customer_ledger",
        ["tenant_id", "customer_id", "seq"],
    )
    op.create_index("ix_customer_ledger_order", "customer_ledger", ["tenant_id", "order_id"])
    op.create_index(
        "uq_customer_ledger_one_reversal",
        "customer_ledger",
        ["tenant_id", "reverses_entry_id"],
        unique=True,
        postgresql_where=sa.text("reverses_entry_id IS NOT NULL"),
    )
    op.create_index(
        "uq_customer_ledger_idempotency",
        "customer_ledger",
        ["tenant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    _rls("customer_accounts", "SELECT, INSERT, UPDATE, DELETE")
    # the ledger: SELECT and INSERT only, no UPDATE or DELETE grant at all
    _rls("customer_ledger", "SELECT, INSERT")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.{_FN}() RETURNS trigger
        LANGUAGE plpgsql AS $guard$
        BEGIN
            -- a tenant being deleted cascades away its ledger; that is not an edit of history
            IF TG_OP = 'DELETE'
               AND NOT EXISTS (SELECT 1 FROM public.tenants WHERE id = OLD.tenant_id) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'customer ledger entry % cannot be %: post a reversal instead',
                OLD.id, TG_OP
                USING HINT = 'the ledger is append-only';
        END
        $guard$
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_FN} ON public.customer_ledger")
    op.execute(
        f"""CREATE TRIGGER {_FN}
            BEFORE UPDATE OR DELETE ON public.customer_ledger
            FOR EACH ROW EXECUTE FUNCTION public.{_FN}()"""
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_FN} ON public.customer_ledger")
    op.execute(f"DROP FUNCTION IF EXISTS public.{_FN}()")
    op.drop_table("customer_ledger")
    op.drop_table("customer_accounts")
