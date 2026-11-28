"""INVENTORY domain models — warehouses, balances, movements, transfers.

inventory_movements is the append-only ledger of stock changes;
inventory_balances holds the current per-warehouse position per variant.
Stock is tracked against product_variants (catalog domain, same metadata).
Enum-like columns are String with allowed values documented inline — never
sa.Enum (avoids PG ENUM migration churn).

The supply-chain tables that hang off the ledger follow three rules that the
whole program depends on:

* The balance grain NEVER changes: inventory_balances stays keyed on
  (tenant_id, warehouse_id, variant_id). Every new dimension (location, lot,
  serial, condition) lives in a side table beside it, never inside the key.
* Condition is a SUBSET COUNTER: `quarantined` counts units of the on-hand
  stock that are held for inspection, so sellable and available are DERIVED
  (on_hand - quarantined [- reserved]) and never stored a second time.
* A transfer is a DOCUMENT with a lifecycle, not two moves at once: the
  relational line tables are the truth, the old JSONB column is deprecated.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import (
    MONEY,
    AppendOnlyCreatedAtMixin,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    WorkspaceScopeMixin,
)

# Cost keeps 4 places, like purchasing's COST: an average of 10.00 and 12.00 over
# odd quantities is not a clean cent, and rounding every cost layer to 2 places
# at every receipt would drift. Totals shown to people are rounded once.
COST = Numeric(14, 4)


class Warehouse(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    __tablename__ = "warehouses"

    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(31))
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_warehouses_tenant_code"),)


class InventoryBalance(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """Current stock position per (warehouse, variant).

    `on_hand` keeps its meaning: the TOTAL physical stock of that variant at
    that warehouse. `quarantined` is the SUBSET of it held for inspection —
    units that are physically there but not sellable. Condition is a subset
    counter, never a second balance row (the grain of this table does not
    change), so the derived figures are:

        sellable  = on_hand - quarantined
        available = on_hand - quarantined - reserved

    Every reader of availability must subtract `quarantined`.
    """

    __tablename__ = "inventory_balances"

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    on_hand: Mapped[int] = mapped_column(Integer, server_default="0")
    reserved: Mapped[int] = mapped_column(Integer, server_default="0")
    # Units of `on_hand` that are held for inspection and are NOT sellable.
    quarantined: Mapped[int] = mapped_column(Integer, server_default="0")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "warehouse_id",
            "variant_id",
            name="uq_inventory_balances_tenant_wh_variant",
        ),
        CheckConstraint("quarantined >= 0", name="ck_inventory_balances_quarantined"),
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
    # opening_stock | reservation | reservation_release
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
    # The BOOK COST of the units this row moved, so a later FIFO or landed-cost
    # pass can value the movement without re-deriving it. NULL means "the cost
    # is unknown" (stock that pre-dates any recorded purchase) and is NEVER 0:
    # a zero cost would silently value stock at nothing.
    cost_value: Mapped[Decimal | None] = mapped_column(COST, nullable=True)

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
    """Stock transfer between two warehouses of the same tenant.

    A transfer is a DOCUMENT with a lifecycle, not two moves at once: shipping
    writes the `out` at the source and nothing at the destination, receiving
    writes the `in` at the destination. The goods in between are in transit and
    belong to neither shelf.

    allowed status values:
      draft | approved | picking | packed | in_transit | partially_received |
      completed | cancelled | exception

    DEPRECATED: `lines` (JSONB). It is kept only so rows written before the
    relational line tables existed still read back; the truth is
    `inventory_transfer_lines`.
    """

    __tablename__ = "inventory_transfers"

    from_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    to_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    # allowed: draft | approved | picking | packed | in_transit |
    #         partially_received | completed | cancelled | exception
    # (31 chars, not 15: `partially_received` is 18 characters long.)
    status: Mapped[str] = mapped_column(String(31), server_default="draft")
    # DEPRECATED: the JSONB line list is kept for backwards compatibility only.
    # The relational `inventory_transfer_lines` table is the truth.
    lines: Mapped[list] = mapped_column(JSONB, server_default="[]")  # [{variant_id, quantity}]
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Why the transfer was flagged (shortage, damage). Only meaningful in the
    # `exception` state, but kept nullable so the reason survives a move on.
    exception_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','approved','picking','packed','in_transit',"
            "'partially_received','completed','cancelled','exception')",
            name="ck_inventory_transfers_status",
        ),
    )


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

    A count is not always the whole warehouse: `kind` says which count this is
    (a cycle count of one aisle, a spot check of one product) and `scope` says
    WHAT the count covers (locations, products, categories). A `blind` count
    hides the book quantity from the counter, so the count cannot be anchored
    to it; `recount_threshold_pct` is the variance above which the count asks
    for a recount instead of adjusting the stock.
    """

    __tablename__ = "stocktakes"

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    # allowed: OPEN | APPROVED | CANCELLED
    status: Mapped[str] = mapped_column(String(15), server_default="OPEN")
    # allowed: full | cycle | blind | spot | abc
    kind: Mapped[str] = mapped_column(String(15), server_default="full")
    # What this count covers: locations / products / categories (a JSON list).
    scope: Mapped[list] = mapped_column(JSONB, server_default="[]")
    # A blind count must not show the book quantity to the counter.
    blind: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # A variance above this percentage asks for a recount instead of an adjustment.
    recount_threshold_pct: Mapped[int] = mapped_column(Integer, server_default="10")
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
        CheckConstraint(
            "kind IN ('full','cycle','blind','spot','abc')",
            name="ck_stocktakes_kind",
        ),
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
    line as the audit of what this count changed. ``recount_count`` says how many times the line
    was counted again after a variance above the count's recount threshold.
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
    # Who counted this line. NULL = unknown or a system actor.
    counted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # How many recounts this line has had (0 = counted once).
    recount_count: Mapped[int] = mapped_column(Integer, server_default="0")
    # WHEN this figure was true. The shop keeps selling while the sheet is filled, so approval
    # rebuilds the book quantity at this moment instead of comparing against the snapshot taken
    # when the count started — otherwise every sale during the count is subtracted twice.
    counted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The book quantity the counter was looking at when the figure was taken. Approval compares
    # the count against THIS, not against the snapshot from when the sheet was printed, so sales
    # made during the count are not subtracted twice.
    counted_book_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("stocktake_id", "variant_id", name="uq_stocktake_lines_variant"),
        CheckConstraint("expected_qty >= 0", name="ck_stocktake_lines_expected"),
        CheckConstraint(
            "counted_qty IS NULL OR (counted_qty >= 0 AND counted_qty <= 1000000)",
            name="ck_stocktake_lines_counted",
        ),
        CheckConstraint("recount_count >= 0", name="ck_stocktake_lines_recount_count"),
        Index("ix_stocktake_lines_stocktake", "stocktake_id"),
    )


