"""The two tables a voice session needs to survive a worker restart.

A live call is held in memory by the media worker, but nothing about it may live ONLY there: the
control plane has to answer "what is this session, whose shop, which persona, which agent version,
and what did it already do" after the worker that started it is gone. These rows are that answer.

Only two tables are added on purpose. Calls, call legs, phone numbers, recordings, chat threads and
conversations already exist in this schema; a voice session points at them instead of copying them,
so the same conversation can move between text and voice without a second identity.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class VoiceSessionRow(Base):
    """One live voice session: who, which shop, which persona, which version, in what state."""

    __tablename__ = "voice_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    principal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    persona: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    authentication_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The scopes the session was issued with, frozen. A tool call re-checks them against this row
    # so a permission revoked mid-call stops working on the next turn (invariant 7).
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(24), nullable=False, default="v1")
    provider_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    client_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_completed_turn: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    close_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # A phone that retries the same key must find the open session, not open a second one.
        Index(
            "ux_voice_sessions_client_key",
            "tenant_id",
            "client_key",
            unique=True,
            postgresql_where=sa.text("client_key IS NOT NULL"),
        ),
        Index("ix_voice_sessions_tenant_state", "tenant_id", "state"),
        Index("ix_voice_sessions_trace", "trace_id"),
    )


class VoiceTurnRow(Base):
    """One turn of a session: what was heard, what was asked of the domain, what was said.

    The transcript itself is stored by reference (``transcript_ref``) so a turn row never becomes a
    second copy of the conversation, and a turn that was interrupted keeps its reason: an answer
    the caller never heard must not be replayed as if it were the answer to their next question.
    """

    __tablename__ = "voice_turns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voice_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    input_modality: Mapped[str | None] = mapped_column(String(16), nullable=True)
    output_modality: Mapped[str | None] = mapped_column(String(16), nullable=True)
    transcript_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tool_calls: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    latency_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    completion_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    interruption_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ux_voice_turns_session_sequence", "session_id", "sequence_number", unique=True),
        Index("ix_voice_turns_tenant", "tenant_id"),
    )
