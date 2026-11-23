"""``social_posts.insights``: a story's metrics, kept where the story lives.

Instagram delivers a story's numbers after it expires (webhook field ``story_insights``) and there
was nowhere to put them, so the metrics were parsed away. One nullable JSONB column: existing rows
read NULL, nothing is backfilled, and a story that never expires keeps NULL.

Revision ID: fe2026112303
Revises: fe2026112302
Create Date: 2026-11-23 08:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112303"
down_revision: str | None = "fe2026112302"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "social_posts", sa.Column("insights", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("social_posts", "insights")
