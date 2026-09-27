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
    WorkspaceScopeMixin,
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
    # Durable retry scheduling: the relay skips rows until this instant, so
    # workers can stage a backoff retry as an outbox row instead of sleeping
    # in-process (a process death then loses nothing).
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    # §66 lineage — copied from request-scoped contextvars by AuditService at
    # write time (NULL outside a request/event scope): source is the actor
    # kind (§66 vocabulary: "human" | "ai" | "automation" | "system" |
    # "integration"), request_id links the row to
    # the HTTP request / bus event, correlation_id links it across services.
    source: Mapped[str | None] = mapped_column(String(63))
    request_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_tenant_request", "tenant_id", "request_id"),
    )


class Integration(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    __tablename__ = "integrations"

    # §145: channel account lifecycle — allowed transitions.
    _LIFECYCLE_TRANSITIONS: dict[str, set[str]] = {
        "pending": {"connecting", "disabled"},
        "connecting": {"active", "reauth_required", "disabled"},
        "active": {"reauth_required", "restricted", "disconnected", "disabled"},
        "reauth_required": {"connecting", "active", "disabled"},
        "restricted": {"active", "disconnected", "disabled"},
        "disconnected": {"connecting", "disabled"},
        "disabled": set(),  # terminal
    }

    @classmethod
    def validate_transition(cls, from_status: str, to_status: str) -> None:
        """§145: raise if the transition is not in the allowed set."""
        allowed = cls._LIFECYCLE_TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            raise ValueError(
                f"illegal channel account transition: {from_status} -> {to_status}"
            )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(63))  # whatsapp | gmail | sheets | ...
    kind: Mapped[str] = mapped_column(String(31))  # channel | oauth | api_key
    # allowed (§145 lifecycle): pending | connecting | active
    #        | reauth_required | restricted | disconnected | disabled
    # legacy: pre-§145 rows carry 'connected' (and 'error'); the migration
    # maps 'connected' -> 'active' and 'error' -> 'reauth_required'.
    # The default is 'pending' now that the ingest gateway resolves tenants
    # through public.resolve_channel_tenant (which accepts both 'active' and
    # the legacy 'connected'): 'connected' is no longer a valid lifecycle
    # value, so new rows must not be born with it.
    status: Mapped[str] = mapped_column(String(15), server_default="pending")
    config: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # NOTE: secrets land here only encrypted at rest (Stage 9 hardening).
    credentials: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # §145: rolling webhook health (last webhook at, consecutive failures,
    # last error) — consumed by the integration health surface.
    webhook_health: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", "kind", name="uq_integrations_tenant_provider_kind"
        ),
    )


