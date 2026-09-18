"""PLATFORM domain models — system plumbing.

outbox_events and idempotency_keys are system tables (no tenant_id): they are
drained by the relay/ingestion layer across tenants and stay outside RLS.
audit_logs is tenant-scoped with a nullable tenant for platform-level actions.
webhook_events is a system-ingress table (inbound provider webhooks): its
tenant_id is a plain nullable column resolved after signature verification,
and it stays outside RLS.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import (
    AppendOnlyCreatedAtMixin,
    TenantMixin,
    TimestampMixin,
)


class OutboxEvent(Base):
    """Durable event staging — written in the same transaction as the change."""

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    aggregate_type: Mapped[str] = mapped_column(String(63))  # e.g. "order"
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    stream: Mapped[str] = mapped_column(String(127))
    payload: Mapped[dict] = mapped_column(JSONB)
    meta: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # allowed: pending | publishing | published | failed
    status: Mapped[str] = mapped_column(String(15), server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_outbox_status_created", "status", "created_at"),)


class IdempotencyKey(Base):
    """Deduplication for external webhook/callback deliveries."""

    __tablename__ = "idempotency_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scope: Mapped[str] = mapped_column(String(63))  # e.g. "webhook:whatsapp"
    key: Mapped[str] = mapped_column(String(255))  # provider event/message id
    request_hash: Mapped[str | None] = mapped_column(String(128))
    response: Mapped[dict | None] = mapped_column(JSONB)
    # allowed: processed | failed
    status: Mapped[str] = mapped_column(String(15), server_default="processed")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),)


class AuditLog(Base):
    """Append-only action history. tenant_id is nullable for platform-level actions."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(127))  # e.g. "order.created"
    resource_type: Mapped[str] = mapped_column(String(63))
    resource_id: Mapped[str] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_audit_tenant_created", "tenant_id", "created_at"),)


class Integration(TenantMixin, TimestampMixin, Base):
    __tablename__ = "integrations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(63))  # whatsapp | gmail | sheets | ...
    kind: Mapped[str] = mapped_column(String(31))  # channel | oauth | api_key
    # allowed: connected | disconnected | error
    status: Mapped[str] = mapped_column(String(15), server_default="connected")
    config: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # NOTE: secrets land here only encrypted at rest (Stage 9 hardening).
    credentials: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", "kind", name="uq_integrations_tenant_provider_kind"
        ),
    )


class WebhookEndpoint(TenantMixin, TimestampMixin, Base):
    """Tenant-configured outbound webhooks (we call them, with signatures)."""

    __tablename__ = "webhooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    url: Mapped[str] = mapped_column(Text)
    secret: Mapped[str] = mapped_column(String(255))
    events: Mapped[list[str]] = mapped_column(ARRAY(String(127)))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class WebhookDelivery(TenantMixin, TimestampMixin, Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    webhook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhooks.id", ondelete="CASCADE"), index=True
    )
    event_name: Mapped[str] = mapped_column(String(127))
    payload: Mapped[dict] = mapped_column(JSONB)
    # allowed: queued | delivered | failed | dead
    status: Mapped[str] = mapped_column(String(15), server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    response_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(TenantMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(15))  # email | sms | push | inapp
    subject: Mapped[str | None] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text)
    # allowed: queued | sent | failed
    status: Mapped[str] = mapped_column(String(15), server_default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Automation(TenantMixin, TimestampMixin, Base):
    """Event-triggered automation definitions (executed by workers/n8n)."""

    __tablename__ = "automations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    trigger: Mapped[dict] = mapped_column(JSONB)  # {event, filters}
    actions: Mapped[list] = mapped_column(JSONB)  # ordered action list
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class WebhookEvent(Base):
    """Inbound webhook ingress (provider -> us) — every delivery lands here first.

    System table like outbox_events: rows are written before authentication, so
    tenant_id is a plain nullable column (resolved once the signature is
    verified) with no FK and the table stays outside RLS.
    """

    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(31))  # whatsapp | telegram | stripe | ...
    external_event_id: Mapped[str | None] = mapped_column(String(255))
    # plain column on purpose: no FK, no TenantMixin, no RLS (system ingress)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    signature_valid: Mapped[bool] = mapped_column(Boolean, server_default="false")
    payload: Mapped[dict] = mapped_column(JSONB)
    # allowed: pending | processing | processed | failed | dead
    processing_status: Mapped[str] = mapped_column(String(15), server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_webhook_events_provider_ext", "provider", "external_event_id"),
        Index("ix_webhook_events_status_created", "processing_status", "received_at"),
    )


