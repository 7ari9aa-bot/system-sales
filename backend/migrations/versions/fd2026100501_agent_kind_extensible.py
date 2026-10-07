"""Add kind to Agent model to support extensible multi-agent architecture.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "fd2026100501"
down_revision: str | None = "fd2026100412"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add kind column with default 'customer' to existing rows.
    op.add_column('agents', sa.Column('kind', sa.String(length=63), server_default='customer', nullable=False))


def downgrade() -> None:
    op.drop_column('agents', 'kind')
