"""MARKETING domain models — campaigns, ad sets, ads, touchpoints, leads,
conversions, attribution."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
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


class Campaign(TenantMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    # allowed: facebook | google | tiktok | snapchat | manual
    provider: Mapped[str] = mapped_column(String(31))
    external_id: Mapped[str | None] = mapped_column(String(127))
    objective: Mapped[str | None] = mapped_column(String(63))
    # allowed: draft | active | paused | ended
    status: Mapped[str] = mapped_column(String(15), server_default="draft")
    budget: Mapped[float | None] = mapped_column(MONEY)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "external_id", name="uq_campaigns_provider_id"),
        Index("ix_campaigns_tenant_status", "tenant_id", "status"),
    )


class AdSet(TenantMixin, TimestampMixin, Base):
    __tablename__ = "ad_sets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(31))
    external_id: Mapped[str | None] = mapped_column(String(127))
    status: Mapped[str] = mapped_column(String(15), server_default="draft")
    budget: Mapped[float | None] = mapped_column(MONEY)
    targeting: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (Index("ix_ad_sets_tenant_campaign", "tenant_id", "campaign_id"),)


class Ad(TenantMixin, TimestampMixin, Base):
    __tablename__ = "ads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ad_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ad_sets.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(31))
    external_id: Mapped[str | None] = mapped_column(String(127))
    creative: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(String(15), server_default="draft")

    __table_args__ = (Index("ix_ads_tenant_adset", "tenant_id", "ad_set_id"),)


class Touchpoint(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    """A marketing contact point: ad click / UTM visit / channel entry."""

    __tablename__ = "touchpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL")
    )
    source: Mapped[str | None] = mapped_column(String(63))   # utm_source
    medium: Mapped[str | None] = mapped_column(String(63))   # utm_medium
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL")
    )
    ad_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ad_sets.id", ondelete="SET NULL")
    )
    ad_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ads.id", ondelete="SET NULL")
    )
    click_id: Mapped[str | None] = mapped_column(String(255))  # fbclid/gclid/ttclid
    landing_url: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    session_key: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index(
            "ix_touchpoints_tenant_customer_created", "tenant_id", "customer_id", "created_at"
        ),
        Index("ix_touchpoints_tenant_click", "tenant_id", "click_id"),
    )


class Lead(TenantMixin, TimestampMixin, Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL")
    )
    name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(31))
    email: Mapped[str | None] = mapped_column(String(320))
    source: Mapped[str | None] = mapped_column(String(63))
    # allowed: new | contacted | qualified | converted | lost
    status: Mapped[str] = mapped_column(String(15), server_default="new")
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL")
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    extra: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (Index("ix_leads_tenant_status", "tenant_id", "status"),)


class Conversion(TenantMixin, TimestampMixin, Base):
    __tablename__ = "conversions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL")
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL")
    )
    # allowed: purchase | signup | lead | custom
    type: Mapped[str] = mapped_column(String(31), server_default="purchase")
    value: Mapped[float | None] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), server_default="EGP")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    touchpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("touchpoints.id", ondelete="SET NULL")
    )

    __table_args__ = (
        Index("ix_conversions_tenant_customer", "tenant_id", "customer_id"),
    )


class Attribution(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    """Credited value of a touchpoint for a conversion under a given model."""

    __tablename__ = "attributions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversions.id", ondelete="CASCADE")
    )
    touchpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("touchpoints.id", ondelete="CASCADE")
    )
    # allowed: first_touch | last_touch | linear | time_decay | position_based
    model: Mapped[str] = mapped_column(String(31))
    weight: Mapped[float] = mapped_column(Numeric(5, 4), server_default="1")
    credited_value: Mapped[float | None] = mapped_column(MONEY)

    __table_args__ = (
        Index("ix_attributions_tenant_conversion", "tenant_id", "conversion_id"),
    )
