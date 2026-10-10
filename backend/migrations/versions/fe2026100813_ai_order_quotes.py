"""ai_order_quotes — server-persisted quotes awaiting the customer's confirmation.

Revision ID: fe2026100813
Revises: fe2026100812
Create Date: 2026-10-10 00:00:00.000000

P1-10: ``create_order`` must not execute on the model's word alone. The tool
mints a row here (items + total + an expiring 6-digit code echoed into the
chat) and only a quote whose code the CUSTOMER typed back authorizes the
order. A new tenant-scoped table ships with ENABLE + FORCE + tenant_isolation
from day one — the gap fe2026100810 closed for agent_versions must not reopen.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "fe2026100813"
down_revision: str | None = "fe2026100812"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"



def upgrade() -> None:
    op.create_table(
        "ai_order_quotes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("items", pg.JSONB(), server_default="[]", nullable=False),
        sa.Column("grand_total", sa.Numeric(18, 8), server_default="0", nullable=False),
        sa.Column("currency", sa.String(3), server_default="EGP", nullable=False),
        sa.Column("code", sa.String(12), nullable=False),
        sa.Column("status", sa.String(15), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_ai_order_quotes_conversation_status",
        "ai_order_quotes",
        ["tenant_id", "conversation_id", "status"],
    )
    # The mixin declares both scope columns indexed; a model index no migration
    # creates is a silent full-scan waiting for the first tenant that scopes a
    # quote (fe2026100803 is that cleanup, already paid for once).
    op.create_index("ix_ai_order_quotes_workspace_id", "ai_order_quotes", ["workspace_id"])
    op.create_index("ix_ai_order_quotes_location_id", "ai_order_quotes", ["location_id"])
    op.execute("ALTER TABLE ai_order_quotes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_order_quotes FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_order_quotes")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON ai_order_quotes
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )
    # CI provisions sales_app after Alembic, while production already has it.
    # Guard the grants so both deploy orders remain valid.
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ai_order_quotes TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_order_quotes")
    op.drop_table("ai_order_quotes")
