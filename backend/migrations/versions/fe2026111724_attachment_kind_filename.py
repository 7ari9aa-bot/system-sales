"""What an outbound file IS and what it is called, on the attachment.

An agent can send the same WebP as a photo or as a sticker, and a document needs
a name the customer sees. Neither can be recovered from the MIME type, so they
are stored on the row instead of guessed later. Both are NULL for inbound media
and for every attachment that existed before this migration.

Revision ID: fe2026111724
Revises: fe2026111723
Create Date: 2026-11-17 07:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026111724"
down_revision: str | None = "fe2026111723"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # image | sticker | audio | video | document
    op.add_column("attachments", sa.Column("kind", sa.String(15), nullable=True))
    op.add_column("attachments", sa.Column("filename", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("attachments", "filename")
    op.drop_column("attachments", "kind")
