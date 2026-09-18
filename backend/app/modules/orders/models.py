"""ORDERS domain models — orders, items, status history, shipments, payments, refunds."""

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


class Order(TenantMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    number: Mapped[str] = mapped_column(String(31))
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE")
    )
    # allowed: draft | pending | confirmed | processing | shipped | delivered
    #        | completed | cancelled | refunded
    status: Mapped[str] = mapped_column(String(31), server_default="pending")
    currency: Mapped[str] = mapped_column(String(3), server_default="EGP")
    subtotal: Mapped[float] = mapped_column(MONEY, server_default="0")
    discount_total: Mapped[float] = mapped_column(MONEY, server_default="0")
    shipping_total: Mapped[float] = mapped_column(MONEY, server_default="0")
    tax_total: Mapped[float] = mapped_column(MONEY, server_default="0")
    grand_total: Mapped[float] = mapped_column(MONEY, server_default="0")
    # allowed: whatsapp | instagram | messenger | telegram | webchat | dashboard
    channel: Mapped[str | None] = mapped_column(String(31))
    shipping_address: Mapped[dict | None] = mapped_column(JSONB)
    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_orders_tenant_number"),
        Index("ix_orders_tenant_status_placed", "tenant_id", "status", "placed_at"),
        Index("ix_orders_tenant_customer", "tenant_id", "customer_id"),
    )


class OrderItem(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    """Line item snapshot at purchase time (title/sku frozen from the variant)."""

    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    title: Mapped[str] = mapped_column(String(255))  # snapshot at purchase
    sku: Mapped[str | None] = mapped_column(String(63))  # snapshot
    quantity: Mapped[int] = mapped_column()
    unit_price: Mapped[float] = mapped_column(MONEY)
    total: Mapped[float] = mapped_column(MONEY)

    __table_args__ = (
        Index("ix_order_items_tenant_order", "tenant_id", "order_id"),
    )


class OrderStatusHistory(TenantMixin, AppendOnlyCreatedAtMixin, Base):
    __tablename__ = "order_status_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE")
    )
    from_status: Mapped[str | None] = mapped_column(String(31))
    to_status: Mapped[str] = mapped_column(String(31))
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(String(512))

    __table_args__ = (
        Index("ix_order_history_tenant_order", "tenant_id", "order_id"),
    )


class Shipment(TenantMixin, TimestampMixin, Base):
    __tablename__ = "shipments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE")
    )
    carrier: Mapped[str | None] = mapped_column(String(63))
    tracking_number: Mapped[str | None] = mapped_column(String(127))
    # allowed: pending | picked_up | in_transit | delivered | returned | failed
    status: Mapped[str] = mapped_column(String(15), server_default="pending")
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    label_url: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_shipments_tenant_order", "tenant_id", "order_id"),
    )


class OrderPayment(TenantMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "order_payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE")
    )
    # allowed: cash | card | wallet | bank_transfer | cod | manual
    method: Mapped[str] = mapped_column(String(31))
    # allowed: pending | authorized | captured | failed | refunded
    #        | partially_refunded
    status: Mapped[str] = mapped_column(String(31), server_default="pending")
    amount: Mapped[float] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), server_default="EGP")
    provider: Mapped[str | None] = mapped_column(String(31))
    provider_ref: Mapped[str | None] = mapped_column(String(255))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_order_payments_tenant_order", "tenant_id", "order_id"),
    )


class Refund(TenantMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_payments.id", ondelete="CASCADE")
    )
    amount: Mapped[float] = mapped_column(MONEY)
    reason: Mapped[str | None] = mapped_column(Text)
    # allowed: pending | approved | processed | rejected
    status: Mapped[str] = mapped_column(String(15), server_default="pending")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        Index("ix_refunds_tenant_payment", "tenant_id", "payment_id"),
    )
