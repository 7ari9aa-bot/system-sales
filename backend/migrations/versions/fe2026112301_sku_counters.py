"""one atomic SKU counter per shop, so a number is never handed out twice.

Revision ID: fe2026112301
Revises: fe2026112015
Create Date: 2026-11-23 03:00:00.000000

Additive and inert: a new table that nothing reads until the add-product screen asks for the next
number. Existing shops keep their numbering: the first allocation seeds the counter from the
highest SKU-<number> already in the catalog, so nobody's next product jumps backwards.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112301"
down_revision: str | None = "fe2026112015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "sku_counters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("last_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", name="uq_sku_counters_tenant"),
    )
    op.create_index("ix_sku_counters_tenant_id", "sku_counters", ["tenant_id"])
    op.execute("ALTER TABLE sku_counters ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sku_counters FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON sku_counters
        USING (tenant_id = {_TENANT_GUARD})
        WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )


def downgrade() -> None:
    op.drop_index("ix_sku_counters_tenant_id", table_name="sku_counters")
    op.drop_table("sku_counters")
