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
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import (
    AppendOnlyCreatedAtMixin,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    WorkspaceScopeMixin,
)


class Warehouse(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    __tablename__ = "warehouses"

    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(31))
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_warehouses_tenant_code"),)


class InventoryBalance(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
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


class InventoryMovement(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base):
    """Append-only stock ledger — one row per stock change."""

    __tablename__ = "inventory_movements"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    # allowed: in | out | adjust | hold | release
    #   in/out/adjust change `on_hand`; hold/release change `reserved` only.
    direction: Mapped[str] = mapped_column(String(15))
    quantity: Mapped[int] = mapped_column(Integer)
    # CLOSED vocabulary (M9), enforced by InventoryService.check_movement_shape
    # and by the request model — free text here made the ledger unreadable.
    # allowed: purchase | sale | return | return_reversal | transfer_in |
    # transfer_out | adjustment | damage | supplier_return | supplier_return_reversal |
    # reservation | reservation_release
    reason: Mapped[str] = mapped_column(String(63))
    reference_type: Mapped[str | None] = mapped_column(String(31), nullable=True)
    # polymorphic reference (e.g. order/transfer/reservation id) —
    # intentionally no FK: it points at rows of several kinds, including
    # `inventory_reservations` for a `reservation_release` row.
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Always the on-hand position after this row — unchanged on a hold/release
    # row, which moves availability, not stock.
    balance_after: Mapped[int] = mapped_column(Integer)
    # Total order within a ledger pair. created_at is the TRANSACTION time, so
    # rows written in one transaction share it and the uuid4 id is not an
    # order — without this sequence a ledger replay could reorder those rows
    # and invent a discrepancy that never happened (§181: a replayable ledger
    # needs a replay order).
    ledger_seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    # Who made the movement. NULL = unknown (rows from before this column) or a system actor.
    # No FK on purpose, like reference_id: the ledger is append-only, and ON DELETE SET NULL
    # would rewrite history rows when a user is removed.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_inv_mov_tenant_variant_created", "tenant_id", "variant_id", "created_at"),
        Index("ix_inv_mov_tenant_wh_created", "tenant_id", "warehouse_id", "created_at"),
        Index(
            "ix_inv_mov_tenant_actor_created",
            "tenant_id",
            "actor_user_id",
            "created_at",
            postgresql_where=text("actor_user_id IS NOT NULL"),
        ),
    )


class InventoryTransfer(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
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


class InventoryReservation(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """Durable stock reservation (spec §140).

    Created when stock is reserved for an order/cart. Expiry frees abandoned
    carts via the maintenance worker. Only ACTIVE reservations count against
    availability.
    """

    __tablename__ = "inventory_reservations"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL")
    )
    quantity: Mapped[int] = mapped_column(Integer, server_default="0")
    # The ledger row that took this hold (direction 'hold'). No FK on purpose:
    # the ledger is append-only and this is a pointer from the mutable side to
    # it, so that a hold written before the reservation row existed (Orders
    # reserves, then inserts the order, then registers the line) is still
    # reachable from `GET /inventory/movements?reservation_id=...`.
    hold_movement_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # allowed: ACTIVE | EXPIRED | CONVERTED | CANCELLED
    status: Mapped[str] = mapped_column(String(15), server_default="ACTIVE")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_inv_res_tenant_variant_status", "tenant_id", "variant_id", "status"),
        Index("ix_inv_res_status_expires", "status", "expires_at"),
    )


class InventoryReconciliationFinding(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
    """A ledger↔projection discrepancy, recorded — never silently fixed (§188).

    check = 'chain'      : a movement row's replayed position ≠ balance_after
                           (a forged or corrupted ledger row).
    check = 'projection' : the balance row drifted from the ledger's last
                           position (someone wrote the projection by hand).
    Resolution is operator work; the service moves OPEN → RESOLVED only.
    """

    __tablename__ = "inventory_reconciliation_findings"

    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="SET NULL"),
        nullable=True,
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="SET NULL"),
        nullable=True,
    )
    # allowed: chain | projection — named check_kind because `check` is a
    # reserved word that makes raw SQL over this table a quoting trap.
    check_kind: Mapped[str] = mapped_column(String(15))
    # For a chain finding: the offending ledger row. No FK on purpose — the
    # ledger is append-only history and the finding must outlive nothing of it.
    movement_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    expected: Mapped[int] = mapped_column(BigInteger)
    actual: Mapped[int] = mapped_column(BigInteger)
    # allowed: OPEN | RESOLVED
    status: Mapped[str] = mapped_column(String(15), server_default="OPEN")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_inv_rec_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
    )


class VariantStockSetting(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """The reorder level of ONE variant (a shop first: per variant, not per warehouse).

    0 means "no alert configured", so a variant nobody set up is never reported as running low.
    No row at all reads as 0. The ceiling is a sanity bound against a mistyped barcode scan
    landing in the field, not a business rule.
    """

    __tablename__ = "variant_stock_settings"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    reorder_level: Mapped[int] = mapped_column(Integer, server_default="0")

    __table_args__ = (
        UniqueConstraint("tenant_id", "variant_id", name="uq_variant_stock_settings_variant"),
        CheckConstraint(
            "reorder_level >= 0 AND reorder_level <= 1000000",
            name="ck_variant_stock_settings_level",
        ),
    )


class Stocktake(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """A physical count of one warehouse: OPEN while people count, then APPROVED or CANCELLED.

    Opening takes a SNAPSHOT of every line's book quantity (`expected_qty`) because the shop keeps
    selling while it is counted. Approving applies only the difference between what was counted and
    what the book said WHEN COUNTING STARTED, as a relative movement on today's balance, so a sale
    rung up during the count is never wiped out by a stale absolute figure.
    """

    __tablename__ = "stocktakes"

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    # allowed: OPEN | APPROVED | CANCELLED
    status: Mapped[str] = mapped_column(String(15), server_default="OPEN")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opened_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('OPEN', 'APPROVED', 'CANCELLED')", name="ck_stocktakes_status"),
        # A closed count says who closed it and when; an open one says neither.
        CheckConstraint(
            "(status = 'OPEN') = (closed_at IS NULL)",
            name="ck_stocktakes_closed_at",
        ),
        # One open count per warehouse: two people counting the same shelves would each "fix" the
        # other's figures.
        Index(
            "uq_stocktakes_one_open_per_warehouse",
            "tenant_id",
            "warehouse_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
    )


class StocktakeLine(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """One variant in a count: the book quantity at the start and what was counted.

    ``counted_qty`` NULL means "not counted yet", which is NOT zero: an uncounted line is never
    adjusted. ``applied_delta`` is what approval actually moved (counted - expected), kept on the
    line as the audit of what this count changed.
    """

    __tablename__ = "stocktake_lines"

    stocktake_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stocktakes.id", ondelete="CASCADE")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    expected_qty: Mapped[int] = mapped_column(Integer)
    counted_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("stocktake_id", "variant_id", name="uq_stocktake_lines_variant"),
        CheckConstraint("expected_qty >= 0", name="ck_stocktake_lines_expected"),
        CheckConstraint(
            "counted_qty IS NULL OR (counted_qty >= 0 AND counted_qty <= 1000000)",
            name="ck_stocktake_lines_counted",
        ),
        Index("ix_stocktake_lines_stocktake", "stocktake_id"),
    )
