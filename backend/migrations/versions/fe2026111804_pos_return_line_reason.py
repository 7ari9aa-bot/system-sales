"""pos_return_lines.reason: why the item came back.

Revision ID: fe2026111804
Revises: fe2026111803
Create Date: 2026-11-18 20:40:00.000000

WHY. A clothing shop's most useful number is which size comes back and why. The reason is chosen
by the cashier from the list the owner set in ``pos.return_reasons`` and saved on the returned
line. Nullable: every return made before this column has no reason, and a shop may leave the
choice optional.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026111804"
down_revision: str | None = "fe2026111803"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pos_return_lines", sa.Column("reason", sa.String(length=63), nullable=True))


def downgrade() -> None:
    op.drop_column("pos_return_lines", "reason")
