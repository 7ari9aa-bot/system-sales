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
from app.core.model_kit import (
    AppendOnlyCreatedAtMixin,
    TenantMixin,
    TimestampMixin,
    WorkspaceScopeMixin,
)

# §156 lifecycle states — String values, never sa.Enum (migration-friendly).
CONVERSATION_STATUSES = frozenset(
    {"open", "waiting_customer", "waiting_human", "waiting_ai", "paused", "closed"}
)
# Legacy alias: rows (and API calls) written before §156 may carry "pending";
# it normalizes to "open" wherever the service reads or sets status.
CONVERSATION_STATUS_ALIASES = {"pending": "open"}


def normalize_conversation_status(status: str) -> str:
    """Map legacy 'pending' to 'open'; pass canonical values through."""
    return CONVERSATION_STATUS_ALIASES.get(status, status)


class Conversation(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "ix_conversations_tenant_status_last",
            "tenant_id",
            "status",
            "last_message_at",
        ),
        Index("ix_conversations_tenant_customer", "tenant_id", "customer_id"),
        # At most one open conversation per (tenant, customer, channel) —
        # prevents the select-then-insert duplicate-conversation race.
        Index(
            "uq_conversations_open_tenant_customer_channel",
            "tenant_id",
            "customer_id",
            "channel",
            unique=True,
            postgresql_where=text("status <> 'closed'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    # channel: whatsapp | instagram | messenger | telegram | webchat
    channel: Mapped[str] = mapped_column(String(31), nullable=False)
    # status (§156): open | waiting_customer | waiting_human | waiting_ai
    #              | paused | closed
    # legacy: "pending" is accepted as an alias of "open" on read/write
    # (normalize_conversation_status); the pre-§156 migration maps existing
    # 'pending' rows to 'open'. Width 31 fits the longest value.
    status: Mapped[str] = mapped_column(
        String(31), nullable=False, default="open", server_default="open"
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # §30: the anchor for the channel's customer-service window. Distinct from
    # last_message_at, which also moves on OUTBOUND messages and therefore
    # cannot answer "when did the customer last write to us?".
    last_customer_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # §30: standing messaging state (open | template_only | ...). Kept so the
    # UI and the policy engine read the same value.
    messaging_policy_state: Mapped[str] = mapped_column(
        String(31), nullable=False, server_default="open"
    )
    unread_count: Mapped[int] = mapped_column(default=0, server_default="0")
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # §143: tombstone — soft-delete columns (privacy deletion).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Message(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
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
        Index(
            "ix_messages_tenant_reply_to",
            "tenant_id",
            "reply_to_message_id",
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
    # §155 canonical content kind — ONE column every surface reads:
    # text | image | voice | video | file | location | contact
    #    | buttons | list | reaction | unsupported
    content_type: Mapped[str] = mapped_column(
        String(31), nullable=False, default="text", server_default="text"
    )
    # §155 threading: the message this one replies to (self-FK, SET NULL).
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    # §155 edit/delete tombstones (UI renders "edited"/"deleted" placeholders).
    edited: Mapped[bool] = mapped_column(default=False, server_default="false")
    deleted: Mapped[bool] = mapped_column(default=False, server_default="false")
    # §155 provider-specific extras (wamid, button payloads, quick replies) —
    # kept OUT of body so the canonical columns stay clean.
    provider_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    # §31: set when this outbound message was sent AS an approved template
    # (the only legal way to reach a customer outside the service window).
    # Recorded so the policy decision is auditable after the fact.
    template_name: Mapped[str | None] = mapped_column(String(127), nullable=True)
    template_vars: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    # Normalized provider payload.
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    # status: received | queued | sending | sent | delivered | read
    #       | unknown (send result lost — reconciled via provider events)
    #       | failed
    status: Mapped[str] = mapped_column(
        String(15), nullable=False, default="received", server_default="received"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # §143: tombstone — soft-delete columns (privacy deletion).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Assignment(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
    """Conversation assignment history — who was assigned and when."""

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


class AISession(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
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


class MessageTemplate(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """Spec §31: first-class outbound template (WhatsApp HSM etc.).

    AI/Automation MUST reference an APPROVED template — never compose
    template-like content inline outside the 24h window.
    """

    __tablename__ = "message_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(127))
    # allowed: draft | submitted | approved | rejected | paused | archived
    status: Mapped[str] = mapped_column(String(15), server_default="draft")
    language: Mapped[str] = mapped_column(String(15), server_default="ar")
    body_text: Mapped[str] = mapped_column(Text)
    variables: Mapped[list] = mapped_column(JSONB, server_default="[]")
    provider: Mapped[str] = mapped_column(String(31), server_default="whatsapp")
    provider_template_id: Mapped[str | None] = mapped_column(String(127))
    version: Mapped[int] = mapped_column(default=1)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "language", name="uq_templates_tenant_name_lang"),
        Index("ix_templates_tenant_status", "tenant_id", "status"),
    )


class TemplateApproval(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
    __tablename__ = "template_approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message_templates.id", ondelete="CASCADE")
    )
    # allowed: submitted | approved | rejected
    status: Mapped[str] = mapped_column(String(15), server_default="submitted")
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(63))  # provider or staff


class Attachment(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
    """Spec §33-34: durable media object — provider URLs are never the
    source of truth. scan/processing pipeline lands in the media worker."""

    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE")
    )
    storage_key: Mapped[str | None] = mapped_column(String(512))  # our S3 key
    provider_url: Mapped[str | None] = mapped_column(Text)  # expiring original
    mime_type: Mapped[str | None] = mapped_column(String(127))
    size: Mapped[int | None] = mapped_column()
    checksum: Mapped[str | None] = mapped_column(String(128))
    width: Mapped[int | None] = mapped_column()
    height: Mapped[int | None] = mapped_column()
    duration: Mapped[int | None] = mapped_column()  # seconds (audio/video)
    # allowed: pending | downloading | stored | scanned | failed
    scan_status: Mapped[str] = mapped_column(String(15), server_default="pending")
    # allowed: pending | processing | ready | failed
    processing_status: Mapped[str] = mapped_column(String(15), server_default="pending")
    # audio: spec §35
    transcription_status: Mapped[str | None] = mapped_column(String(15))
    transcript_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # §35: the transcript text itself. `transcript_id` is a pointer for a future
    # transcripts table; until that table exists the text has to live here or
    # the transcription is paid for and lost.
    transcript_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(15))

    __table_args__ = (
        Index("ix_attachments_tenant_message", "tenant_id", "message_id"),
        Index("ix_attachments_tenant_conversation", "tenant_id", "conversation_id"),
    )


# ------------------------------------------- §36 Voice Gateway ----


class PhoneNumber(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """§36: a phone number owned/rented by the tenant for voice calls.

    Routed to a conversation channel — inbound calls on this number
    open a CallSession linked to the conversation.
    """

    __tablename__ = "phone_numbers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # E.164 format: +9665XXXXXXXX
    number: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(31))  # twilio | vonage | ...
    # allowed: pending | active | released
    status: Mapped[str] = mapped_column(String(15), server_default="pending")
    display_name: Mapped[str | None] = mapped_column(String(127))
    # webhook config for inbound calls
    voice_url: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_phone_numbers_tenant_number"),
    )


class Call(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """§36: a voice call (inbound or outbound).

    A call may have multiple legs (transfers, forwarding). The call
    itself is the top-level entity; legs track individual connections.
    """

    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    phone_number_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id", ondelete="SET NULL"), nullable=True
    )
    direction: Mapped[str] = mapped_column(String(15))  # inbound | outbound
    from_number: Mapped[str] = mapped_column(String(20))
    to_number: Mapped[str] = mapped_column(String(20))
    # allowed: ringing | in_progress | completed | failed | no_answer | busy
    status: Mapped[str] = mapped_column(String(15), server_default="ringing")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column()
    provider_call_id: Mapped[str | None] = mapped_column(String(255))  # provider's call id
    # recording + transcript (durable — §33-35)
    recording_url: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    transcript_status: Mapped[str | None] = mapped_column(String(15))  # pending | ready | failed

    __table_args__ = (
        Index("ix_calls_tenant_conversation", "tenant_id", "conversation_id"),
        Index("ix_calls_tenant_status", "tenant_id", "status"),
    )


class CallSession(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """§36: an AI or IVR session within a call.

    A call may have multiple sessions (e.g., IVR menu → agent handoff).
    Each session tracks the AI agent or IVR flow that handled it.
    """

    __tablename__ = "call_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    # AI agent or IVR flow that handled this segment
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # AI module owns agents
    ivr_flow_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # allowed: active | completed | failed | transferred
    status: Mapped[str] = mapped_column(String(15), server_default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_call_sessions_tenant_call", "tenant_id", "call_id"),)


class CallLeg(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
    """§36: a single leg of a call (one endpoint connection).

    A call with a transfer has 2+ legs. Each leg tracks the individual
    connection's start/end, direction, and outcome.
    """

    __tablename__ = "call_legs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    # allowed: inbound | outbound | transfer
    leg_type: Mapped[str] = mapped_column(String(15))
    from_number: Mapped[str] = mapped_column(String(20))
    to_number: Mapped[str] = mapped_column(String(20))
    # allowed: ringing | answered | completed | failed | no_answer | busy
    status: Mapped[str] = mapped_column(String(15), server_default="ringing")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column()
    provider_leg_id: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (Index("ix_call_legs_tenant_call", "tenant_id", "call_id"),)
