"""The book quantity AT THE COUNT, recorded on the line instead of rebuilt from timestamps.

``counted_at`` says when a line was counted, but rebuilding the book quantity from it means
comparing a Python clock against ``inventory_movements.created_at``, and rows written in one
transaction share a single ``now()``. Two clocks, one comparison: a sale and its count can look
simultaneous and the reconciliation silently falls back to the start snapshot — the very
double-count the previous migration set out to remove.

So the book quantity is measured ONCE, when the figure is taken, and stored: the same read the
counter's screen shows. Approval then compares like with like, with no clock involved.

Revision ID: fe2026112306
Revises: fe2026112305
Create Date: 2026-11-23 23:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112306"
down_revision: str | None = "fe2026112305"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stocktake_lines",
        sa.Column("counted_book_qty", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stocktake_lines", "counted_book_qty")
