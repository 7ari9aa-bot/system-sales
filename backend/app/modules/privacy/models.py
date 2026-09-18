"""PRIVACY domain models — consent is first-class, per purpose + channel."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import (
    AppendOnlyCreatedAtMixin,
    TenantMixin,
    TimestampMixin,
    WorkspaceScopeMixin,
)


class Consent(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
    """Spec §32: NOT a boolean — scoped by channel + purpose, with proof."""

    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE")
    )
    channel: Mapped[str] = mapped_column(String(31))  # whatsapp | email | sms | push
    # allowed purposes: service_messages | marketing | ai_processing | analytics
    purpose: Mapped[str] = mapped_column(String(63))
    # allowed: granted | revoked | expired
    status: Mapped[str] = mapped_column(String(15), server_default="granted")
    source: Mapped[str | None] = mapped_column(String(63))  # widget | form | import
    proof: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_consents_tenant_customer_purpose", "tenant_id", "customer_id", "purpose"),
    )


class DataSubjectRequest(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """Spec §51: access/export/delete/rectify requests with full lifecycle."""

    __tablename__ = "data_subject_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE")
    )
    # allowed: access | export | delete | rectify
    request_type: Mapped[str] = mapped_column(String(15))
    # allowed: pending | in_progress | completed | rejected | failed
    status: Mapped[str] = mapped_column(String(15), server_default="pending")
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    payload_scope: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    result_ref: Mapped[str | None] = mapped_column(Text)  # export file key
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_dsr_tenant_status", "tenant_id", "status"),
    )


class RetentionPolicy(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """Spec §52: per data-class retention; executed by retention workers."""

    __tablename__ = "retention_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    data_class: Mapped[str] = mapped_column(String(63))  # messages|audit|ai_usage|...
    retention_days: Mapped[int] = mapped_column(default=365)
    # allowed: active | paused
    status: Mapped[str] = mapped_column(String(15), server_default="active")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_retention_policies_tenant_class", "tenant_id", "data_class"),
    )
