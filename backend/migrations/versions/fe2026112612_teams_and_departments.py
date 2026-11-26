"""Teams: the grouping the permission matrix could not express.

Revision ID: fe2026112608
Revises: fe2026112607

The settings map asks the Team section for "teams and departments", and the schema
had no such thing: a person held one role per workspace, and that was the whole
model. The absence was visible in the product — every attempt to say "the Cairo
branch team" had to be encoded in the role, which then granted permissions.

Deliberate modelling decisions:

- A team is a GROUPING, never a grant. Membership in a team changes nothing about
  what a person may do; permissions still come from ``role_permissions`` and the
  location grants in ``user_location_access``. This is why the tables carry no
  role column: a team that could grant would be a second, silent permission
  system, which is exactly what the map forbids.
- ``tenant_id`` on both tables, not only on ``teams``: RLS on a join table with no
  tenant column would have to reach through the parent on every policy, and a
  policy that reaches is a policy that can be got wrong. The tenant is denormalised
  and the FK makes it consistent.
- One name per tenant: ``uq_teams_tenant_name``. Two teams called "المخزن" is not a
  naming preference, it is a picker nobody can use.
- RLS is tenant-scoped on ``app.tenant_id``, the same guard as every other tenant
  table, so a forgotten filter cannot cross a tenant.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112612"
down_revision: str | None = "fe2026112611"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

_GRANT_SALES_APP = """DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
        {grant};
    END IF;
END
$$;"""


def _grant_sales_app(grant: str) -> str:
    return _GRANT_SALES_APP.format(grant=grant)


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
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
    )
    op.create_index("ix_teams_tenant_id", "teams", ["tenant_id"])
    op.create_unique_constraint("uq_teams_tenant_name", "teams", ["tenant_id", "name"])

    op.create_table(
        "team_members",
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_team_members_tenant_id", "team_members", ["tenant_id"])
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])

    for table in ("teams", "team_members"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""CREATE POLICY {table}_tenant_read ON {table}
                FOR SELECT USING (tenant_id = {_TENANT_GUARD})"""
        )
        op.execute(
            f"""CREATE POLICY {table}_tenant_write ON {table}
                FOR ALL USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD})"""
        )
        op.execute(
            _grant_sales_app(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO sales_app")
        )


def downgrade() -> None:
    op.drop_table("team_members")
    op.drop_table("teams")