class WebhookEndpoint(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """Tenant-configured outbound webhooks (we call them, with signatures)."""

    __tablename__ = "webhooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    url: Mapped[str] = mapped_column(Text)
    secret: Mapped[str] = mapped_column(String(255))
    events: Mapped[list[str]] = mapped_column(ARRAY(String(127)))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class WebhookDelivery(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
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


class Notification(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    # channel: email | sms | push | inapp
    channel: Mapped[str] = mapped_column(String(15), server_default="inapp")
    kind: Mapped[str] = mapped_column(String(31), server_default="system")
    title: Mapped[str | None] = mapped_column(String(127), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    action_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # allowed: queued | sent | failed
    status: Mapped[str] = mapped_column(String(15), server_default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(127), nullable=True)


class NotificationPreference(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """§166: per-user notification channel preferences + quiet hours.

    A row per (tenant, user, channel). `enabled` defaults True; the
    dispatcher checks this before sending. `quiet_hours_start/end` are
    nullable Time fields; when both are set and the current time falls
    within the window, the channel is suppressed.
    """

    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # channel: email | sms | whatsapp | push
    channel: Mapped[str] = mapped_column(String(15), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)
    quiet_hours_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    quiet_hours_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "channel", name="uq_notif_prefs_user_channel"
        ),
    )


class Automation(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
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


# §24: the closed vocabulary of webhook_events.processing_status (column is a
# plain String — the application is the type system here, so the set is named).
WEBHOOK_EVENT_STATUSES: frozenset[str] = frozenset(
    {"pending", "processing", "processed", "failed", "dead", "ignored", "resolved"}
)


class WebhookEvent(Base):
    """Inbound webhook ingress (provider -> us) — every delivery lands here first.

    tenant_id is a plain nullable column (resolved once the signature is
    verified) with no FK. The table is FORCE RLS with the strict
    tenant_isolation policy (migration d5e6f7a8b9c0), so every ingress write
    binds the tenant GUC first (see the webhook router).
    """

    __tablename__ = "webhook_events"

    # §24 DLQ lifecycle — the only values processing_status may take:
    # pending → processing → processed, or → failed (budget left, the sweep
    # re-runs it) → dead (budget spent — human hands only: replay/ignore/
    # resolve). ignored/resolved are the terminal DLQ close-outs; the row is
    # NEVER deleted — nothing disappears (§24).
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
    # allowed: WEBHOOK_EVENT_STATUSES (§24, defined next to the class above)
    processing_status: Mapped[str] = mapped_column(String(15), server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_webhook_events_provider_ext", "provider", "external_event_id"),
        Index("ix_webhook_events_status_created", "processing_status", "received_at"),
    )


class EventLog(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
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
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    effect_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("event_id", name="uq_event_log_event_id"),
        Index("ix_event_log_tenant_type_created", "tenant_id", "event_type", "created_at"),
        Index("ix_event_log_aggregate", "aggregate_type", "aggregate_id"),
        Index("ix_event_log_decision_id", "decision_id"),
        Index("ix_event_log_effect_id", "effect_id"),
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


class ScheduledJob(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
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


class DeliveryAttempt(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
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
    # §130: provider event metadata — the provider's event id and the
    # timestamp it reported for the delivery receipt.
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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


class SecretReference(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
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


class SecretValue(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    """§68: the actual secret values behind SecretStorePort's database adapter.

    SecretReference holds the business metadata (provider, status); THIS table
    holds the values, one row per version, encrypted by EnvelopeSecretStore
    (AES-256-GCM, ``v1:`` wire format) so the column never carries plaintext.
    Rows are immutable: rotation expires the live rows (§69 grace) and inserts
    a new version; reads serve the newest non-expired version.
    """

    __tablename__ = "secret_values"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    vault_key: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer)
    ciphertext: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "vault_key", "version", name="uq_secret_values_key_version"
        ),
        Index("ix_secret_values_tenant_key", "tenant_id", "vault_key"),
    )


class FeatureFlag(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
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


class MetricDefinition(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
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


class Job(TenantMixin, TimestampMixin, Base):
    """Spec §84: the user-facing record of a long-running operation.

    This is deliberately NOT ``ScheduledJob`` (above). ``scheduled_jobs`` is
    the scheduler's internal wake-up list: ``run_at``, ``next_attempt_at`` and
    ``idempotency_key`` exist so the scheduler loop can decide *when* to run
    something. A Job answers a different question — "what did the user start,
    how far did it get, what did it produce, and can I retry or cancel it?" —
    so it carries ``progress``, ``result``, ``correlation_id`` and
    ``actor_user_id`` instead of scheduling columns. Publishing
    ``scheduled_jobs`` as the public Job API would leak the scheduler's retry
    machinery (and its nullable tenant story) into the UI.

    This table is the durable record and the control surface only. There is no
    runner here: a worker executes a job and writes status back. Building a
    runner into the request path would tie a long operation to the request
    lifetime — the exact failure this table exists to make visible.
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kind: Mapped[str] = mapped_column(String(63))  # e.g. "import.customers"
    # allowed: queued | processing | completed | failed | retrying | cancelled
    status: Mapped[str] = mapped_column(String(15), server_default="queued")
    progress: Mapped[int] = mapped_column(Integer, server_default="0")  # 0-100
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="3")
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        Index("ix_jobs_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_jobs_tenant_kind", "tenant_id", "kind"),
    )


class SavedView(TenantMixin, TimestampMixin, Base):
    """Spec §95: a named list layout — filters/sort/columns/grouping/density.

    Lives in platform because it is a cross-cutting UI concern: every entity
    list (customers, orders, inbox) saves into the same shape, and the
    visibility rules are the same for all of them.
    """

    __tablename__ = "saved_views"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    entity: Mapped[str] = mapped_column(String(63))  # customers | orders | inbox
    # filters / sort / columns / grouping / density — opaque to the server,
    # which stores and returns it but never interprets it.
    definition: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # allowed: private | team | workspace
    visibility: Mapped[str] = mapped_column(String(15), server_default="private")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (Index("ix_saved_views_tenant_entity", "tenant_id", "entity"),)


class TenantServiceToken(TenantMixin, TimestampMixin, Base):
    """§136: per-tenant service credential for the n8n adapter.

    Replaces the single global SERVICE_TOKEN_INTERNAL Bearer, which let any
    tenant's automation act as any other tenant. Only the sha256 hex digest
    of the presented token is stored — the plaintext is returned exactly
    once at issuance and never persisted. Lives in platform alongside
    Integration (the other tenant-credential model).
    """

    __tablename__ = "tenant_service_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(127))  # human label, e.g. "n8n-outbound"
    token_hash: Mapped[str] = mapped_column(String(64))  # sha256 hex — never plaintext
    scopes: Mapped[list] = mapped_column(JSONB, server_default="[]")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_service_tokens.id", ondelete="SET NULL"),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("uq_tenant_service_tokens_hash", "token_hash", unique=True),)
