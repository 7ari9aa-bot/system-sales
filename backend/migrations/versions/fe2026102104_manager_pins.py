"""pos: a manager PIN, so a manager can approve one action at the cashier's till.

Revision ID: fe2026102104
Revises: fe2026102103
Create Date: 2026-10-21 06:00:00.000000

Until now an action above a cashier's authority (a discount over the ceiling, a return on another
cashier's drawer) could only be done by signing the manager in on that till. The PIN is the
counter-top version: the cashier stays signed in, the manager types a short secret, and it covers
that one request.

Only a hash is stored. The table holds no digits and no attempt counter (failures live in Redis so
they survive a restart without a write per bad guess). One row per (tenant, manager).

Tenant-scoped with ENABLE + FORCE + tenant_isolation like every other table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026102104"
down_revision: str | None = "fe2026102103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_table("manager_pins")
