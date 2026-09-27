"""Financial domain models (V12 Wave C §31).

Implements pure double-entry bookkeeping:
- Every financial event is an atomic Transaction composed of 2 or more Entries.
- Strict invariant: SUM(debit amounts) == SUM(credit amounts).
- Enforced at service layer and guarded against float precision issues with Numeric(14, 4).
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.model_kit import TenantMixin

ACCOUNT_TYPES: frozenset[str] = frozenset(
    {"ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"}
)
ENTRY_TYPES: frozenset[str] = frozenset({"DEBIT", "CREDIT"})
TRANSACTION_STATUSES: frozenset[str] = frozenset({"DRAFT", "POSTED", "VOID"})


class ChartOfAccount(TenantMixin, Base):
    """The general ledger chart of accounts per tenant."""

    __tablename__ = "chart_of_accounts"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), server_default="SAR", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    entries: Mapped[list[FinancialEntry]] = relationship(
        "FinancialEntry", back_populates="account"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_chart_of_accounts_tenant_code"),
        Index("ix_chart_of_accounts_tenant_type", "tenant_id", "account_type"),
    )


class FinancialTransaction(TenantMixin, Base):
    """An atomic financial journal transaction header."""

    __tablename__ = "financial_transactions"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    reference_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    effect_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    currency: Mapped[str] = mapped_column(String(3), server_default="SAR", nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="POSTED", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    entries: Mapped[list[FinancialEntry]] = relationship(
        "FinancialEntry", back_populates="transaction", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_financial_transactions_tenant_ref", "tenant_id", "reference_type", "reference_id"),
        Index("ix_financial_transactions_tenant_posted", "tenant_id", "posted_at"),
        Index("ix_financial_transactions_tenant_decision", "tenant_id", "decision_id"),
    )


class FinancialEntry(TenantMixin, Base):
    """One single debit or credit entry within a transaction."""

    __tablename__ = "financial_entries"

    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("financial_transactions.transaction_id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chart_of_accounts.account_id"),
        nullable=False,
    )
    entry_type: Mapped[str] = mapped_column(String(8), nullable=False)  # DEBIT or CREDIT
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    memo: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    transaction: Mapped[FinancialTransaction] = relationship(
        "FinancialTransaction", back_populates="entries"
    )
    account: Mapped[ChartOfAccount] = relationship(
        "ChartOfAccount", back_populates="entries"
    )

    __table_args__ = (
        Index("ix_financial_entries_tenant_account", "tenant_id", "account_id"),
        Index("ix_financial_entries_tenant_tx", "tenant_id", "transaction_id"),
    )
