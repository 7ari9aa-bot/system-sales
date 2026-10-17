"""Per-line discounts on order items (§189 — the ground-shop discount).

A ground-shop cashier discounts a SPECIFIC piece, types the percentage on
the till, and the line charges its net — no approval gate. The ladder price
stays on ``unit_price`` (price integrity: the catalog price is what it is);
the discount lives beside it and the line's ``total`` carries the net.

Revision ID: fe2026101507
Revises: fe2026101506
Create Date: 2026-10-16 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026101507"
down_revision: str | None = "fe2026101506"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column(
            "discount_pct",
            sa.Numeric(5, 2),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_order_items_discount_pct",
        "order_items",
        "discount_pct >= 0 AND discount_pct <= 100",
    )


def downgrade() -> None:
    op.drop_constraint("ck_order_items_discount_pct", "order_items", type_="check")
    op.drop_column("order_items", "discount_pct")
