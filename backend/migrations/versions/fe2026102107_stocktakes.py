"""inventory: physical stocktake (a count with a book snapshot, approved into the ledger).

Revision ID: fe2026102107
Revises: fe2026102106
Create Date: 2026-10-21 11:00:00.000000

A count takes a snapshot of the book quantity when it opens, because the shop keeps selling while
it is counted. Approval moves only (counted - snapshot) as a relative movement, never an absolute
overwrite. `counted_qty` NULL is "not counted", which is not zero, so an uncounted line is never
adjusted. One OPEN count per warehouse is enforced by a partial unique index, not by the service.

Both tables are tenant-scoped with ENABLE + FORCE + tenant_isolation like every other table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026102107"
down_revision: str | None = "fe2026102106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _common_columns() -> list[sa.Column]:
    return [
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
    ]


def _secure(table: str, grants: str) -> None:
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
        "stocktakes",
        *_common_columns(),
        sa.Column(
            "warehouse_id",
            sa.Uuid(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(15), server_default="OPEN", nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column(
            "opened_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "closed_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('OPEN', 'APPROVED', 'CANCELLED')", name="ck_stocktakes_status"
        ),
        sa.CheckConstraint(
            "(status = 'OPEN') = (closed_at IS NULL)", name="ck_stocktakes_closed_at"
        ),
    )
    op.create_index("ix_stocktakes_tenant_id", "stocktakes", ["tenant_id"])
    op.create_index("ix_stocktakes_workspace_id", "stocktakes", ["workspace_id"])
    op.create_index("ix_stocktakes_location_id", "stocktakes", ["location_id"])
    op.create_index(
        "uq_stocktakes_one_open_per_warehouse",
        "stocktakes",
        ["tenant_id", "warehouse_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    _secure("stocktakes", "SELECT, INSERT, UPDATE")

    op.create_table(
        "stocktake_lines",
        *_common_columns(),
        sa.Column(
            "stocktake_id",
            sa.Uuid(),
            sa.ForeignKey("stocktakes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            sa.Uuid(),
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("expected_qty", sa.Integer(), nullable=False),
        sa.Column("counted_qty", sa.Integer(), nullable=True),
        sa.Column("applied_delta", sa.Integer(), nullable=True),
        sa.UniqueConstraint("stocktake_id", "variant_id", name="uq_stocktake_lines_variant"),
        sa.CheckConstraint("expected_qty >= 0", name="ck_stocktake_lines_expected"),
        sa.CheckConstraint(
            "counted_qty IS NULL OR (counted_qty >= 0 AND counted_qty <= 1000000)",
            name="ck_stocktake_lines_counted",
        ),
    )
    op.create_index("ix_stocktake_lines_tenant_id", "stocktake_lines", ["tenant_id"])
    op.create_index("ix_stocktake_lines_workspace_id", "stocktake_lines", ["workspace_id"])
    op.create_index("ix_stocktake_lines_location_id", "stocktake_lines", ["location_id"])
    op.create_index("ix_stocktake_lines_stocktake", "stocktake_lines", ["stocktake_id"])
    _secure("stocktake_lines", "SELECT, INSERT, UPDATE")


def downgrade() -> None:
    op.drop_table("stocktake_lines")
    op.drop_table("stocktakes")
