"""``social_posts.shares_count``: the share counter Meta already returns for a Page post.

The Facebook sync asked Meta for ``shares`` but had nowhere to keep it, so the Share counter on the
Posts page was always 0. One additive, defaulted column: no backfill is needed (the next sync fills
it), existing rows read 0, and the column is safe to add on a live table.

Revision ID: fe2026112013
Revises: fe2026112012
Create Date: 2026-11-21 12:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112013"
down_revision: str | None = "fe2026112012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "social_posts",
        sa.Column("shares_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("social_posts", "shares_count")
