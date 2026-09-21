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

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f1a2b3c4d5e6"
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

    # §166: notification_preferences table
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=15), nullable=False),
        sa.Column("enabled", sa.Boolean, server_default="true", nullable=False),
        sa.Column("quiet_hours_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quiet_hours_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "channel", name="uq_notif_prefs_user_channel"
        ),
    )
    op.create_index(
        "ix_notification_preferences_tenant", "notification_preferences", ["tenant_id"]
    )

    # §36: Voice Gateway — phone_numbers
    op.create_table(
        "phone_numbers",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=63), nullable=False),
        sa.Column("status", sa.String(length=15), server_default="pending", nullable=False),
        sa.Column("display_name", sa.String(length=127), nullable=True),
        sa.Column("voice_url", sa.Text(), nullable=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "number", name="uq_phone_numbers_tenant_number"),
    )

    # §36: Voice Gateway — calls
    op.create_table(
        "calls",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("phone_number_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("direction", sa.String(length=15), nullable=False),
        sa.Column("from_number", sa.String(length=20), nullable=False),
        sa.Column("to_number", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=15), server_default="ringing", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("provider_call_id", sa.String(length=255), nullable=True),
        sa.Column("recording_url", sa.Text(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("transcript_status", sa.String(length=15), nullable=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_calls_tenant_conversation", "calls", ["tenant_id", "conversation_id"])
    op.create_index("ix_calls_tenant_status", "calls", ["tenant_id", "status"])

    # §36: Voice Gateway — call_sessions
    op.create_table(
        "call_sessions",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("call_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("ivr_flow_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=15), server_default="active", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_call_sessions_tenant_call", "call_sessions", ["tenant_id", "call_id"])

    # §36: Voice Gateway — call_legs
    op.create_table(
        "call_legs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("call_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("leg_type", sa.String(length=15), nullable=False),
        sa.Column("from_number", sa.String(length=20), nullable=False),
        sa.Column("to_number", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=15), server_default="ringing", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("provider_leg_id", sa.String(length=255), nullable=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_call_legs_tenant_call", "call_legs", ["tenant_id", "call_id"])


def downgrade() -> None:
    # Voice Gateway tables
    op.drop_table("call_legs")
    op.drop_table("call_sessions")
    op.drop_table("calls")
    op.drop_table("phone_numbers")

    # Notification preferences
    op.drop_table("notification_preferences")

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
