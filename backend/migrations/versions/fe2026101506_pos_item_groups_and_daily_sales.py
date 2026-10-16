"""POS catalog scoping + the daily sales projection (§189 phase 4/5).

Closes the last ERPNext-parity gaps that are structural:

- ``pos_profiles.item_group_ids`` — ERPNext `POS Item Group`: a terminal's
  catalog is scoped to whole categories; an empty list means the tenant's
  whole catalog. Both the browse grid and the scan refuse what the profile
  does not serve.
- ``pos_daily_sales`` — the ERPNext `POS Closing Entry` consolidation, as an
  EVENT-FED PROJECTION (§190): the pos worker pool consumes
  ``pos.session.closed`` and recomputes each (business_date, register) row
  from the ledgers. Never a column on a core table; recomputed, never
  incremented, so redelivery is idempotent.

Every new table carries tenant_id, so RLS is enabled FORCED with the same
``tenant_isolation`` policy and ``sales_app`` grants as fe2026101501.

Revision ID: fe2026101506
Revises: fe2026101505
Create Date: 2026-10-16 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026101506"
down_revision: str | None = "fe2026101505"
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
        "pos_profiles",
        sa.Column(
            "item_group_ids",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
    )

    op.create_table(
        "pos_daily_sales",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column(
            "register_id",
            sa.Uuid(),
            sa.ForeignKey("pos_registers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("session_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("invoice_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("returns_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sales_total", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("returns_total", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("taxes_total", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("variance_total", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("by_method", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "business_date", "register_id",
            name="uq_pos_daily_sales_date_register",
        ),
    )
    op.create_index(
        "ix_pos_daily_tenant_date", "pos_daily_sales", ["tenant_id", "business_date"]
    )
    _scope_fks("pos_daily_sales")
    _enable_rls("pos_daily_sales")
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE pos_daily_sales TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON pos_daily_sales")
    op.drop_table("pos_daily_sales")
    op.drop_column("pos_profiles", "item_group_ids")
