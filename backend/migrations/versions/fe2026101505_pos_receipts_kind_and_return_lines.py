"""POS returns as a first-class document (§189 phase 2).

ERPNext treats a POS return as its own document against the original sale:
quantities come back line by line, money returns through the ORIGINAL tender
methods, and the return prints its own receipt. This migration carries that
design:

- ``pos_receipts.kind`` — ``sale`` | ``return``; a return gets its own
  ``POS-RET-`` receipt number series.
- ``pos_return_lines`` — the returned lines of one return receipt, priced at
  the ORIGINAL sale's line prices. This table is the single source for "how
  much of this sale has already come back", for both the money cap and the
  per-variant restock cap.

Every new table carries tenant_id, so RLS is enabled FORCED with the same
``tenant_isolation`` policy and ``sales_app`` grants as fe2026101501.

Revision ID: fe2026101505
Revises: fe2026101504
Create Date: 2026-10-15 20:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026101505"
down_revision: str | None = "fe2026101504"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _scope_fks(table: str) -> None:
    op.create_foreign_key(
        f"fk_{table}_workspace_id", table, "workspaces", ["workspace_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        f"fk_{table}_location_id", table, "locations", ["location_id"], ["id"],
        ondelete="SET NULL",
    )


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )


def upgrade() -> None:
    op.add_column(
        "pos_receipts",
        sa.Column("kind", sa.String(7), server_default="sale", nullable=False),
    )
    op.create_check_constraint(
        "ck_pos_receipts_kind", "pos_receipts", "kind IN ('sale', 'return')"
    )

    op.create_table(
        "pos_return_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column(
            "receipt_id",
            sa.Uuid(),
            sa.ForeignKey("pos_receipts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            sa.Uuid(),
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("refund_total", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_pos_return_lines_tenant_order",
        "pos_return_lines",
        ["tenant_id", "order_id"],
    )
    _scope_fks("pos_return_lines")
    _enable_rls("pos_return_lines")
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE pos_return_lines TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON pos_return_lines")
    op.drop_table("pos_return_lines")
    op.drop_constraint("ck_pos_receipts_kind", "pos_receipts", type_="check")
    op.drop_column("pos_receipts", "kind")
