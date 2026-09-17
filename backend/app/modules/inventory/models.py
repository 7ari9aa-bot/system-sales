"""INVENTORY domain models — warehouses, balances, movements, transfers.

inventory_movements is the append-only ledger of stock changes;
inventory_balances holds the current per-warehouse position per variant.
Stock is tracked against product_variants (catalog domain, same metadata).
Enum-like columns are String with allowed values documented inline — never
sa.Enum (avoids PG ENUM migration churn).
"""

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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import (
    AppendOnlyCreatedAtMixin,
    IdMixin,
    TenantMixin,
    TimestampMixin,
)


class Warehouse(TenantMixin, TimestampMixin, IdMixin, Base):
    __tablename__ = "warehouses"

    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(31))
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_warehouses_tenant_code"),)


class InventoryBalance(TenantMixin, TimestampMixin, IdMixin, Base):
    """Current stock position per (warehouse, variant)."""

    __tablename__ = "inventory_balances"

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    on_hand: Mapped[int] = mapped_column(Integer, server_default="0")
    reserved: Mapped[int] = mapped_column(Integer, server_default="0")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "warehouse_id",
            "variant_id",
            name="uq_inventory_balances_tenant_wh_variant",
        ),
    )


class InventoryMovement(TenantMixin, AppendOnlyCreatedAtMixin, IdMixin, Base):
    """Append-only stock ledger — one row per stock change."""

    __tablename__ = "inventory_movements"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    # allowed: in | out | adjust
    direction: Mapped[str] = mapped_column(String(15))
    quantity: Mapped[int] = mapped_column(Integer)
    # allowed: purchase | sale | return | transfer_in | transfer_out | adjustment | damage
    reason: Mapped[str] = mapped_column(String(63))
    reference_type: Mapped[str | None] = mapped_column(String(31), nullable=True)
    # polymorphic reference (e.g. order/transfer id) — intentionally no FK
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    balance_after: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_inv_mov_tenant_variant_created", "tenant_id", "variant_id", "created_at"),
        Index("ix_inv_mov_tenant_wh_created", "tenant_id", "warehouse_id", "created_at"),
    )


class InventoryTransfer(TenantMixin, TimestampMixin, IdMixin, Base):
    """Stock transfer between two warehouses of the same tenant."""

    __tablename__ = "inventory_transfers"

    from_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    to_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    # allowed: draft | in_transit | completed | cancelled
    status: Mapped[str] = mapped_column(String(15), server_default="draft")
    lines: Mapped[list] = mapped_column(JSONB, server_default="[]")  # [{variant_id, quantity}]
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
