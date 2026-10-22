"""POS domain models — profiles, registers, sessions, cash movements, receipts (§189).

POS owns its own state (profile, register, session, cash, receipt) and issues
commerce commands; it never writes inventory balances or order state directly.
The cash movement ledger is append-only and session-scoped, so a session close
is arithmetic over rows — expected cash is computed, never remembered.
Enum-like columns are String with closed vocabularies enforced in the service.

The Profile is the ERPNext `POS Profile` idea (§2 of the plan): a terminal
configuration — default warehouse, walk-in customer and allowed payment methods —
so a cashier's station is preconfigured instead of invented
per sale.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
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


class PosProfile(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """A cashier station's preconfiguration (§189, ERPNext `POS Profile`).

    One profile drives many registers: the config changes without touching the
    hardware.
    """

    __tablename__ = "pos_profiles"

    name: Mapped[str] = mapped_column(String(127))
    code: Mapped[str] = mapped_column(String(31))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    # Walk-in fallback when require_customer is False. SET NULL (not RESTRICT):
    # a deleted customer must not take the profile — and every till using it —
    # down; the service refuses a sale whose profile lost its customer.
    default_customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    # Closed vocabulary mirrors the orders payment methods; the service refuses
    # a tender whose method is not in this list.
    allowed_payment_methods: Mapped[list] = mapped_column(
        JSONB, server_default='["cash", "card", "wallet", "bank_transfer"]'
    )
    require_customer: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # The till's preselected tender (ERPNext `set_grand_total_to_default_mop`):
    # a sale that names no tender charges this method with the whole total.
    # NULL = the service falls back to cash.
    default_payment_method: Mapped[str | None] = mapped_column(String(31), nullable=True)
    # Category ids this terminal serves (ERPNext `POS Item Group`). Empty list
    # = the tenant's whole catalog; the browse grid and the scan both refuse
    # outside it.
    item_group_ids: Mapped[list] = mapped_column(JSONB, server_default="[]")

    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_pos_profiles_tenant_code"),)


class PosProfileUser(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base):
    """Which user may operate a profile (ERPNext `POS Profile User`).

    The grant is a plain link row, not a role: a cashier is a user who has been
    granted this terminal, and revoking is deleting the row.
    """

    __tablename__ = "pos_profile_users"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_profiles.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "profile_id", "user_id", name="uq_pos_profile_users"),
    )


class PosRegister(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """A physical till. It sells from ONE warehouse's stock pool."""

    __tablename__ = "pos_registers"

    name: Mapped[str] = mapped_column(String(127))
    code: Mapped[str] = mapped_column(String(31))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    # Nullable so an existing register (created before profiles) keeps working;
    # a register WITH a profile inherits the profile's warehouse + policy.
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_profiles.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_pos_registers_tenant_code"),)


class PosSession(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """A cash-drawer shift on one register. One OPEN session per register.

    Closing is the POS cash reconciliation (§188): expected cash is the
    opening float plus the session's cash rows, and the counted figure is
    compared against it — the variance is a record, never a fix.
    """

    __tablename__ = "pos_sessions"

    register_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_registers.id", ondelete="RESTRICT")
    )
    # The terminal configuration the shift ran under, captured at open time so a
    # later profile edit cannot retroactively change what this shift allowed.
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_profiles.id", ondelete="SET NULL"), nullable=True
    )
    # allowed: OPEN | CLOSED
    status: Mapped[str] = mapped_column(String(15), server_default="OPEN")
    # Who is holding the drawer. A cashier is a user; the policy check refuses a
    # sale by a user who was not granted the session's profile.
    cashier_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    opened_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    opening_float: Mapped[Decimal] = mapped_column(MONEY)
    counted_cash: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    expected_cash: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    variance: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "uq_pos_sessions_open_per_register",
            "tenant_id",
            "register_id",
            unique=True,
            postgresql_where="status = 'OPEN'",
        ),
        Index(
            "uq_pos_sessions_open_per_user",
            "tenant_id",
            "cashier_user_id",
            unique=True,
            postgresql_where="status = 'OPEN'",
        ),
    )


