"""inventory: channel allocations (§4 Phase 7).

Revision ID: fe2026111627
Revises: fe2026111626
Create Date: 2026-11-17 06:00:00.000000

WHY. Reserving stock per sales channel (e.g. pos, website, whatsapp) so one channel
cannot exhaust the inventory reserved for other channels and prevent overselling
the last unit.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026111627"
down_revision: str = "fe2026111626"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _scoped_columns() -> list[sa.Column]:
    """id + tenant + scope + timestamps (TenantMixin, TimestampMixin, WorkspaceScopeMixin)."""
    return [
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _secure(table: str, grants: str = "SELECT, INSERT, UPDATE, DELETE") -> None:
    """Row-level security exactly like every other tenant table."""
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
            GRANT {grants} ON TABLE {table} TO sales_app;
          END IF;
        END
        $$"""
    )


def upgrade() -> None:
    op.create_table(
        "inventory_channel_allocations",
        *_scoped_columns(),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=31), nullable=False),
        sa.Column("allocated_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reserved_in_channel", sa.Integer(), server_default="0", nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "warehouse_id",
            "variant_id",
            "channel",
            name="uq_inventory_channel_allocations_wh_var_ch",
        ),
        sa.CheckConstraint(
            "allocated_quantity >= 0",
            name="ck_channel_allocations_allocated_qty",
        ),
        sa.CheckConstraint(
            "reserved_in_channel >= 0",
            name="ck_channel_allocations_reserved_qty",
        ),
    )

    op.create_index(
        "ix_inventory_channel_allocations_tenant_id", "inventory_channel_allocations", ["tenant_id"]
    )
    op.create_index(
        "ix_channel_allocations_variant",
        "inventory_channel_allocations",
        ["tenant_id", "variant_id"],
    )
    op.create_index(
        "ix_channel_allocations_warehouse",
        "inventory_channel_allocations",
        ["tenant_id", "warehouse_id"],
    )

    _secure("inventory_channel_allocations")


def downgrade() -> None:
    op.drop_table("inventory_channel_allocations")
