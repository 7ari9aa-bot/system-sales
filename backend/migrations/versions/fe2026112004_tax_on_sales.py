"""taxation: tax class on a product, tax snapshot on an order and its lines.

Revision ID: fe2026112004
Revises: fe2026112003
Create Date: 2026-11-20 10:00:00.000000

Additive and inert: every column is nullable or defaults to 0, so a shop that is not VAT-registered
and every order that predates this migration read exactly as before. ``orders.tax_included`` is
tax that sits INSIDE the prices and is never added to grand_total.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112004"
down_revision: str | None = "fe2026112003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("tax_class_id", sa.Uuid(), nullable=True))
    op.add_column(
        "orders",
        sa.Column("tax_included", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "order_items",
        sa.Column("tax_rate", sa.Numeric(6, 4), nullable=False, server_default="0"),
    )
    op.add_column(
        "order_items",
        sa.Column("tax_included", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.create_check_constraint("ck_orders_tax_included_nonneg", "orders", "tax_included >= 0")
    op.create_check_constraint(
        "ck_order_items_tax_nonneg", "order_items", "tax_included >= 0 AND tax_rate >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_order_items_tax_nonneg", "order_items", type_="check")
    op.drop_constraint("ck_orders_tax_included_nonneg", "orders", type_="check")
    op.drop_column("order_items", "tax_included")
    op.drop_column("order_items", "tax_rate")
    op.drop_column("orders", "tax_included")
    op.drop_column("products", "tax_class_id")
