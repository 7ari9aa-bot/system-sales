"""Workspace membership: access to a business is granted, never inferred.

Tenant membership answers "do you belong to this account". It must not answer
"may you work in every business inside it": today one account can hold an
apparel shop and a distribution company, and nothing in the schema says who may
see which. ``resolve_scope`` verifies that a workspace belongs to the tenant and
stops there — so a staff member of the Cairo shop can read the other business by
naming its id.

This table is the missing grant. Explicit rows only: no trigger, no backfill from
tenant roles, because inferring access is exactly the bug being fixed. The owner
and the account administrator get rows too when the app decides to give them, and
that decision stays visible in data instead of hidden in a role check.

RLS is part of the migration, not a later hardening step: a tenant table without
``tenant_isolation`` makes the boot reconciler refuse to start the service.

Revision ID: fe2026112705
Revises: fe2026112704
Create Date: 2026-11-28 00:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112705"
down_revision: str | None = "fe2026112704"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_memberships",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
    )
    op.execute(
        "CREATE INDEX ix_workspace_memberships_tenant_id ON workspace_memberships (tenant_id)"
    )
    op.execute(
        "CREATE INDEX ix_workspace_memberships_user_id ON workspace_memberships (user_id)"
    )
    op.execute("ALTER TABLE workspace_memberships ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE workspace_memberships FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON workspace_memberships "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )
    # The runtime role is created by ``scripts/provision.py``, which runs either before or after
    # Alembic depending on the environment: production already has it, a CI database does not.
    # An unguarded GRANT therefore aborts the whole upgrade with
    # ``role "sales_app" does not exist`` (CI run 46087084159, job live-api, step Apply
    # migrations), taking every later migration with it. Issued inside the same pg_roles DO block
    # the other RLS migrations use, so a database without the role still reaches head and a
    # database with it still gets the grant.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON workspace_memberships TO sales_app;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_table("workspace_memberships")
