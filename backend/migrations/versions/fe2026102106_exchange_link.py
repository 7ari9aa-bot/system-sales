"""pos: a stored link from an exchange's new sale receipt to its return receipt.

Revision ID: fe2026102106
Revises: fe2026102105
Create Date: 2026-10-21 11:00:00.000000

An exchange is two receipts issued in one transaction: a ``return`` receipt for what came back and
a ``sale`` receipt for what went out. Until now the only thing tying them together was an outbox
event, so the exchange log could not tell an exchange from a return plus an unrelated sale.

``exchange_return_receipt_id`` is set on the NEW SALE receipt and points at its return receipt.
Receipts are append-only, so it is written at insert and never changed. NULL = an ordinary sale (and
every exchange made before this migration, which stay a return plus a sale: nothing is guessed).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026102106"
down_revision: str | None = "fe2026102105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pos_receipts",
        sa.Column("exchange_return_receipt_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_pos_receipts_exchange_return",
        "pos_receipts",
        "pos_receipts",
        ["exchange_return_receipt_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # Only a sale receipt can carry the link, and never to itself.
    op.create_check_constraint(
        "ck_pos_receipts_exchange_link_on_sale",
        "pos_receipts",
        "exchange_return_receipt_id IS NULL "
        "OR (kind = 'sale' AND exchange_return_receipt_id <> id)",
    )
    # One return receipt belongs to at most one exchange.
    op.create_index(
        "uq_pos_receipts_exchange_return",
        "pos_receipts",
        ["tenant_id", "exchange_return_receipt_id"],
        unique=True,
        postgresql_where=sa.text("exchange_return_receipt_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_pos_receipts_exchange_return", table_name="pos_receipts")
    op.drop_constraint("ck_pos_receipts_exchange_link_on_sale", "pos_receipts", type_="check")
    op.drop_constraint("fk_pos_receipts_exchange_return", "pos_receipts", type_="foreignkey")
    op.drop_column("pos_receipts", "exchange_return_receipt_id")
