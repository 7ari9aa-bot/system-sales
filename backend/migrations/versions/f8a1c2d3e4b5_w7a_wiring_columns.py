"""w7a wiring: canonical message model, conversation lifecycle, integrations health

Revision ID: f8a1c2d3e4b5
Revises: 6cd2037d7891
Create Date: 2026-09-19

Hand-authored (W7a agent altered the DB to unblock DB-backed tests; this file
makes the change reproducible).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f8a1c2d3e4b5"
down_revision: str | None = "6cd2037d7891"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("content_type", sa.String(length=31), server_default="text", nullable=False),
    )
    op.add_column(
        "messages",
        sa.Column("reply_to_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("edited", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "messages",
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "messages",
        sa.Column("provider_metadata", postgresql.JSONB(), server_default="{}", nullable=False),
    )
    op.create_index("ix_messages_tenant_reply_to", "messages", ["tenant_id", "reply_to_message_id"])
    op.create_foreign_key(
        "fk_messages_reply_to_messages",
        "messages",
        "messages",
        ["reply_to_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("conversations", "status", type_=sa.String(length=31))
    op.add_column(
        "integrations",
        sa.Column("webhook_health", postgresql.JSONB(), server_default="{}", nullable=False),
    )
    op.execute("UPDATE integrations SET status = 'active' WHERE status = 'connected'")
    op.execute("UPDATE conversations SET status = 'open' WHERE status = 'pending'")


def downgrade() -> None:
    op.drop_column("integrations", "webhook_health")
    op.alter_column("conversations", "status", type_=sa.String(length=15))
    op.drop_index("ix_messages_tenant_reply_to", table_name="messages")
    op.drop_constraint("fk_messages_reply_to_messages", "messages", type_="foreignkey")
    op.drop_column("messages", "provider_metadata")
    op.drop_column("messages", "deleted")
    op.drop_column("messages", "edited")
    op.drop_column("messages", "reply_to_message_id")
    op.drop_column("messages", "content_type")
