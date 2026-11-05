"""A profile picture for the account itself.

Revision ID: fe2026110502
Revises: fe2026110501

`users` is global (one person can belong to several workspaces), so the picture
is stored on the account, not per tenant. The column keeps an OBJECT KEY
(`s3://avatars/<user>/<file>`), never a read URL: signed URLs expire, and a
stored one would quietly break every avatar the day its lifetime ends.

No new grants: this adds a column to a table `sales_app` already owns access to.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026110502"
down_revision: str | None = "fe2026110501"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
