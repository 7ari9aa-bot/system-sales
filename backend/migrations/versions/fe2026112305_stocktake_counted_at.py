"""A counted line remembers WHEN it was counted, so a sale during the count is not counted twice.

The bug: ``approve`` compared the counted figure against ``expected_qty``, the book quantity
snapshotted when the count STARTED, then moved the difference on whatever the balance was at
approval time. In a shop that keeps selling while the sheet is being filled (which is every
clothing shop on a Saturday), that double-counts every sale made in between:

    book at start 10 → one dress sold → counter counts 9 → approve moves 9 - 10 = -1 → book 8.

The dress left once and was subtracted twice.

With ``counted_at`` the line knows the moment its figure was true, so approval can rebuild the
book quantity AT THAT MOMENT (balance now minus everything that moved after the count) and the
difference becomes the real discrepancy: 9 - 9 = 0, nothing moves.

Revision ID: fe2026112305
Revises: fe2026112304
Create Date: 2026-11-23 22:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112305"
down_revision: str | None = "fe2026112304"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stocktake_lines",
        sa.Column("counted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Approving a count reads "what moved after this line was counted", per variant.
    op.create_index(
        "ix_stocktake_lines_counted_at",
        "stocktake_lines",
        ["tenant_id", "counted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_stocktake_lines_counted_at", table_name="stocktake_lines")
    op.drop_column("stocktake_lines", "counted_at")
