"""w7a wiring backfills: integrations status + conversation status normalization

Revision ID: f8a1c2d3e4b5
Revises: 6cd2037d7891
Create Date: 2026-09-19

The DDL of this wave (canonical message columns, integrations.webhook_health,
conversations.status width) is applied by 6cd2037d7891 — an earlier revision of
this file re-applied it and broke fresh `alembic upgrade head` runs with
"duplicate column". Only the data backfills remain here.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f8a1c2d3e4b5"
down_revision: str | None = "6cd2037d7891"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE integrations SET status = 'active' WHERE status = 'connected'")
    op.execute("UPDATE conversations SET status = 'open' WHERE status = 'pending'")


def downgrade() -> None:
    # Original states are not recoverable (the legacy values were normalized);
    # these updates only restore the historical default strings.
    op.execute("UPDATE integrations SET status = 'connected' WHERE status = 'active'")
    op.execute("UPDATE conversations SET status = 'pending' WHERE status = 'open'")
