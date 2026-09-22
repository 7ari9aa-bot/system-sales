"""workflows.version — optimistic-concurrency column for §17 conditional writes

Revision ID: d170cc170dd0
Revises: c166dd166dd1
Create Date: 2026-09-22

The workflow row is mutated by the status PATCH and by ``current_version``
bumps on publish, yet had no CAS token: two concurrent writers silently
clobbered each other. Mirrors the W1 pattern (``b8befbde56e7``) that added
``version`` to customers/orders/campaigns/agents/refunds. Distinct from
``current_version``, which is the definition-snapshot number, not a row
concurrency counter.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d170cc170dd0"
down_revision: str | None = "c166dd166dd1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("workflows", "version")
