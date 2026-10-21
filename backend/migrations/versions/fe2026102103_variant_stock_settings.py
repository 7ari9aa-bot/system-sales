"""inventory: a reorder level per variant, so the stock screen can say 'low' and mean it.

Revision ID: fe2026102103
Revises: fe2026102102
Create Date: 2026-10-21 05:00:00.000000

The old cashier screen decided low / out from a hard-coded threshold in mock data. The real rule
needs a stored level per variant. 0 means "no alert configured" and no row reads as 0, so a variant
nobody set up is never reported as running low. The database refuses a negative level or an absurd
one (a barcode scan landing in the field).

Tenant-scoped with ENABLE + FORCE + tenant_isolation like every other table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026102103"
down_revision: str | None = "fe2026102102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "variant_stock_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
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
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "variant_id",
            sa.Uuid(),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reorder_level", sa.Integer(), server_default="0", nullable=False),
        sa.UniqueConstraint("tenant_id", "variant_id", name="uq_variant_stock_settings_variant"),
        sa.CheckConstraint(
            "reorder_level >= 0 AND reorder_level <= 1000000",
            name="ck_variant_stock_settings_level",
        ),
    )
    op.create_index("ix_variant_stock_settings_tenant_id", "variant_stock_settings", ["tenant_id"])
    op.create_index(
        "ix_variant_stock_settings_workspace_id", "variant_stock_settings", ["workspace_id"]
    )
    op.create_index(
        "ix_variant_stock_settings_location_id", "variant_stock_settings", ["location_id"]
    )

    table = "variant_stock_settings"
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
            REVOKE ALL ON TABLE {table} FROM sales_app;
            GRANT SELECT, INSERT, UPDATE ON TABLE {table} TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    op.drop_table("variant_stock_settings")
