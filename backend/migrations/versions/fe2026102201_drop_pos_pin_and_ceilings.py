"""pos: drop the manager PIN and every money ceiling (not part of the first release).

Revision ID: fe2026102201
Revises: fe2026102109
Create Date: 2026-10-22 09:00:00.000000

The first release has no approval flow. Removed:

* ``manager_pins`` (the manager's counter PIN)
* ``pos_profiles.discount_ceiling_pct``, ``refund_ceiling``, ``cash_out_ceiling``
* ``pos_profiles.returns_allowed_methods``

Kept on purpose: the ``pos:override`` permission, which still lets a manager work on a shift
another cashier holds.

DESTRUCTIVE: any PIN or ceiling already configured is deleted. ``downgrade`` recreates the
structure (RLS included) but cannot bring the values back; ceilings return at their defaults.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026102201"
down_revision: str | None = "fe2026102109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.drop_table("manager_pins")
    op.drop_constraint("ck_pos_profiles_cash_out_ceiling_nonneg", "pos_profiles", type_="check")
    op.drop_constraint("ck_pos_profiles_refund_ceiling_nonneg", "pos_profiles", type_="check")
    op.drop_constraint("ck_pos_profiles_discount_ceiling", "pos_profiles", type_="check")
    op.drop_column("pos_profiles", "cash_out_ceiling")
    op.drop_column("pos_profiles", "refund_ceiling")
    op.drop_column("pos_profiles", "discount_ceiling_pct")
    op.drop_column("pos_profiles", "returns_allowed_methods")


def downgrade() -> None:
    op.add_column(
        "pos_profiles",
        sa.Column(
            "returns_allowed_methods", postgresql.JSONB(), server_default="[]", nullable=False
        ),
    )
    op.add_column(
        "pos_profiles",
        sa.Column("discount_ceiling_pct", sa.Numeric(5, 2), server_default="0", nullable=False),
    )
    op.add_column("pos_profiles", sa.Column("refund_ceiling", sa.Numeric(14, 2), nullable=True))
    op.add_column("pos_profiles", sa.Column("cash_out_ceiling", sa.Numeric(14, 2), nullable=True))
    op.create_check_constraint(
        "ck_pos_profiles_discount_ceiling",
        "pos_profiles",
        "discount_ceiling_pct >= 0 AND discount_ceiling_pct <= 100",
    )
    op.create_check_constraint(
        "ck_pos_profiles_refund_ceiling_nonneg",
        "pos_profiles",
        "refund_ceiling IS NULL OR refund_ceiling >= 0",
    )
    op.create_check_constraint(
        "ck_pos_profiles_cash_out_ceiling_nonneg",
        "pos_profiles",
        "cash_out_ceiling IS NULL OR cash_out_ceiling >= 0",
    )

    op.create_table(
        "manager_pins",
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
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("pin_hash", sa.String(255), nullable=False),
        sa.Column(
            "set_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_manager_pins_user"),
    )
    op.create_index("ix_manager_pins_tenant_id", "manager_pins", ["tenant_id"])
    op.create_index("ix_manager_pins_workspace_id", "manager_pins", ["workspace_id"])
    op.create_index("ix_manager_pins_location_id", "manager_pins", ["location_id"])
    table = "manager_pins"
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