# ---------------------------------------------------------------------------
# Transfers: the document and its relational lines (D6).
#
# A transfer travels: it is approved, picked, packed, shipped (which writes the
# `out` at the source and nothing at the destination), received in parts, and
# only then completed. Every step is a row here, so "what is still in transit"
# is a question about documents, not about a guess.
# ---------------------------------------------------------------------------


class InventoryTransferLine(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
    """One variant on a transfer document — the truth the JSONB column used to hold.

    `quantity` is what the document asks to move, `quantity_shipped` what left
    the source and `quantity_received` what arrived: the gap between them is
    the shortage the `exception` state records.
    """

    __tablename__ = "inventory_transfer_lines"

    transfer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_transfers.id", ondelete="CASCADE")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int] = mapped_column(Integer)
    quantity_shipped: Mapped[int] = mapped_column(Integer, server_default="0")
    quantity_received: Mapped[int] = mapped_column(Integer, server_default="0")
    # 1-based place on the document; created_at cannot order lines.
    position: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "transfer_id", "position", name="uq_inv_transfer_lines_position"
        ),
        UniqueConstraint(
            "tenant_id", "transfer_id", "variant_id", name="uq_inv_transfer_lines_variant"
        ),
        CheckConstraint("quantity > 0", name="ck_inv_transfer_lines_quantity"),
        CheckConstraint("quantity_shipped >= 0", name="ck_inv_transfer_lines_shipped"),
        CheckConstraint("quantity_received >= 0", name="ck_inv_transfer_lines_received"),
        CheckConstraint("position > 0", name="ck_inv_transfer_lines_position"),
        Index("ix_inv_transfer_lines_transfer", "tenant_id", "transfer_id"),
        Index("ix_inv_transfer_lines_variant", "tenant_id", "variant_id"),
    )


