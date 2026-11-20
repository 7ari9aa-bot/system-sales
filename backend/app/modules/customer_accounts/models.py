"""Customer account ledger: append-only entries, and the per-customer terms.

The balance is never a column. It is the sum of the entries, so it cannot drift from them, and a
mistake is corrected by a reversal entry, never by editing history.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import MONEY, AppendOnlyCreatedAtMixin, IdMixin, TenantMixin, TimestampMixin


class CustomerAccount(TenantMixin, TimestampMixin, IdMixin, Base):
    """The terms a customer trades on. Existence of a row opts the customer in to credit."""

    __tablename__ = "customer_accounts"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    # NULL = no limit. 0 = no credit at all (deposits and cash sales only).
    credit_limit: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_id", name="uq_customer_accounts_tenant_customer"),
        CheckConstraint(
            "credit_limit IS NULL OR credit_limit >= 0", name="ck_customer_accounts_limit"
        ),
    )


class CustomerLedgerEntry(TenantMixin, AppendOnlyCreatedAtMixin, IdMixin, Base):
    """One movement on a customer's account. Never updated, never deleted."""

    __tablename__ = "customer_ledger"

    # The order entries happened in. created_at is the transaction's start and is identical for
    # every entry posted in one transaction, so it cannot order a statement; this can.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    # charge | payment | deposit | deposit_applied | adjustment | reversal
    entry_type: Mapped[str] = mapped_column(String(31), nullable=False)
    # The effect on the balance, signed: + the customer owes more, - they owe less.
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=True
    )
    reverses_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_ledger.id", ondelete="RESTRICT"), nullable=True
    )
    # A replayed request (an offline till resending) must not post twice.
    idempotency_key: Mapped[str | None] = mapped_column(String(127), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # running balance AFTER this entry, kept for fast statements; the sum is the truth.
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('charge','payment','deposit','deposit_applied',"
            "'adjustment','reversal')",
            name="ck_customer_ledger_type",
        ),
        CheckConstraint("amount <> 0", name="ck_customer_ledger_nonzero"),
        # the sign must match the kind: a payment can never ADD debt, a charge can never reduce it
        CheckConstraint(
            "(entry_type IN ('charge','deposit_applied') AND amount > 0) "
            "OR (entry_type IN ('payment','deposit') AND amount < 0) "
            "OR entry_type IN ('adjustment','reversal')",
            name="ck_customer_ledger_sign",
        ),
        CheckConstraint(
            "entry_type <> 'adjustment' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_customer_ledger_adjustment_reason",
        ),
        CheckConstraint(
            "(entry_type = 'reversal') = (reverses_entry_id IS NOT NULL)",
            name="ck_customer_ledger_reversal_link",
        ),
        Index("ix_customer_ledger_tenant_customer", "tenant_id", "customer_id", "seq"),
        Index("ix_customer_ledger_order", "tenant_id", "order_id"),
        # one reversal per entry, and one posting per idempotency key
        Index(
            "uq_customer_ledger_one_reversal",
            "tenant_id",
            "reverses_entry_id",
            unique=True,
            postgresql_where="reverses_entry_id IS NOT NULL",
        ),
        Index(
            "uq_customer_ledger_idempotency",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where="idempotency_key IS NOT NULL",
        ),
    )
