"""expenses: categories, expenses and gap-free document counters.

Revision ID: fe2026102001
Revises: fe2026101715
Create Date: 2026-10-20 14:00:00.000000

A cash expense is paid out of an OPEN POS drawer and books one pay_out row there
(reference_type='expense'). The DB itself refuses a cash expense without a shift and a
non-cash expense with one, a zero/negative amount, and a duplicate document number.
Tenant-scoped with ENABLE + FORCE + tenant_isolation from day one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026102001"
down_revision: str | None = "fe2026101715"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_TABLES = ("expense_categories", "expenses", "document_counters")


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    ]


def _scope_indexes(table: str) -> None:
    op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
    op.create_index(f"ix_{table}_location_id", table, ["location_id"])


def _secure(table: str) -> None:
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
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO sales_app;
          END IF;
        END
        $$"""
    )


def upgrade() -> None:
    op.create_table(
        "expense_categories",
        *_common_columns(),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_expense_categories_tenant_name"),
    )
    _scope_indexes("expense_categories")

    op.create_table(
        "document_counters",
        *_common_columns(),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("last_seq", sa.Integer(), server_default="0", nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "kind", "year", name="uq_document_counters_tenant_kind_year"
        ),
    )
    _scope_indexes("document_counters")

    op.create_table(
        "expenses",
        *_common_columns(),
        sa.Column("number", sa.String(31), nullable=False),
        sa.Column(
            "category_id",
            sa.Uuid(),
            sa.ForeignKey("expense_categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("payment_method", sa.String(15), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("pos_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(15), server_default="posted", nullable=False),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("void_reason", sa.String(255), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("tenant_id", "number", name="uq_expenses_tenant_number"),
        sa.CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        sa.CheckConstraint("status IN ('posted','voided')", name="ck_expenses_status"),
        sa.CheckConstraint(
            "payment_method IN ('cash','card','wallet','bank_transfer')",
            name="ck_expenses_payment_method",
        ),
        sa.CheckConstraint(
            "(payment_method = 'cash') = (session_id IS NOT NULL)",
            name="ck_expenses_cash_has_session",
        ),
    )
    _scope_indexes("expenses")
    op.create_index("ix_expenses_tenant_date", "expenses", ["tenant_id", "expense_date"])
    op.create_index("ix_expenses_tenant_category", "expenses", ["tenant_id", "category_id"])

    for table in _TABLES:
        _secure(table)


def downgrade() -> None:
    op.drop_table("expenses")
    op.drop_table("document_counters")
    op.drop_table("expense_categories")
