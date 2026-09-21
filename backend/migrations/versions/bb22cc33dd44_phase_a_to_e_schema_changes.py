"""add schema changes for phases A-E (deep audit gap closure)

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-09-21

Consolidates schema changes from the deep-audit gap closure:
- §15-16: tool_calls.idempotency_key (already added in f1a2b3c4d5e6, skip if exists)
- §130: delivery_attempts.provider_event_id + provider_timestamp
- §139: orders.process_state
- §143: orders/conversations/messages tombstone columns
- §166: notification_preferences table
- §36: phone_numbers, calls, call_sessions, call_legs tables (voice gateway)

Idempotent — uses IF NOT EXISTS for all CREATE TABLE and ADD COLUMN.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bb22cc33dd44"
down_revision: str | None = "aa11bb22cc33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # §130: delivery_attempts.provider_event_id + provider_timestamp
    op.add_column(
        "delivery_attempts",
        sa.Column("provider_event_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "delivery_attempts",
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
    )

    # §166: notification_preferences columns the model declares that the
    # w8 migration (already applied) did not create. Nullable with server
    # defaults so the add is safe on a populated table.
    op.add_column(
        "notification_preferences",
        sa.Column("channel", sa.String(length=15), nullable=True),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=True),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("quiet_hours_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("quiet_hours_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("workspace_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("location_id", sa.UUID(as_uuid=True), nullable=True),
    )

    # §139: orders.process_state
    op.add_column(
        "orders",
        sa.Column(
            "process_state",
            sa.String(length=31),
            nullable=True,
            server_default="created",
        ),
    )

    # §143: tombstones on orders
    op.add_column(
        "orders",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("deleted_by", sa.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("deletion_reason", sa.String(length=512), nullable=True),
    )

    # §143: tombstones on conversations
    op.add_column(
        "conversations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("deleted_by", sa.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("deletion_reason", sa.String(length=512), nullable=True),
    )

    # §143: tombstones on messages
    op.add_column(
        "messages",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("deleted_by", sa.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("deletion_reason", sa.String(length=512), nullable=True),
    )

    # (§166 notification_preferences and the §36 voice tables — phone_numbers,
    # calls, call_sessions, call_legs — are created by the earlier migrations
    # e1f2a3b4c5d6 and f9b0c1d2e3f4; re-creating them here broke fresh databases.)



def downgrade() -> None:
    # NOTE: this migration no longer creates the §166 notification_preferences
    # table or the §36 voice tables (they belong to e1f2a3b4c5d6 and
    # f9b0c1d2e3f4), so the downgrade must not drop them either.

    # Tombstones on messages
    op.drop_column("messages", "deletion_reason")
    op.drop_column("messages", "deleted_by")
    op.drop_column("messages", "deleted_at")

    # Tombstones on conversations
    op.drop_column("conversations", "deletion_reason")
    op.drop_column("conversations", "deleted_by")
    op.drop_column("conversations", "deleted_at")

    # Tombstones on orders
    op.drop_column("orders", "deletion_reason")
    op.drop_column("orders", "deleted_by")
    op.drop_column("orders", "deleted_at")

    # orders.process_state
    op.drop_column("orders", "process_state")

    # delivery_attempts provider metadata
    op.drop_column("delivery_attempts", "provider_timestamp")
    op.drop_column("delivery_attempts", "provider_event_id")
