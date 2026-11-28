"""EXPENSES domain models: categories, expenses, and the per-year document counter.

An expense is a posted business cost (rent, electricity, packaging...). It is NOT a
supplier payment (paying a supplier settles a debt for stock that is later costed
when sold) and NOT a drawer movement: the POS records, it never moves money, so an expense
writes no drawer row whatever its method.

A posted expense is never edited or deleted. A mistake is VOIDED, which keeps the original
row and marks it voided with a reason (same rule as the stock ledger).
Enum-like columns are String with allowed values documented inline, never sa.Enum.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import MONEY, IdMixin, TenantMixin, TimestampMixin, WorkspaceScopeMixin

# Closed vocabularies (documented here, enforced by the service and the request model).
EXPENSE_PAYMENT_METHODS: frozenset[str] = frozenset({"cash", "card", "wallet", "bank_transfer"})
EXPENSE_STATUSES: frozenset[str] = frozenset({"posted", "voided"})


class ExpenseCategory(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """A merchant-editable expense category (was a hard-coded list in the screen)."""

    __tablename__ = "expense_categories"

    name: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_expense_categories_tenant_name"),
    )


class Expense(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    __tablename__ = "expenses"

    # EXP-0001 style, from the server counter inside the same transaction.
    number: Mapped[str] = mapped_column(String(31))
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("expense_categories.id", ondelete="RESTRICT")
    )
    description: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    # allowed: cash | card | wallet | bank_transfer
    payment_method: Mapped[str] = mapped_column(String(15))
    expense_date: Mapped[date] = mapped_column(Date)
    # Kept for history only. New expenses never name a session (always NULL).
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_sessions.id", ondelete="SET NULL"), nullable=True
    )
    # allowed: posted | voided
    status: Mapped[str] = mapped_column(String(15), server_default="posted")
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_expenses_tenant_number"),
        CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        CheckConstraint("status IN ('posted','voided')", name="ck_expenses_status"),
        CheckConstraint(
            "payment_method IN ('cash','card','wallet','bank_transfer')",
            name="ck_expenses_payment_method",
        ),
        # Only a cash expense may carry a session (old rows); a non-cash one never does.
        CheckConstraint(
            "session_id IS NULL OR payment_method = 'cash'",
            name="ck_expenses_shift_only_cash",
        ),
        Index("ix_expenses_tenant_date", "tenant_id", "expense_date"),
        Index("ix_expenses_tenant_category", "tenant_id", "category_id"),
    )


class DocumentCounter(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """Gap-free per-(kind, year) document numbering (EXP / PO / SR).

    Incremented with SELECT ... FOR UPDATE in the SAME transaction as the document,
    so a rolled-back document gives its number back and two concurrent requests
    can never receive the same one.
    """

    __tablename__ = "document_counters"

    # allowed: EXP | PO | SR
    kind: Mapped[str] = mapped_column(String(8))
    year: Mapped[int] = mapped_column(Integer)
    last_seq: Mapped[int] = mapped_column(Integer, server_default="0")

    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", "year", name="uq_document_counters_tenant_kind_year"),
    )
