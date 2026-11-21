"""a shop keeps its own size sets and colours as data.

Revision ID: fe2026112011
Revises: fe2026112010
Create Date: 2026-11-21 05:00:00.000000

Two new tenant tables, each created with row-level security in this same migration (the boot
reconciler refuses to start a service whose tenant table lacks it, and CI hides that by running
provision.py afterwards, so it must not be left to provision). Both are empty for every shop until
an owner saves a list, and a shop with no rows is shown the built-in lists, so nothing changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112011"
down_revision: str | None = "fe2026112010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_TABLES = ("shop_size_sets", "shop_colours")


def _rls(table: str) -> None:
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
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO sales_app;
          END IF;
        END
        $$"""
    )


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "shop_size_sets",
        *_base_columns(),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("sizes", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_shop_size_sets_tenant_name"),
    )
    op.create_table(
        "shop_colours",
        *_base_columns(),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("hex", sa.String(7), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_shop_colours_tenant_name"),
    )
    for table in _TABLES:
        _rls(table)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
