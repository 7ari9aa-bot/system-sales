"""A voided POS sale is its own document, not a deleted one.

The till could already cancel a sale that was still being built, but a CONFIRMED
sale had no reversal: a wrong size, a wrong price or a wrong colour was stuck in
the books, and the only workaround was a return, which is a different accounting
fact (the customer brought goods back) from a void (the sale never happened).

This migration lets ``pos_receipts.kind`` carry ``void`` so the reversal gets its
own ``POS-VOID-`` number series and its own row, pointing at the original sale
through ``order_id``. Nothing is ever deleted: the sale receipt stays, the
payments stay, the stock movements stay, and the void adds the reversing ones.

Revision ID: fe2026112304
Revises: fe2026112304a
Create Date: 2026-11-23 22:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "fe2026112304"
down_revision = "fe2026112304a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_pos_receipts_kind", "pos_receipts", type_="check")
    op.create_check_constraint(
        "ck_pos_receipts_kind", "pos_receipts", "kind IN ('sale', 'return', 'void')"
    )
    # A sale is voided at most once, and the lookup "was this sale voided" is by order.
    op.create_index(
        "uq_pos_receipts_one_void_per_order",
        "pos_receipts",
        ["tenant_id", "order_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'void'"),
    )


def downgrade() -> None:
    op.drop_index("uq_pos_receipts_one_void_per_order", table_name="pos_receipts")
    op.drop_constraint("ck_pos_receipts_kind", "pos_receipts", type_="check")
    op.create_check_constraint(
        "ck_pos_receipts_kind", "pos_receipts", "kind IN ('sale', 'return')"
    )
