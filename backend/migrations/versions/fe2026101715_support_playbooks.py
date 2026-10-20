"""support_playbooks — recurring customer problems with their solution steps.

Revision ID: fe2026101715
Revises: fe2026101714
Create Date: 2026-10-20 00:00:00.000000

The customer agent explains how to solve a recurring problem from steps the
MERCHANT wrote, and hands the chat to staff when the playbook's own condition
holds or no playbook matches. It never executes the steps: this table is read
only to the agent.

Separate from ``knowledge_items`` so playbooks cannot crowd store policies out
of get_store_info's token budget. Tenant-scoped with ENABLE + FORCE +
tenant_isolation from day one, same as every agent-owned table, and a
generated tsvector for deterministic search that needs no embedding model.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "fe2026101715"
down_revision: str | None = "fe2026101714"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "support_playbooks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("steps", pg.JSONB(), server_default="[]", nullable=False),
        sa.Column("escalate_when", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "search_ts",
            pg.TSVECTOR(),
            sa.Computed(
                "(setweight(to_tsvector('simple', coalesce(title, '')), 'A') "
                "|| setweight(to_tsvector('simple', coalesce(problem, '')), 'B'))",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_support_playbooks_tenant_id", "support_playbooks", ["tenant_id"])
    op.create_index(
        "ix_support_playbooks_tenant_active", "support_playbooks", ["tenant_id", "is_active"]
    )
    op.create_index("ix_support_playbooks_workspace_id", "support_playbooks", ["workspace_id"])
    op.create_index("ix_support_playbooks_location_id", "support_playbooks", ["location_id"])
    op.create_index(
        "ix_support_playbooks_search_ts", "support_playbooks", ["search_ts"], postgresql_using="gin"
    )
    op.execute("ALTER TABLE support_playbooks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE support_playbooks FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON support_playbooks")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON support_playbooks
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE support_playbooks TO sales_app;
          END IF;
        END
        $$"""
    )

    # Existing customer agents need the new tool row. Provisioning only INSERTs
    # at tenant creation, so without this the runtime would refuse the tool on
    # every tenant that already exists (a missing row means "not authorized").
    op.execute(
        """
        INSERT INTO agent_tools (id, tenant_id, agent_id, name, policy, is_active)
        SELECT gen_random_uuid(), a.tenant_id, a.id, 'find_support_playbook', '{}'::jsonb, true
        FROM agents a
        WHERE a.kind = 'customer'
        ON CONFLICT (tenant_id, agent_id, name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM agent_tools WHERE name = 'find_support_playbook'")
    op.drop_table("support_playbooks")
