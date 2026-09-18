"""CUSTOMERS domain models — customers, identities, addresses, tags, notes, events."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import (
    MONEY,
    AppendOnlyCreatedAtMixin,
    TenantMixin,
    TimestampMixin,
    VersionMixin,
)


class Customer(TenantMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(31))
    email: Mapped[str | None] = mapped_column(String(320))
    locale: Mapped[str | None] = mapped_column(String(15))
    is_blocked: Mapped[bool] = mapped_column(Boolean, server_default="false")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lifetime_value: Mapped[float] = mapped_column(MONEY, server_default="0")
    extra: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # §28 identity merge: canonical redirect when this customer was merged away
    merged_into_customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL")
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # §143 tombstones / soft delete
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    deletion_reason: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        UniqueConstraint("tenant_id", "phone", name="uq_customers_tenant_phone"),
        Index("ix_customers_tenant_name", "tenant_id", "name"),
        Index(
            "ix_customers_tenant_merged_into",
            "tenant_id",
            "merged_into_customer_id",
        ),
    )


class CustomerIdentity(TenantMixin, TimestampMixin, Base):
    """Maps a channel handle (e.g. WhatsApp wa_id) to a customer."""

    __tablename__ = "customer_identities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE")
    )
    # allowed: whatsapp | instagram | messenger | telegram | webchat
    channel: Mapped[str] = mapped_column(String(31))
    external_id: Mapped[str] = mapped_column(String(255))
    extra: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "channel", "external_id", name="uq_customer_identities_lookup"
        ),
        Index(
            "ix_customer_identities_tenant_customer", "tenant_id", "customer_id"
        ),
    )


class Address(TenantMixin, TimestampMixin, Base):
    __tablename__ = "addresses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE")
    )
    label: Mapped[str | None] = mapped_column(String(63))
    line1: Mapped[str] = mapped_column(String(255))
    line2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(127))
    region: Mapped[str | None] = mapped_column(String(127))
    postal_code: Mapped[str | None] = mapped_column(String(31))
    country: Mapped[str | None] = mapped_column(String(2))
    is_default: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (
        Index("ix_addresses_tenant_customer", "tenant_id", "customer_id"),
    )


class Tag(TenantMixin, TimestampMixin, Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(63))
    color: Mapped[str | None] = mapped_column(String(15))

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_tags_tenant_name"),)


customer_tags = Table(
    "customer_tags",
    Base.metadata,
    Column(
        "customer_id",
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Note(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE")
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("ix_notes_tenant_customer", "tenant_id", "customer_id"),)


class CustomerEvent(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    __tablename__ = "customer_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(63))
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        Index(
            "ix_customer_events_tenant_customer_created",
            "tenant_id",
            "customer_id",
            "created_at",
        ),
    )


class IdentityMergeCandidate(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    """Spec §27: candidate duplicate pairs awaiting resolution.

    Layer 3 (AI-assisted) creates candidates; humans decide (layer 4).
    """

    __tablename__ = "identity_merge_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE")
    )
    customer_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE")
    )
    # allowed: deterministic | verified | ai_suggested | manual
    match_type: Mapped[str] = mapped_column(String(31), server_default="ai_suggested")
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), server_default="0")
    # allowed: pending | merged | rejected | dismissed
    status: Mapped[str] = mapped_column(String(15), server_default="pending")
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "customer_a_id",
            "customer_b_id",
            name="uq_merge_candidates_pair",
        ),
        Index("ix_merge_candidates_tenant_status", "tenant_id", "status"),
    )


class IdentityMergeEvent(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    """Spec §28: audit trail of an executed merge (reversible reference)."""

    __tablename__ = "identity_merge_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    canonical_customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE")
    )
    merged_away_customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE")
    )
    performed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(31), server_default="human")
    details: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        Index(
            "ix_merge_events_tenant_canonical",
            "tenant_id",
            "canonical_customer_id",
        ),
    )