class PosSessionFloat(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base):
    """The drawer's opening float PER PAYMENT METHOD (ERPNext `POS Opening
    Entry Detail`).

    A shift does not only start with cash: a card terminal may need a tip
    drawer, a wallet float, change for returns. One row per method the session
    opened with; the session's ``opening_float`` column keeps the cash leg so
    the existing arithmetic never breaks. Append-only like the cash ledger it
    feeds.
    """

    __tablename__ = "pos_session_floats"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_sessions.id", ondelete="CASCADE")
    )
    # allowed: cash | card | wallet | bank_transfer
    method: Mapped[str] = mapped_column(String(31))
    amount: Mapped[Decimal] = mapped_column(MONEY)

    __table_args__ = (
        UniqueConstraint("tenant_id", "session_id", "method", name="uq_pos_floats_session_method"),
    )


class PosCashMovement(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base):
    """Append-only cash ledger for one session (§189).

    direction `in` books money into the drawer, `out` removes it. The
    `cash_sale`/`cash_refund` reasons are written only by the sell flow —
    a hand-written cash sale would book money no order claims.
    """

    __tablename__ = "pos_cash_movements"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_sessions.id", ondelete="CASCADE")
    )
    # allowed: in | out
    direction: Mapped[str] = mapped_column(String(6))
    # allowed: cash_sale | cash_refund | pay_in | pay_out | cash_drop |
    #          float_adjust
    reason: Mapped[str] = mapped_column(String(31))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    reference_type: Mapped[str | None] = mapped_column(String(31), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_pos_cash_tenant_session",
            "tenant_id",
            "session_id",
        ),
    )


class PosReceipt(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base):
    """One receipt per POS sale — the human-facing artifact of one order."""

    __tablename__ = "pos_receipts"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_sessions.id", ondelete="CASCADE")
    )
    number: Mapped[str] = mapped_column(String(31))
    # allowed: sale | return — a return is its own receipt (ERPNext
    # `is_return`): negative lines against the original sale's receipt.
    kind: Mapped[str] = mapped_column(String(7), server_default="sale")
    # Tender vs owed (ERPNext `change_amount`/`account_for_change_amount`):
    # what the customer handed over and the change returned. NULL when the sale
    # was settled exactly (no cash tender, or card).
    tendered_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    change_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Set on the NEW SALE receipt of an exchange: the return receipt it was paired with. Written
    # at insert (receipts are append-only). NULL = an ordinary sale, or a pre-link exchange.
    exchange_return_receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pos_receipts.id", ondelete="RESTRICT", name="fk_pos_receipts_exchange_return"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_pos_receipts_tenant_number"),
    )


class PosReturnLine(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base):
    """One returned line of one return receipt (§189 phase 2).

    Priced at the ORIGINAL sale's line price — a return never re-prices the
    basket. This table is the single source for "how much of this sale has
    already come back": both the money cap (a variant cannot be returned more
    times than it was sold) and the per-variant restock decision read from it.
    """

    __tablename__ = "pos_return_lines"

    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_receipts.id", ondelete="CASCADE")
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT")
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int] = mapped_column()
    # The original sale's own unit price, frozen at return time.
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    # What this line actually refunded: the original gross minus this line's
    # share of the order's discount.
    refund_total: Mapped[Decimal] = mapped_column(MONEY)

    __table_args__ = (Index("ix_pos_return_lines_tenant_order", "tenant_id", "order_id"),)


class PosSessionReconciliation(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
    """Per-payment-method reconciliation at session close (§188, ERPNext
    `POS Closing Entry Detail`).

    The session's single ``expected_cash``/``variance`` pair only ever told the
    truth about cash. A merchant taking card and wallet needs the same
    arithmetic per method, so each close writes one row per method the session
    actually saw: expected (from the payments) vs counted (typed by the closer),
    and the difference. A discrepancy is a record, never a correction.
    """

    __tablename__ = "pos_session_reconciliations"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_sessions.id", ondelete="CASCADE")
    )
    # allowed: cash | card | wallet | bank_transfer
    method: Mapped[str] = mapped_column(String(31))
    expected_amount: Mapped[Decimal] = mapped_column(MONEY)
    counted_amount: Mapped[Decimal] = mapped_column(MONEY)
    variance: Mapped[Decimal] = mapped_column(MONEY)

    __table_args__ = (
        UniqueConstraint("tenant_id", "session_id", "method", name="uq_pos_recon_session_method"),
    )


class PosHeldCart(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """A parked cart — a customer stepped aside, the till keeps their basket.

    The cart is a CART, not a sale: holding one reserves nothing and books no
    money. It stays a plain snapshot (variant + quantity lines, an optional
    customer, an optional discount) until it is turned into a real sale through
    the exact same ``sell`` path every other basket takes. Two parked carts can
    therefore both name the last unit of a variant; whichever sells first wins,
    and the loser hears the normal out-of-stock refusal — the alternative
    (reserving on hold) would let a full till be immobilised by abandoned carts.

    ``label`` is the human handle ("Ahmed — 2 shirts"); ``held_by_user_id`` is
    who parked it, so a shift's carts can be handed over or dropped at close.
    """

    __tablename__ = "pos_held_carts"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_sessions.id", ondelete="CASCADE")
    )
    # The basket, verbatim: [{"variant_id": str, "quantity": int}, ...]. Kept as
    # JSONB because it is a cart the cashier is still building, not a priced
    # line — the price is struck only at sell time, from the tenant's ladder.
    items: Mapped[list] = mapped_column(JSONB)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    discount_total: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    label: Mapped[str | None] = mapped_column(String(127), nullable=True)
    held_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (Index("ix_pos_held_carts_tenant_session", "tenant_id", "session_id"),)


class PosSessionHandover(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base):
    """A mid-shift drawer hand-off from one cashier to the next (§188/§189).

    A single OPEN session can outlive one cashier — a shift change, a break, a
    second till operator. Rather than close and reopen (which would split one
    drawer's cash across two reconciliations), the drawer is COUNTED at the
    moment of hand-off and the count is recorded here: who gave it, who took it,
    what the arithmetic expected, what was actually in it, and the variance.

    The session's status does not change — the SAME session keeps running, and
    its ``cashier_user_id`` moves to the new holder. The close reconciliation
    still runs over the whole session; the handovers are the audit trail of who
    was responsible between which two points. Append-only: a handover is a fact
    that already happened, never an editable row.
    """

    __tablename__ = "pos_session_handovers"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_sessions.id", ondelete="CASCADE")
    )
    from_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    to_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    # The drawer position at the hand-off, from the session's own arithmetic.
    expected_cash: Mapped[Decimal] = mapped_column(MONEY)
    counted_cash: Mapped[Decimal] = mapped_column(MONEY)
    variance: Mapped[Decimal] = mapped_column(MONEY)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (Index("ix_pos_handovers_tenant_session", "tenant_id", "session_id"),)


class PosDailySales(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """The daily sales projection — ERPNext's consolidation, event-fed (§190).

    One row per (tenant, business_date, register). The pos worker pool
    RECOMPUTES it from the ledgers on every ``pos.session.closed`` event —
    never incremented, so a redelivered event rewrites the same truth instead
    of doubling it. Analytics reads this table; nothing in the commerce core
    ever does.
    """

    __tablename__ = "pos_daily_sales"

    business_date: Mapped[date] = mapped_column(Date)
    register_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_registers.id", ondelete="RESTRICT")
    )
    session_count: Mapped[int] = mapped_column(server_default="0")
    invoice_count: Mapped[int] = mapped_column(server_default="0")
    returns_count: Mapped[int] = mapped_column(server_default="0")
    sales_total: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    returns_total: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    taxes_total: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    variance_total: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    # [{method, expected, counted, variance}] summed across the day's sessions.
    by_method: Mapped[list] = mapped_column(JSONB, server_default="[]")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "business_date",
            "register_id",
            name="uq_pos_daily_sales_date_register",
        ),
        Index("ix_pos_daily_tenant_date", "tenant_id", "business_date"),
    )