class InventoryTransferShipment(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """One despatch of a transfer — a transfer may travel in more than one box.

    Shipping is the moment the goods LEAVE the source: the `out` is written
    here and the destination learns nothing until the receipt.
    """

    __tablename__ = "inventory_transfer_shipments"

    transfer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_transfers.id", ondelete="CASCADE")
    )
    shipped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    shipped_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    carrier: Mapped[str | None] = mapped_column(String(63), nullable=True)
    tracking_ref: Mapped[str | None] = mapped_column(String(63), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_inv_transfer_shipments_transfer", "tenant_id", "transfer_id"),)


class InventoryTransferShipmentLine(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
    """What one shipment actually carried — a shipment may hold less than the line asked for."""

    __tablename__ = "inventory_transfer_shipment_lines"

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_transfer_shipments.id", ondelete="CASCADE")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "shipment_id", "position", name="uq_inv_transfer_shipment_lines_position"
        ),
        CheckConstraint("quantity > 0", name="ck_inv_transfer_shipment_lines_quantity"),
        CheckConstraint("position > 0", name="ck_inv_transfer_shipment_lines_position"),
        Index("ix_inv_transfer_shipment_lines_shipment", "tenant_id", "shipment_id"),
    )


class InventoryTransferReceipt(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """What arrived: receiving writes the `in` at the destination.

    A receipt may point at the shipment it closes, or at none (goods that
    arrived without a despatch record — a walk-in delivery).
    """

    __tablename__ = "inventory_transfer_receipts"

    transfer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_transfers.id", ondelete="CASCADE")
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_transfer_shipments.id", ondelete="CASCADE"),
        nullable=True,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    received_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_inv_transfer_receipts_transfer", "tenant_id", "transfer_id"),)


class InventoryTransferReceiptLine(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
    """One variant as it arrived — and in what condition.

    `condition` is what the receiver saw, not what the ledger stores: a short
    receipt is a shortage, a damaged receipt is damage. Both are facts about
    the DOCUMENT; the ledger rows they cause are written by the service.
    """

    __tablename__ = "inventory_transfer_receipt_lines"

    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_transfer_receipts.id", ondelete="CASCADE")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int] = mapped_column(Integer)
    # allowed: good | damaged | short
    condition: Mapped[str] = mapped_column(String(15), server_default="good")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_inv_transfer_receipt_lines_quantity"),
        CheckConstraint(
            "condition IN ('good','damaged','short')",
            name="ck_inv_transfer_receipt_lines_condition",
        ),
        Index("ix_inv_transfer_receipt_lines_receipt", "tenant_id", "receipt_id"),
    )


# ---------------------------------------------------------------------------
# Stocktake: who counts what, and the scope of the count.
# ---------------------------------------------------------------------------


class StocktakeAssignment(TenantMixin, TimestampMixin, IdMixin, Base):
    """One counter's assignment inside a count: which location, and how far they got.

    Deliberately WITHOUT WorkspaceScopeMixin: this table's `location_id` is a
    WAREHOUSE location (a shelf, a bin), not the hierarchy location the mixin
    stamps, and the two names would collide.
    """

    __tablename__ = "stocktake_assignments"

    stocktake_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stocktakes.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    # The warehouse location this counter was asked to count (NULL = the whole count).
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouse_locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    # allowed: assigned | counting | counted | recount
    status: Mapped[str] = mapped_column(String(15), server_default="assigned")
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    counted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    counted_lines: Mapped[int] = mapped_column(Integer, server_default="0")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "stocktake_id", "user_id", name="uq_stocktake_assignments_user"
        ),
        CheckConstraint(
            "status IN ('assigned','counting','counted','recount')",
            name="ck_stocktake_assignments_status",
        ),
        CheckConstraint("counted_lines >= 0", name="ck_stocktake_assignments_counted_lines"),
        Index("ix_stocktake_assignments_stocktake", "tenant_id", "stocktake_id"),
    )


# ---------------------------------------------------------------------------
# Warehousing: where inside the warehouse the stock sits (D4).
#
# Locations are a SUB-POSITION of the warehouse, never a second balance: moving
# stock between two locations of the same warehouse changes nothing at the
# warehouse level and writes no in/out movement.
# ---------------------------------------------------------------------------


class WarehouseLocation(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """A physical place inside a warehouse: receiving, QC, a zone, a rack, a shelf, a bin.

    `kind` says what the place is FOR (the functional kinds: receiving, qc,
    storage, picking, packing, returns, quarantine, damaged) and `parent_id`
    says where it sits in the physical hierarchy (zone -> rack -> shelf -> bin).
    """

    __tablename__ = "warehouse_locations"

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(63))
    name: Mapped[str] = mapped_column(String(255))
    # allowed: receiving | qc | storage | picking | packing | returns |
    #         quarantine | damaged | zone | rack | shelf | bin
    kind: Mapped[str] = mapped_column(String(31))
    # The place this one sits in (zone -> rack -> shelf -> bin).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouse_locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    # How many units the place holds (NULL = not counted).
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "warehouse_id", "code", name="uq_warehouse_locations_tenant_wh_code"
        ),
        CheckConstraint(
            "kind IN ('receiving','qc','storage','picking','packing','returns',"
            "'quarantine','damaged','zone','rack','shelf','bin')",
            name="ck_warehouse_locations_kind",
        ),
        CheckConstraint(
            "capacity IS NULL OR capacity >= 0", name="ck_warehouse_locations_capacity"
        ),
        Index("ix_warehouse_locations_warehouse", "tenant_id", "warehouse_id"),
    )


class InventoryLocationBalance(TenantMixin, TimestampMixin, IdMixin, Base):
    """How much of a variant's stock sits at one location.

    The warehouse-level balance stays the truth; the sum of a variant's
    location balances at a warehouse may never exceed that warehouse's
    `on_hand` — a rule the service enforces.

    Deliberately WITHOUT WorkspaceScopeMixin: this table's `location_id` is a
    WAREHOUSE location (a shelf, a bin), not the hierarchy location the mixin
    stamps, and the two names would collide.
    """

    __tablename__ = "inventory_location_balances"

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouse_locations.id", ondelete="CASCADE")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    on_hand: Mapped[int] = mapped_column(Integer, server_default="0")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "location_id", "variant_id", name="uq_inv_location_balances_position"
        ),
        CheckConstraint("on_hand >= 0", name="ck_inv_location_balances_on_hand"),
        Index("ix_inv_location_balances_wh_variant", "tenant_id", "warehouse_id", "variant_id"),
    )


class InventoryLocationMovement(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
    """One move of stock between two locations of the SAME warehouse (append-only).

    The warehouse-level `on_hand` does not change, so no in/out movement is
    written for this: the row here IS the record of the move.
    """

    __tablename__ = "inventory_location_movements"

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    from_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouse_locations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    to_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouse_locations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    quantity: Mapped[int] = mapped_column(Integer)
    # allowed: putaway | replenishment | pick | transfer | adjustment | relocation
    reason: Mapped[str] = mapped_column(String(31))
    moved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_inv_location_movements_quantity"),
        CheckConstraint(
            "reason IN ('putaway','replenishment','pick','transfer','adjustment','relocation')",
            name="ck_inv_location_movements_reason",
        ),
        Index(
            "ix_inv_location_movements_wh_variant",
            "tenant_id",
            "warehouse_id",
            "variant_id",
            "created_at",
        ),
    )


