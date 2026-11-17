"""Store-wide list state on a conversation: pinned, muted, archived, marked unread.

WhatsApp lets a person pin a chat to the top, mute it, archive it and mark it
unread. In the inbox these are shared by the whole store (one flag per
conversation), so every staff member sees the same list. They are only flags
on the row: nothing here is sent to WhatsApp, because the Cloud API has no
such concept.

Revision ID: fe2026111723
Revises: fe2026111701
Create Date: 2026-11-17 06:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026111723"
down_revision: str | None = "fe2026111701"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True))
    # NULL = not muted; a timestamp = muted until then; the far-future value
    # the API writes for "always" is handled in the service, not here.
    op.add_column("conversations", sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("conversations", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("marked_unread", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # The pinned strip is read on every first page; keep it index-only.
    op.create_index(
        "ix_conversations_tenant_pinned",
        "conversations",
        ["tenant_id", "pinned_at"],
        postgresql_where=sa.text("pinned_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_tenant_pinned", table_name="conversations")
    op.drop_column("conversations", "marked_unread")
    op.drop_column("conversations", "archived_at")
    op.drop_column("conversations", "muted_until")
    op.drop_column("conversations", "pinned_at")
