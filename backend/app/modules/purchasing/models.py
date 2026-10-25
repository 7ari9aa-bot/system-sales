"""PURCHASING domain models: suppliers, purchase orders, supplier payments, supplier returns,
and the moving-average cost of every variant.

Design rules (backend design doc, phase 2):
  * Receiving and paying are SEPARATE facts. A purchase order has a receipt state (stored) and a
    payment state that is DERIVED from supplier_payments. Buying on credit is the normal case.
  * Stock enters/leaves only through InventoryService.move(), never by writing the ledger here
    (reason 'purchase' in, 'supplier_return' out, reference_type = the document).
  * A supplier's balance is never stored. It is computed from received orders, payments and
    accepted credit returns, so there is no second number that can drift from the documents.
  * Cost is the MOVING AVERAGE, updated only at receipt, kept in its own table so the catalog
    module's product_variants is untouched. Every change is appended to variant_cost_history.
  * Enum-like columns are String with allowed values documented inline, never sa.Enum.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
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

SUPPLIER_STATUSES: frozenset[str] = frozenset({"active", "inactive"})
PO_STATUSES: frozenset[str] = frozenset({"draft", "received", "cancelled"})
PAYMENT_METHODS: frozenset[str] = frozenset({"cash", "card", "wallet", "bank_transfer"})
RETURN_STATUSES: frozenset[str] = frozenset({"review", "accepted", "rejected"})
RETURN_SETTLEMENTS: frozenset[str] = frozenset({"cash", "credit", "replace"})

# Cost is kept with 4 places: an average of 10.00 and 12.00 over odd quantities is not a clean cent,
# and rounding it to 2 places at every receipt would drift. Totals shown to people are rounded once.
COST = Numeric(14, 4)


class Supplier(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(255))
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(31), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # allowed: active | inactive. A supplier with history is never deleted, only deactivated.
    status: Mapped[str] = mapped_column(String(15), server_default="active")

    __table_args__ = (
        CheckConstraint("status IN ('active','inactive')", name="ck_suppliers_status"),
        Index("ix_suppliers_tenant_status", "tenant_id", "status"),
    )


class PurchaseOrder(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    __tablename__ = "purchase_orders"

    number: Mapped[str] = mapped_column(String(31))
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT")
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    order_date: Mapped[date] = mapped_column(Date)
    # allowed: draft | received | cancelled  (payment state is derived, not stored)
    status: Mapped[str] = mapped_column(String(15), server_default="draft")
    total: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_purchase_orders_tenant_number"),
        CheckConstraint(
            "status IN ('draft','received','cancelled')", name="ck_purchase_orders_status"
        ),
        CheckConstraint("total >= 0", name="ck_purchase_orders_total"),
        # A received order says when; any other state must not.
        CheckConstraint(
            "(status = 'received') = (received_at IS NOT NULL)",
            name="ck_purchase_orders_received_at",
        ),
        Index("ix_purchase_orders_tenant_supplier", "tenant_id", "supplier_id"),
        Index("ix_purchase_orders_tenant_date", "tenant_id", "order_date"),
    )


class PurchaseOrderLine(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base):
    """Lines are written with their order and never edited (a wrong order is cancelled)."""

    __tablename__ = "purchase_order_lines"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal] = mapped_column(MONEY)
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    position: Mapped[int] = mapped_column(
        Integer
    )  # 1-based place on the document; created_at cannot order lines

    __table_args__ = (
        UniqueConstraint("tenant_id", "purchase_order_id", "position", name="uq_po_lines_position"),
        CheckConstraint("position > 0", name="ck_po_lines_position"),
        CheckConstraint("quantity > 0", name="ck_po_lines_quantity"),
        CheckConstraint("unit_cost >= 0", name="ck_po_lines_unit_cost"),
        # The database itself refuses a line whose total is not quantity x cost.
        CheckConstraint("line_total = quantity * unit_cost", name="ck_po_lines_total"),
        Index("ix_po_lines_order", "tenant_id", "purchase_order_id"),
        Index("ix_po_lines_variant", "tenant_id", "variant_id"),
    )


class SupplierPayment(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base):
    """Money paid to a supplier. Append-only: a mistake is reversed by a voiding row, not edited.

    Paying a supplier settles a debt for stock; it is NOT an expense. It is a RECORD (amount, date,
    supplier, invoice): the POS never moves money, so no drawer row is written for it.
    """

    __tablename__ = "supplier_payments"

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT")
    )
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY)
    # allowed: cash | card | wallet | bank_transfer
    method: Mapped[str] = mapped_column(String(15))
    paid_on: Mapped[date] = mapped_column(Date)
    # Kept for history only. New payments are records and never name a shift (always NULL).
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_sessions.id", ondelete="SET NULL"), nullable=True
    )
    # A reversal points at the payment it cancels (amount stays positive; this flag carries the
    # sign).
    reverses_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier_payments.id", ondelete="RESTRICT"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_supplier_payments_amount"),
        CheckConstraint(
            "method IN ('cash','card','wallet','bank_transfer')", name="ck_supplier_payments_method"
        ),
        CheckConstraint(
            "session_id IS NULL OR method = 'cash'",
            name="ck_supplier_payments_shift_only_cash",
        ),
        # one payment can be reversed at most once
        UniqueConstraint("tenant_id", "reverses_payment_id", name="uq_supplier_payments_reversal"),
        Index("ix_supplier_payments_tenant_supplier", "tenant_id", "supplier_id"),
        Index("ix_supplier_payments_tenant_order", "tenant_id", "purchase_order_id"),
    )


class SupplierReturn(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    __tablename__ = "supplier_returns"

    number: Mapped[str] = mapped_column(String(31))
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT")
    )
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=True
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    # Retired: the shop does not record why goods go back. Rows written before keep their value.
    reason: Mapped[str | None] = mapped_column(String(31), nullable=True)
    # allowed: cash | credit | replace
    settlement: Mapped[str] = mapped_column(String(15))
    # allowed: review | accepted | rejected. Goods leave the shelf at registration; the MONEY effect
    # (account credit / cash refund) happens only when the supplier accepts.
    status: Mapped[str] = mapped_column(String(15), server_default="review")
    total: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    return_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Kept for history only. A refund is a record and never names a shift (always NULL).
    refund_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_sessions.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_supplier_returns_tenant_number"),
        CheckConstraint(
            "status IN ('review','accepted','rejected')", name="ck_supplier_returns_status"
        ),
        CheckConstraint(
            "settlement IN ('cash','credit','replace')", name="ck_supplier_returns_settlement"
        ),
        CheckConstraint("total >= 0", name="ck_supplier_returns_total"),
        CheckConstraint(
            "(status = 'review') = (decided_at IS NULL)", name="ck_supplier_returns_decided_at"
        ),
        Index("ix_supplier_returns_tenant_supplier", "tenant_id", "supplier_id"),
    )


class SupplierReturnLine(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base):
    __tablename__ = "supplier_return_lines"

    supplier_return_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier_returns.id", ondelete="CASCADE")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal] = mapped_column(MONEY)
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    position: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "supplier_return_id", "position", name="uq_sr_lines_position"
        ),
        CheckConstraint("position > 0", name="ck_sr_lines_position"),
        CheckConstraint("quantity > 0", name="ck_sr_lines_quantity"),
        CheckConstraint("unit_cost >= 0", name="ck_sr_lines_unit_cost"),
        CheckConstraint("line_total = quantity * unit_cost", name="ck_sr_lines_total"),
        Index("ix_sr_lines_return", "tenant_id", "supplier_return_id"),
    )


class VariantCost(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """Current moving-average cost per variant (one row each). Updated only at receipt."""

    __tablename__ = "variant_costs"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    # NULL = unknown (stock that pre-dates any recorded purchase), NOT zero.
    avg_cost: Mapped[Decimal | None] = mapped_column(COST, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "variant_id", name="uq_variant_costs_tenant_variant"),
        CheckConstraint("avg_cost >= 0", name="ck_variant_costs_avg"),
    )


class VariantCostHistory(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base):
    """Every cost change, with what it was computed from, so any number can be re-derived."""

    __tablename__ = "variant_cost_history"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    old_avg_cost: Mapped[Decimal | None] = mapped_column(COST, nullable=True)
    new_avg_cost: Mapped[Decimal] = mapped_column(COST)
    on_hand_before: Mapped[int] = mapped_column(Integer)
    received_quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal] = mapped_column(MONEY)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_variant_cost_history_variant", "tenant_id", "variant_id", "created_at"),
    )