# ---------------------------------------------------------------------------
# Quality: what arrived and whether it may be sold.
# ---------------------------------------------------------------------------


class InventoryQualityInspection(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """An inspection of goods that arrived: a receipt, a return, or a transfer receipt.

    `source_type` + `source_id` name what is being inspected. There is NO
    foreign key on the source: it points at rows of several kinds, exactly like
    `inventory_movements.reference_id` does.
    """

    __tablename__ = "inventory_quality_inspections"

    # allowed: goods_receipt | return_receipt | transfer_receipt
    source_type: Mapped[str] = mapped_column(String(31))
    # Polymorphic reference to the document being inspected — intentionally no FK.
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    # allowed: open | passed | quarantined | rejected
    status: Mapped[str] = mapped_column(String(15), server_default="open")
    inspected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    inspected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('goods_receipt','return_receipt','transfer_receipt')",
            name="ck_inv_quality_inspections_source_type",
        ),
        CheckConstraint(
            "status IN ('open','passed','quarantined','rejected')",
            name="ck_inv_quality_inspections_status",
        ),
        Index("ix_inv_quality_inspections_wh_status", "tenant_id", "warehouse_id", "status"),
        Index("ix_inv_quality_inspections_source", "tenant_id", "source_type", "source_id"),
    )


class InventoryInspectionResult(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
    """What the inspection decided about one variant: sell it, hold it, or reject it."""

    __tablename__ = "inventory_inspection_results"

    inspection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_quality_inspections.id", ondelete="CASCADE")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int] = mapped_column(Integer)
    # allowed: pass | quarantine | reject
    verdict: Mapped[str] = mapped_column(String(15))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    inspected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "inspection_id", "variant_id", name="uq_inv_inspection_results_variant"
        ),
        CheckConstraint("quantity > 0", name="ck_inv_inspection_results_quantity"),
        CheckConstraint(
            "verdict IN ('pass','quarantine','reject')",
            name="ck_inv_inspection_results_verdict",
        ),
        Index("ix_inv_inspection_results_inspection", "tenant_id", "inspection_id"),
    )


# ---------------------------------------------------------------------------
# Valuation: FIFO layers and landed cost.
# ---------------------------------------------------------------------------


class InventoryCostLayer(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """One FIFO layer of stock: what arrived, how much is left, and at what unit cost.

    `remaining_quantity` falls as the layer is consumed; it can never exceed
    what was received.
    """

    __tablename__ = "inventory_cost_layers"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    received_quantity: Mapped[int] = mapped_column(Integer)
    remaining_quantity: Mapped[int] = mapped_column(Integer, server_default="0")
    unit_cost: Mapped[Decimal] = mapped_column(COST)
    layer_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # What the layer came from (a receipt, a transfer, an opening balance).
    # No FK on either: the source is polymorphic, like the inspection's.
    source_type: Mapped[str | None] = mapped_column(String(31), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # The batch this stock arrived in, when the shop tracks expiry. A batch's remaining quantity
    # is the sum of its layers' remaining_quantity, so there is one place stock is counted.
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_lots.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("received_quantity > 0", name="ck_inv_cost_layers_received_quantity"),
        CheckConstraint("remaining_quantity >= 0", name="ck_inv_cost_layers_remaining_quantity"),
        CheckConstraint(
            "remaining_quantity <= received_quantity",
            name="ck_inv_cost_layers_remaining_le_received",
        ),
        CheckConstraint("unit_cost >= 0", name="ck_inv_cost_layers_unit_cost"),
        Index(
            "ix_inv_cost_layers_fifo",
            "tenant_id",
            "variant_id",
            "warehouse_id",
            "layer_date",
        ),
        Index(
            "ix_inventory_cost_layers_lot",
            "tenant_id",
            "lot_id",
            postgresql_where=text("lot_id IS NOT NULL"),
        ),
    )


class InventoryLandedCost(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """The extra cost of getting goods into the warehouse: freight, duty, insurance.

    `draft` is a calculation nobody has committed to; `posted` is a cost that
    has been allocated to the stock it belongs to.
    """

    __tablename__ = "inventory_landed_costs"

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    # The purchase order this cost came from (no model import: string FK only).
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    total: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    # allowed: draft | posted
    status: Mapped[str] = mapped_column(String(15), server_default="draft")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("total >= 0", name="ck_inv_landed_costs_total"),
        CheckConstraint("status IN ('draft','posted')", name="ck_inv_landed_costs_status"),
        Index("ix_inv_landed_costs_warehouse", "tenant_id", "warehouse_id"),
    )


class InventoryLandedCostLine(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
    """How much of a landed cost belongs to one variant."""

    __tablename__ = "inventory_landed_cost_lines"

    landed_cost_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_landed_costs.id", ondelete="CASCADE")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(MONEY)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_inv_landed_cost_lines_quantity"),
        CheckConstraint("amount >= 0", name="ck_inv_landed_cost_lines_amount"),
        Index("ix_inv_landed_cost_lines_cost", "tenant_id", "landed_cost_id"),
    )


# ---------------------------------------------------------------------------
# Replenishment: the rule for one variant at one warehouse, and what it says
# to do about it.
# ---------------------------------------------------------------------------


class InventoryPolicy(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """The replenishment rule for ONE variant at ONE warehouse.

    The numbers are the policy, not a suggestion: `min_stock` is where the
    reorder starts, `safety_stock` is the buffer that must survive the lead
    time, `moq` and `order_multiple` are what the supplier insists on.
    """

    __tablename__ = "inventory_policies"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    min_stock: Mapped[int] = mapped_column(Integer, server_default="0")
    max_stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    safety_stock: Mapped[int] = mapped_column(Integer, server_default="0")
    lead_time_days: Mapped[int] = mapped_column(Integer, server_default="0")
    moq: Mapped[int] = mapped_column(Integer, server_default="1")
    order_multiple: Mapped[int] = mapped_column(Integer, server_default="1")
    review_period_days: Mapped[int] = mapped_column(Integer, server_default="7")
    # The supplier to order from (no model import: string FK only).
    preferred_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "variant_id", "warehouse_id", name="uq_inventory_policies_variant_wh"
        ),
        CheckConstraint("min_stock >= 0", name="ck_inventory_policies_min_stock"),
        CheckConstraint(
            "max_stock IS NULL OR max_stock >= 0", name="ck_inventory_policies_max_stock"
        ),
        CheckConstraint("safety_stock >= 0", name="ck_inventory_policies_safety_stock"),
        CheckConstraint("lead_time_days >= 0", name="ck_inventory_policies_lead_time_days"),
        CheckConstraint("moq > 0", name="ck_inventory_policies_moq"),
        CheckConstraint("order_multiple > 0", name="ck_inventory_policies_order_multiple"),
        CheckConstraint("review_period_days > 0", name="ck_inventory_policies_review_period_days"),
    )


