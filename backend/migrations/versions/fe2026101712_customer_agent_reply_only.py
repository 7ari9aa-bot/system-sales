"""customer agent reply-only scope cut — incoming_stock in, order tools out.

Revision ID: fe2026101712
Revises: fe2026101711
Create Date: 2026-10-18 00:00:00.000000

The customer agent is now language-only: it answers from store data and
escalates; it never sells. Three movements:

1. ``incoming_stock`` — merchant-entered expected restock per variant. The
   agent's "متوفر / خلص / هيتجدد" vocabulary needs a data source for the
   third word; inventory_balances answers the first two, this answers the
   restock date. Tenant-scoped with ENABLE + FORCE + tenant_isolation from
   day one, same as every agent-owned table.
2. ``ai_order_quotes`` drops — the confirmation flow (quotes + 6-digit code
   + create_order execution) was deliberately dormant with zero application
   callers, and the owner decision is to delete it rather than keep dead
   surface. The code lives in git history if the sales cycle returns.
3. Stale ``agent_tools`` rows for the removed/renamed customer tools are
   deleted. The runtime's registry authorization would refuse them anyway;
   the cleanup keeps the per-tenant tool lists honest.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "fe2026101712"
down_revision: str | None = "fe2026101711"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "incoming_stock",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            sa.Uuid(),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expected_on", sa.Date(), nullable=False),
        sa.Column("expected_qty", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.String(15), server_default="expected", nullable=False),
        sa.Column("status", sa.String(15), server_default="open", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
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
        "ix_incoming_stock_variant_status",
        "incoming_stock",
        ["tenant_id", "variant_id", "status"],
    )
    op.create_index("ix_incoming_stock_workspace_id", "incoming_stock", ["workspace_id"])
    op.create_index("ix_incoming_stock_location_id", "incoming_stock", ["location_id"])
    op.execute("ALTER TABLE incoming_stock ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE incoming_stock FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON incoming_stock")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON incoming_stock
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE incoming_stock TO sales_app;
          END IF;
        END
        $$"""
    )

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_order_quotes")
    op.drop_index("ix_ai_order_quotes_workspace_id", table_name="ai_order_quotes")
    op.drop_index("ix_ai_order_quotes_location_id", table_name="ai_order_quotes")
    op.drop_index(
        "ix_ai_order_quotes_conversation_status", table_name="ai_order_quotes"
    )
    op.drop_table("ai_order_quotes")

    op.execute(
        "DELETE FROM agent_tools WHERE name IN "
        "('search_products','get_variant_price','check_stock','create_order',"
        "'get_customer','get_order','add_task','add_tag','resolve_product_media')"
    )


def downgrade() -> None:
    # agent_tools rows are not resurrected — provisioning re-adds the names
    # it knows on the next sync.
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON incoming_stock")
    op.drop_table("incoming_stock")
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
    op.create_index("ix_ai_order_quotes_workspace_id", "ai_order_quotes", ["workspace_id"])
    op.create_index("ix_ai_order_quotes_location_id", "ai_order_quotes", ["location_id"])
    op.execute("ALTER TABLE ai_order_quotes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_order_quotes FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON ai_order_quotes
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )
