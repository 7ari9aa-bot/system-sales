"""POS domain models — registers, sessions, cash movements, receipts (§189).

POS owns its own state (register, session, cash, receipt) and issues commerce
commands; it never writes inventory balances or order state directly. The
cash movement ledger is append-only and session-scoped, so a session close is
arithmetic over rows — expected cash is computed, never remembered.
Enum-like columns are String with closed vocabularies enforced in the service.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
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


class PosRegister(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """A physical till. It sells from ONE warehouse's stock pool."""

    __tablename__ = "pos_registers"

    name: Mapped[str] = mapped_column(String(127))
    code: Mapped[str] = mapped_column(String(31))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_pos_registers_tenant_code"),
    )


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
    # allowed: OPEN | CLOSED
    status: Mapped[str] = mapped_column(String(15), server_default="OPEN")
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
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_pos_sessions_open_per_register",
            "tenant_id",
            "register_id",
            unique=True,
            postgresql_where="status = 'OPEN'",
        ),
    )


class PosCashMovement(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
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
    reference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
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


class PosReceipt(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
    """One receipt per POS sale — the human-facing artifact of one order."""

    __tablename__ = "pos_receipts"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_sessions.id", ondelete="CASCADE")
    )
    number: Mapped[str] = mapped_column(String(31))
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_pos_receipts_tenant_number"),
    )
