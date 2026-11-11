"""orders.external_ref: the id an outside storefront gave its own order.

Revision ID: fe2026111201
Revises: fe2026111101
Create Date: 2026-11-12 00:30:00.000000

A Fihrist Sites storefront posts its customer's order to Fihrist (phase 3 of the
integration). The network between the two can lose the reply, so the storefront
retries, and a retry must not reserve the stock and book the order a second time.

The storefront sends its own order id as ``external_ref``. This column stores it and the
partial unique index makes a second insert with the same (tenant, channel, ref) impossible
at the database, not just unlikely in the application. Rows without a ref (every order
created before this, and every order from the dashboard, POS or chat) are outside the
index, so nothing existing is touched and no backfill is needed.

SAFETY. Purely additive: a nullable column and a partial index over rows that do not exist
yet. The index uses ``IF NOT EXISTS``; the column is added once, as every Alembic revision does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026111201"
down_revision: str | None = "fe2026111101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Literal table and column names: tests/test_migrations.py reads them with an AST walk to prove
    # every model column is created by some migration.
    op.add_column("orders", sa.Column("external_ref", sa.String(80), nullable=True))
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_tenant_channel_external_ref "
        "ON orders (tenant_id, channel, external_ref) WHERE external_ref IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_orders_tenant_channel_external_ref")
    op.drop_column("orders", "external_ref")
