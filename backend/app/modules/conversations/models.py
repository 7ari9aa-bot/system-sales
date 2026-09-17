"""CONVERSATIONS domain models — conversations, messages, assignments, ai_sessions.

All tables are tenant-scoped (TenantMixin first) so RLS policies and sharding
conventions apply uniformly. Cross-module FKs reference tenants.id, users.id and
customers.id only; the AI module owns the agents table, so ai_sessions.agent_id
is a plain UUID without a ForeignKey by design.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import AppendOnlyCreatedAtMixin, TenantMixin, TimestampMixin


class Conversation(TenantMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "ix_conversations_tenant_status_last",
            "tenant_id",
            "status",
            "last_message_at",
        ),
        Index("ix_conversations_tenant_customer", "tenant_id", "customer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    # channel: whatsapp | instagram | messenger | telegram | webchat
    channel: Mapped[str] = mapped_column(String(31), nullable=False)
    # status: open | pending | closed
    status: Mapped[str] = mapped_column(
        String(15), nullable=False, default="open", server_default="open"
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unread_count: Mapped[int] = mapped_column(default=0, server_default="0")
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Message(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "channel_message_id",
            name="uq_messages_tenant_channel_message_id",
        ),
        Index(
            "ix_messages_tenant_conversation_created",
            "tenant_id",
            "conversation_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # direction: inbound | outbound
    direction: Mapped[str] = mapped_column(String(15), nullable=False)
    # sender_type: customer | agent | ai | system
    sender_type: Mapped[str] = mapped_column(String(15), nullable=False)
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Provider message id; unique per tenant for ingest idempotency.
    channel_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(31), nullable=True)
    # Normalized provider payload.
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    # status: received | queued | sent | delivered | read | failed
    status: Mapped[str] = mapped_column(
        String(15), nullable=False, default="received", server_default="received"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Assignment(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # status: active | released
    status: Mapped[str] = mapped_column(
        String(15), nullable=False, default="active", server_default="active"
    )


class AISession(TenantMixin, TimestampMixin, Base):
    __tablename__ = "ai_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # AI module owns the agents table — no ForeignKey here by design.
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    model: Mapped[str | None] = mapped_column(String(127), nullable=True)
    context: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    token_usage: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
