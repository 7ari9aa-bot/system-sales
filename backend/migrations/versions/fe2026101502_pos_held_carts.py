"""POS held carts — park a basket without selling it (§189 expansion).

Adds ``pos_held_carts``: a cashier parks a customer's basket while they step
aside. The park is a snapshot (variant + quantity lines, an optional customer,
an optional discount, a human label), NOT a sale — holding reserves no stock and
books no money, so the table has no money columns of its own beyond the parked
discount, and nothing here writes a balance.

The table carries tenant_id, so RLS is enabled FORCED with the same
``tenant_isolation`` policy and ``sales_app`` grants as fe2026101501.

Revision ID: fe2026101502
Revises: fe2026101501
Create Date: 2026-10-15 19:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026101502"
down_revision: str | None = "fe2026101501"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

_NEW_TABLES = ("pos_held_carts",)


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
    op.create_table(
        "pos_held_carts",
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
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("pos_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("items", postgresql.JSONB(), nullable=False),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("discount_total", sa.Numeric(14, 2), nullable=True),
        sa.Column("label", sa.String(127), nullable=True),
        sa.Column(
            "held_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )
    _scope_fks("pos_held_carts")
    op.create_index(
        "ix_pos_held_carts_tenant_session",
        "pos_held_carts",
        ["tenant_id", "session_id"],
    )

    for table in _NEW_TABLES:
        _enable_rls(table)

    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE pos_held_carts TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    for table in reversed(_NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_index("ix_pos_held_carts_tenant_session", table_name=table)
        op.drop_table(table)
