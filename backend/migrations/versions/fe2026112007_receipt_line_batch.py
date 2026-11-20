"""a goods receipt line may name the batch the stock arrived in.

Revision ID: fe2026112007
Revises: fe2026112006
Create Date: 2026-11-20 15:00:00.000000

Additive and inert: both columns are nullable and nothing reads them unless a receipt line sends a
batch code, so every existing receipt and every shop that never sends one behaves exactly as before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112007"
down_revision: str | None = "fe2026112006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("goods_receipt_lines", sa.Column("lot_code", sa.String(64), nullable=True))
    op.add_column(
        "goods_receipt_lines",
        sa.Column("lot_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_gr_lines_expiry_needs_code",
        "goods_receipt_lines",
        "lot_expires_at IS NULL OR lot_code IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_gr_lines_expiry_needs_code", "goods_receipt_lines", type_="check")
    op.drop_column("goods_receipt_lines", "lot_expires_at")
    op.drop_column("goods_receipt_lines", "lot_code")
