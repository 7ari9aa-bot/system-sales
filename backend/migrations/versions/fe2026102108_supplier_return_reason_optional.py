"""purchasing: a supplier return no longer records a reason.

Revision ID: fe2026102108
Revises: fe2026102107
Create Date: 2026-10-21 13:00:00.000000

Nobody in the shop has time to write why goods go back, so the field is retired. The column stays
(nullable) so returns already on file keep what was recorded; new returns leave it empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026102108"
down_revision: str | None = "fe2026102107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("supplier_returns", "reason", existing_type=sa.String(31), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE supplier_returns SET reason = 'surplus' WHERE reason IS NULL")
    op.alter_column("supplier_returns", "reason", existing_type=sa.String(31), nullable=False)