class ReorderSuggestion(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """What the replenishment engine suggests doing — and the arithmetic behind it.

    `source` says whether the goods should be MOVED from another warehouse or
    BOUGHT. `reason` carries the arithmetic that produced the number: the
    deterministic engine writes it, and an AI layer may only read and explain
    it.
    """

    __tablename__ = "reorder_suggestions"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    suggested_quantity: Mapped[int] = mapped_column(Integer)
    # allowed: transfer | purchase
    source: Mapped[str] = mapped_column(String(15))
    # The arithmetic that produced the suggestion.
    reason: Mapped[dict] = mapped_column(JSONB)
    # allowed: open | accepted | dismissed
    status: Mapped[str] = mapped_column(String(15), server_default="open")

    __table_args__ = (
        CheckConstraint("suggested_quantity > 0", name="ck_reorder_suggestions_quantity"),
        CheckConstraint("source IN ('transfer','purchase')", name="ck_reorder_suggestions_source"),
        CheckConstraint(
            "status IN ('open','accepted','dismissed')", name="ck_reorder_suggestions_status"
        ),
        Index("ix_reorder_suggestions_variant_wh", "tenant_id", "variant_id", "warehouse_id"),
        Index("ix_reorder_suggestions_status", "tenant_id", "status"),
    )


# ---------------------------------------------------------------------------
# Traceability: lots, serials, and the per-variant tracking rule.
# ---------------------------------------------------------------------------


class InventoryLot(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """A batch of one variant: what arrived, when, and when it expires."""

    __tablename__ = "inventory_lots"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    lot_code: Mapped[str] = mapped_column(String(63))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The supplier the lot came from (no model import: string FK only).
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
    )
    unit_cost: Mapped[Decimal | None] = mapped_column(COST, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "variant_id", "lot_code", name="uq_inventory_lots_tenant_variant_code"
        ),
        Index("ix_inventory_lots_variant", "tenant_id", "variant_id"),
    )


class InventorySerial(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """One individually tracked unit of a variant — a serial number."""

    __tablename__ = "inventory_serials"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    serial_code: Mapped[str] = mapped_column(String(63))
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_lots.id", ondelete="SET NULL"),
        nullable=True,
    )
    # allowed: in_stock | quarantined | sold | returned | damaged
    status: Mapped[str] = mapped_column(String(15), server_default="in_stock")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "variant_id",
            "serial_code",
            name="uq_inventory_serials_tenant_variant_code",
        ),
        CheckConstraint(
            "status IN ('in_stock','quarantined','sold','returned','damaged')",
            name="ck_inventory_serials_status",
        ),
        Index("ix_inventory_serials_variant", "tenant_id", "variant_id"),
    )


class VariantTrackingPolicy(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """How one variant is tracked: not at all, by batch, or by serial number."""

    __tablename__ = "variant_tracking_policies"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    # allowed: none | batch | serial
    mode: Mapped[str] = mapped_column(String(15), server_default="none")
    # Whether a batch of this variant must carry an expiry date.
    expiry_required: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (
        UniqueConstraint("tenant_id", "variant_id", name="uq_variant_tracking_policies_variant"),
        CheckConstraint(
            "mode IN ('none','batch','serial')", name="ck_variant_tracking_policies_mode"
        ),
    )


# ---------------------------------------------------------------------------
# Channel Allocation (§4 Phase 7): per-channel stock quotas.
# ---------------------------------------------------------------------------


class InventoryChannelAllocation(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """Stock quota per sales channel (e.g. pos, website, whatsapp).

    Prevents channels from overselling shared inventory.
    """

    __tablename__ = "inventory_channel_allocations"

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    channel: Mapped[str] = mapped_column(String(31))
    allocated_quantity: Mapped[int] = mapped_column(Integer, server_default="0")
    reserved_in_channel: Mapped[int] = mapped_column(Integer, server_default="0")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "warehouse_id",
            "variant_id",
            "channel",
            name="uq_inventory_channel_allocations_wh_var_ch",
        ),
        CheckConstraint(
            "allocated_quantity >= 0",
            name="ck_channel_allocations_allocated_qty",
        ),
        CheckConstraint(
            "reserved_in_channel >= 0",
            name="ck_channel_allocations_reserved_qty",
        ),
        Index("ix_channel_allocations_variant", "tenant_id", "variant_id"),
        Index("ix_channel_allocations_warehouse", "tenant_id", "warehouse_id"),
    )
