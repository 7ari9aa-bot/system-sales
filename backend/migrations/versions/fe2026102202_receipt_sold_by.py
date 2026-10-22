"""pos: record who sold on the receipt.

Revision ID: fe2026102202
Revises: fe2026102201
Create Date: 2026-10-22 11:30:00.000000

A sale used to be tied to a cashier only through the shift it was rung on
(`pos_sessions.cashier_user_id`). The cashier layer no longer needs an open shift to sell, so
"who sold" has to live on the receipt itself.

`sold_by_user_id` is nullable: receipts already on file keep NULL (nobody is invented for them;
the shift still says who held the till). It deliberately has no foreign key, like
`inventory_movements.actor_user_id`: receipts are append-only, and a FK with ON DELETE SET NULL
would rewrite history rows when a user is removed. The app role's grants and the table's RLS
already cover a new column, so nothing else changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026102202"
down_revision: str | None = "fe2026102201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pos_receipts", sa.Column("sold_by_user_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_pos_receipts_tenant_sold_by",
        "pos_receipts",
        ["tenant_id", "sold_by_user_id", "issued_at"],
        postgresql_where=sa.text("sold_by_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_pos_receipts_tenant_sold_by", table_name="pos_receipts")
    op.drop_column("pos_receipts", "sold_by_user_id")
