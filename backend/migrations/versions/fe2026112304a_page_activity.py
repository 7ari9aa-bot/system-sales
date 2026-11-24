"""``page_activity``: the Page's event feed, and the read mark that used to live in one browser.

The Facebook notifications screen rebuilt itself from the post list and kept its read mark in
``localStorage``, so a new/edited/deleted post, a reaction or a video produced nothing, a mention
stayed invisible, and one staff member reading a notification left it unread on every other
device. This table is the durable feed the webhook writes and the screen reads.

Revision ID: fe2026112304a
Revises: fe2026112303
Create Date: 2026-11-23 18:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112304a"
down_revision: str | None = "fe2026112303"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "page_activity",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(length=31), nullable=False),
        sa.Column("kind", sa.String(length=31), nullable=False),
        sa.Column("object_id", sa.String(length=127), nullable=False),
        sa.Column("parent_id", sa.String(length=127), nullable=True),
        sa.Column("actor_name", sa.String(length=255), nullable=True),
        sa.Column("actor_id", sa.String(length=127), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "dedup_key", name="uq_page_activity_tenant_dedup"),
    )
    op.create_index(
        "ix_page_activity_tenant_channel_time",
        "page_activity",
        ["tenant_id", "channel", "occurred_at"],
    )
    op.create_index(
        "ix_page_activity_tenant_unread", "page_activity", ["tenant_id", "channel", "read_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_page_activity_tenant_unread", table_name="page_activity")
    op.drop_index("ix_page_activity_tenant_channel_time", table_name="page_activity")
    op.drop_table("page_activity")