class EventLog(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    """Spec §152: append-only durable event history — the replay source.
    The outbox is only a publication buffer and may be cleaned."""

    __tablename__ = "event_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(127))
    aggregate_type: Mapped[str] = mapped_column(String(63))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    aggregate_version: Mapped[int | None] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer, server_default="1")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    producer: Mapped[str] = mapped_column(String(63), server_default="core")
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    causation_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint("event_id", name="uq_event_log_event_id"),
        Index("ix_event_log_tenant_type_created", "tenant_id", "event_type", "created_at"),
        Index("ix_event_log_aggregate", "aggregate_type", "aggregate_id"),
    )


class ProcessedEvent(Base):
    """Spec §127: consumer inbox — unique (consumer_name, event_id) makes
    at-least-once delivery safe. Insert + effect in the SAME transaction."""

    __tablename__ = "processed_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    consumer_name: Mapped[str] = mapped_column(String(63))
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(15), server_default="done")
    result_reference: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        UniqueConstraint("consumer_name", "event_id", name="uq_processed_consumer_event"),
    )


class ScheduledJob(TenantMixin, TimestampMixin, Base):
    """Spec §154: durable scheduler — Redis is never the scheduler."""

    __tablename__ = "scheduled_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_type: Mapped[str] = mapped_column(String(63))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # allowed: queued | processing | completed | failed | retrying | cancelled
    status: Mapped[str] = mapped_column(String(15), server_default="queued")
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="5")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_scheduled_jobs_due", "status", "run_at"),
        UniqueConstraint("idempotency_key", name="uq_scheduled_jobs_idem"),
    )


class DeliveryAttempt(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    """Spec §129/§148: outbound provider call audit (per attempt)."""

    __tablename__ = "delivery_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE")
    )
    webhook_delivery_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_deliveries.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(31))
    # allowed: sending | sent | unknown | failed
    outcome: Mapped[str] = mapped_column(String(15))
    request_payload: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    response_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_delivery_attempts_message", "tenant_id", "message_id"),
    )


class InboundMessageDedupe(Base):
    """Spec §142: dedupe record separated from message retention lifecycle."""

    __tablename__ = "inbound_message_dedupe"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    channel_account_id: Mapped[str] = mapped_column(String(127))
    external_message_id: Mapped[str] = mapped_column(String(255))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "channel_account_id",
            "external_message_id",
            name="uq_inbound_dedupe",
        ),
    )


class SecurityEvent(AppendOnlyCreatedAtMixin, Base):
    """Spec §67: platform-level security events (separate from business audit)."""

    __tablename__ = "security_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # allowed: login_failure | role_changed | permission_changed | secret_rotated
    #        | api_key_created | webhook_changed | integration_connected
    #        | suspicious_activity | data_export | data_deletion | break_glass
    event_type: Mapped[str] = mapped_column(String(63))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    ip: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_security_events_type_created", "event_type", "created_at"),
    )


class SecretReference(TenantMixin, TimestampMixin, Base):
    """Spec §68: business tables hold REFERENCES only — secrets live in
    Supabase Vault behind SecretStorePort."""

    __tablename__ = "secret_references"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scope: Mapped[str] = mapped_column(String(63))  # tenant|workspace|system
    provider: Mapped[str] = mapped_column(String(31))
    vault_key: Mapped[str] = mapped_column(String(255))  # vault secret name
    # allowed: active | rotating | revoked
    status: Mapped[str] = mapped_column(String(15), server_default="active")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "scope", name="uq_secret_ref"),
    )


class FeatureFlag(TenantMixin, TimestampMixin, Base):
    """Spec §76: per-tenant/workspace/role feature flags (not authorization)."""

    __tablename__ = "feature_flags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    feature: Mapped[str] = mapped_column(String(127))  # e.g. voice.enabled
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    role_code: Mapped[str | None] = mapped_column(String(63))
    rollout_percent: Mapped[int] = mapped_column(Integer, server_default="0")

    __table_args__ = (
        UniqueConstraint("tenant_id", "feature", name="uq_feature_flags_tenant_feature"),
    )


class MetricDefinition(TenantMixin, TimestampMixin, Base):
    """Spec §167: one canonical definition per metric (Revenue, FRT...)."""

    __tablename__ = "metric_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(63))
    definition: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(63))
    filters: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    timezone_rule: Mapped[str | None] = mapped_column(String(63))
    currency_rule: Mapped[str | None] = mapped_column(String(15))
    refund_treatment: Mapped[str | None] = mapped_column(String(31))
    version: Mapped[int] = mapped_column(Integer, server_default="1")

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "version", name="uq_metric_defs"),
    )
