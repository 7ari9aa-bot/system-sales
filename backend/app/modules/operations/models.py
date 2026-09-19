"""OPERATIONS domain models (spec §46, §83) — tasks, SLA, business calendars."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
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
from app.core.model_kit import TenantMixin, TimestampMixin


class Task(TenantMixin, TimestampMixin, Base):
    """Spec §83: independent task entity — sources: human|ai|automation|system."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(Integer, server_default="2")  # 1 high 2 normal 3 low
    # allowed: todo | in_progress | done | cancelled
    status: Mapped[str] = mapped_column(String(15), server_default="todo")
    related_entity_type: Mapped[str | None] = mapped_column(String(63))
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(15), server_default="human")
    created_by: Mapped[str | None] = mapped_column(String(63))  # automation actor

    __table_args__ = (
        Index("ix_tasks_tenant_status_assignee", "tenant_id", "status", "assignee_user_id"),
        Index("ix_tasks_tenant_due", "tenant_id", "due_date"),
    )


class SLAPolicy(TenantMixin, TimestampMixin, Base):
    """Spec §46: first-response/resolution targets, business-hours aware."""

    __tablename__ = "sla_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    name: Mapped[str] = mapped_column(String(255))
    first_response_minutes: Mapped[int] = mapped_column(Integer, server_default="60")
    resolution_minutes: Mapped[int] = mapped_column(Integer, server_default="1440")
    applies_to_channel: Mapped[str | None] = mapped_column(String(31))
    is_default: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # allowed: active | paused
    status: Mapped[str] = mapped_column(String(15), server_default="active")

    __table_args__ = (
        Index("ix_sla_policies_tenant", "tenant_id", "status"),
    )


class BusinessCalendar(TenantMixin, TimestampMixin, Base):
    """Spec §46: business hours + holidays per tenant/workspace/location.

    hours: JSONB — {"mon": [["09:00","17:00"]], "sun": null, ...} (null = closed)
    holidays: JSONB — ["2026-04-25", ...]
    """

    __tablename__ = "business_calendars"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    name: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(63), server_default="Africa/Cairo")
    hours: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    holidays: Mapped[list] = mapped_column(JSONB, server_default="[]")
    is_default: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (
        Index("ix_calendars_tenant", "tenant_id", "is_default"),
    )


class SLAEvent(TenantMixin, TimestampMixin, Base):
    """SLA clock events for conversations — breach detection by worker."""

    __tablename__ = "sla_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE")
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sla_policies.id", ondelete="SET NULL")
    )
    # allowed: first_response | resolution
    kind: Mapped[str] = mapped_column(String(31))
    # allowed: running | met | breached | paused
    status: Mapped[str] = mapped_column(String(15), server_default="running")
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    met_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_sla_events_tenant_status_deadline",
            "tenant_id",
            "status",
            "deadline_at",
        ),
    )
