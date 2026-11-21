"""``social_comments.page_liked``: whether the connected Page itself liked the comment.

Meta's Comment node has ``user_likes`` (bool, "whether the viewer has liked this comment"); with a Page
token the viewer is the Page. The sync asked for ``like_count`` only, so the Like button always started
un-pressed after a reload. One additive, defaulted column: existing rows read false until the next sync
fills it, and the column is safe to add on a live table.

Revision ID: fe2026112014
Revises: fe2026112013
Create Date: 2026-11-21 14:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112014"
down_revision: str | None = "fe2026112013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "social_comments",
        sa.Column("page_liked", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("social_comments", "page_liked")
