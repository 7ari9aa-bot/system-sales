"""Spec §36 — Voice advanced architecture models.

Entities for the full voice stack:
    Call        — top-level call record
    CallSession — one logical call session (IVR, AI voice, etc.)
    CallLeg     — a single leg of a call (inbound/outbound)
    PhoneNumber — tenant-owned phone numbers
    Recording   — call recording metadata
    IVRSession  — interactive voice response session state

Voice module can be activated as a separate capability without changing
the Messaging core (§36). These models are tenant-scoped and RLS-protected.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7
from app.core.model_kit import (
    AppendOnlyCreatedAtMixin,
    TenantMixin,
    TimestampMixin,
    WorkspaceScopeMixin,
)


class PhoneNumber(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """A tenant-owned phone number provisioned for voice."""

    __tablename__ = "phone_numbers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    number: Mapped[str] = mapped_column(String(31), nullable=False)
    # SIP trunk / provider reference
    provider: Mapped[str] = mapped_column(String(63))
    external_id: Mapped[str | None] = mapped_column(String(255))
    # allowed: available | in_use | provisioning | released
    status: Mapped[str] = mapped_column(String(15), server_default="available")
    capabilities: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        Index("ix_phone_numbers_tenant_status", "tenant_id", "status"),
    )


class Call(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """Top-level call record — one logical communication session."""

    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    phone_number_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id", ondelete="SET NULL")
    )
    # allowed: inbound | outbound
    direction: Mapped[str] = mapped_column(String(15))
    # allowed: ringing | answered | in_progress | completed | failed | no_answer
    status: Mapped[str] = mapped_column(String(20), server_default="ringing")
    # Customer-facing number (the number the customer dialed / was dialed)
    from_number: Mapped[str | None] = mapped_column(String(31))
    to_number: Mapped[str | None] = mapped_column(String(31))
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    # Provider-specific metadata
    provider_metadata: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        Index("ix_calls_tenant_status", "tenant_id", "status"),
        Index("ix_calls_tenant_customer", "tenant_id", "customer_id"),
    )


class CallSession(TenantMixin, TimestampMixin, Base):
    """A logical session within a call — IVR, AI voice, handover, etc.

    A call can have multiple sessions: e.g. IVR → AI voice → human handover.
    Each session has its own state and transcript.
    """

    __tablename__ = "call_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE")
    )
    # allowed: ivr | ai_voice | human | stt | tts
    session_type: Mapped[str] = mapped_column(String(15))
    # allowed: active | completed | failed | transferred
    status: Mapped[str] = mapped_column(String(15), server_default="active")
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # STT/TTS provider config used for this session
    config: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # AI agent reference if this is an ai_voice session
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        Index("ix_call_sessions_tenant_call", "tenant_id", "call_id"),
    )


class CallLeg(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    """A single leg of a call — the RTP/streaming connection.

    A call with a transfer has multiple legs. Each leg tracks the
    endpoint, codec, and stream metadata.
    """

    __tablename__ = "call_legs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE")
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("call_sessions.id", ondelete="SET NULL")
    )
    # allowed: inbound | outbound
    direction: Mapped[str] = mapped_column(String(15))
    # SIP/RTP endpoint
    endpoint: Mapped[str | None] = mapped_column(String(255))
    # WebRTC SDP if applicable
    sdp: Mapped[str | None] = mapped_column(Text)
    codec: Mapped[str | None] = mapped_column(String(63))
    # allowed: ringing | answered | active | terminated | failed
    status: Mapped[str] = mapped_column(String(15), server_default="ringing")
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_call_legs_tenant_call", "tenant_id", "call_id"),
    )


class Recording(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """Call recording metadata — audio is in object storage, not the DB."""

    __tablename__ = "call_recordings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE")
    )
    storage_key: Mapped[str] = mapped_column(String(255))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    # allowed: recording | recorded | transcribing | transcribed | failed
    status: Mapped[str] = mapped_column(String(20), server_default="recording")
    # Transcript reference (links to the Transcript entity in voice.py)
    transcript_id: Mapped[str | None] = mapped_column(String(255))
    # Consent: was the recording announced to the customer?
    consent_captured: Mapped[bool] = mapped_column(
        Boolean, server_default="false"
    )

    __table_args__ = (
        Index("ix_recordings_tenant_call", "tenant_id", "call_id"),
    )


class IVRSession(TenantMixin, TimestampMixin, Base):
    """IVR (Interactive Voice Response) session state.

    Tracks the menu navigation path, collected DTMF, and the decision
    tree path the caller took.
    """

    __tablename__ = "ivr_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE")
    )
    # The IVR menu tree reference
    menu_id: Mapped[str | None] = mapped_column(String(255))
    # Navigation path: [{node_id, dtmf_input, timestamp}]
    path: Mapped[list] = mapped_column(JSONB, server_default="[]")
    # Collected DTMF inputs
    collected_inputs: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # allowed: active | completed | timed_out | transferred
    status: Mapped[str] = mapped_column(String(15), server_default="active")
    # Where the IVR ended: {destination: "ai_voice" | "human" | "hangup"}
    outcome: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        Index("ix_ivr_sessions_tenant_call", "tenant_id", "call_id"),
    )
