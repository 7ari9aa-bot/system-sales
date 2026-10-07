"""Financial double-entry ledger service (V12 Wave C §31)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.financial.models import (
    ACCOUNT_TYPES,
    ChartOfAccount,
    FinancialEntry,
    FinancialTransaction,
)
from app.modules.financial.ports import PaymentPort, SandboxPaymentAdapter
from app.modules.financial.schemas import (
    EntryCreate,
    TrialBalanceItem,
    TrialBalanceOut,
)

DEFAULT_CHART_OF_ACCOUNTS = [
    ("1010", "Cash & Bank", "ASSET"),
    ("1200", "Accounts Receivable", "ASSET"),
    ("1300", "Inventory Asset", "ASSET"),
    ("2010", "Accounts Payable", "LIABILITY"),
    ("2100", "VAT / Sales Tax Payable", "LIABILITY"),
    ("3010", "Owner's Equity & Retained Earnings", "EQUITY"),
    ("4010", "Sales Revenue", "REVENUE"),
    ("4020", "Shipping & Delivery Income", "REVENUE"),
    ("5010", "Cost of Goods Sold", "EXPENSE"),
    ("5020", "Discounts & Allowances", "EXPENSE"),
    ("5030", "Payment Gateway & Processing Fees", "EXPENSE"),
]


class FinancialService:
    """Core service for managing the general ledger and double-entry postings."""

    @staticmethod
    def validate_balanced(entries: list[EntryCreate] | list[dict[str, Any]]) -> None:
        """Enforces Invariant: SUM(debits) == SUM(credits) to 4 decimal places."""
        total_debits = Decimal("0.0000")
        total_credits = Decimal("0.0000")

        for entry in entries:
            is_create = isinstance(entry, EntryCreate)
            e_type = entry.entry_type if is_create else entry["entry_type"]
            amount = entry.amount if is_create else Decimal(str(entry["amount"]))
            if e_type == "DEBIT":
                total_debits += amount
            elif e_type == "CREDIT":
                total_credits += amount
            else:
                raise ValidationError(f"Invalid entry_type: {e_type}")

        if total_debits != total_credits:
            raise ConflictError(
                f"Double-entry transaction unbalanced: Total debits ({total_debits}) != "
                f"Total credits ({total_credits})"
            )

    @staticmethod
    async def seed_default_chart_of_accounts(
        session: AsyncSession, tenant_id: uuid.UUID, currency: str = "SAR"
    ) -> list[ChartOfAccount]:
        """Seeds standard accounting codes if not already present."""
        created_accounts: list[ChartOfAccount] = []
        now = datetime.now(UTC)

        for code, name, acc_type in DEFAULT_CHART_OF_ACCOUNTS:
            existing = await session.scalar(
                select(ChartOfAccount).where(
                    ChartOfAccount.tenant_id == tenant_id,
                    ChartOfAccount.code == code,
                )
            )
            if not existing:
                account = ChartOfAccount(
                    tenant_id=tenant_id,
                    code=code,
                    name=name,
                    account_type=acc_type,
                    currency=currency,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                session.add(account)
                created_accounts.append(account)

        if created_accounts:
            await session.flush()
        return created_accounts

    @staticmethod
    async def create_account(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        code: str,
        name: str,
        account_type: str,
        currency: str = "SAR",
    ) -> ChartOfAccount:
        """Create a single account in the chart of accounts."""
        if account_type not in ACCOUNT_TYPES:
            raise ValidationError(f"account_type must be one of {sorted(ACCOUNT_TYPES)}")

        existing = await session.scalar(
            select(ChartOfAccount).where(
                ChartOfAccount.tenant_id == tenant_id,
                ChartOfAccount.code == code.strip(),
            )
        )
        if existing:
            raise ConflictError(f"Account code {code} already exists for this tenant")

        now = datetime.now(UTC)
        account = ChartOfAccount(
            tenant_id=tenant_id,
            code=code.strip(),
            name=name.strip(),
            account_type=account_type,
            currency=currency.strip().upper(),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(account)
        await session.flush()
        return account

    @staticmethod
    async def get_account_by_code(
        session: AsyncSession, tenant_id: uuid.UUID, code: str
    ) -> ChartOfAccount:
        """Get account by code, raising NotFoundError if absent."""
        account = await session.scalar(
            select(ChartOfAccount).where(
                ChartOfAccount.tenant_id == tenant_id,
                ChartOfAccount.code == code.strip(),
            )
        )
        if not account:
            raise NotFoundError(f"Chart of Account '{code}' not found")
        return account

    @staticmethod
    async def post_transaction(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        reference_type: str,
        reference_id: uuid.UUID | None = None,
        currency: str = "SAR",
        entries: list[EntryCreate],
        decision_id: uuid.UUID | None = None,
        effect_id: uuid.UUID | None = None,
        description: str | None = None,
    ) -> FinancialTransaction:
        """Atomically post a balanced double-entry transaction."""
        if len(entries) < 2:
            raise ValidationError("A financial transaction must contain at least two entries")

        FinancialService.validate_balanced(entries)

        now = datetime.now(UTC)
        tx = FinancialTransaction(
            tenant_id=tenant_id,
            reference_type=reference_type.strip(),
            reference_id=reference_id,
            decision_id=decision_id,
            effect_id=effect_id,
            currency=currency.strip().upper(),
            status="POSTED",
            description=description,
            posted_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(tx)
        await session.flush()

        for e in entries:
            acc_id = e.account_id
            if acc_id is None:
                if not e.account_code:
                    raise ValidationError("Entry must specify account_id or account_code")
                acc = await FinancialService.get_account_by_code(session, tenant_id, e.account_code)
                acc_id = acc.account_id

            entry_row = FinancialEntry(
                tenant_id=tenant_id,
                transaction_id=tx.transaction_id,
                account_id=acc_id,
                entry_type=e.entry_type,
                amount=e.amount,
                memo=e.memo,
                created_at=now,
            )
            session.add(entry_row)

        await session.flush()
        return tx

    @staticmethod
    async def post_order_sale(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        order_id: uuid.UUID,
        subtotal: Decimal,
        tax: Decimal = Decimal("0.0000"),
        shipping: Decimal = Decimal("0.0000"),
        total: Decimal,
        currency: str = "SAR",
        is_paid: bool = True,
        decision_id: uuid.UUID | None = None,
        effect_id: uuid.UUID | None = None,
    ) -> FinancialTransaction:
        """Post the standard journal entry for an order placement / sale."""
        # Ensure default accounts exist
        await FinancialService.seed_default_chart_of_accounts(session, tenant_id, currency=currency)

        entries: list[EntryCreate] = []

        # Debit: Cash & Bank if paid, else Accounts Receivable
        debit_account = "1010" if is_paid else "1200"
        entries.append(
            EntryCreate(
                account_code=debit_account,
                entry_type="DEBIT",
                amount=total,
                memo=f"Order {order_id} total payment / receivable",
            )
        )

        # Credit: Sales Revenue
        entries.append(
            EntryCreate(
                account_code="4010",
                entry_type="CREDIT",
                amount=subtotal,
                memo=f"Order {order_id} product revenue",
            )
        )

        # Credit: Shipping Revenue (if applicable)
        if shipping > Decimal("0.0000"):
            entries.append(
                EntryCreate(
                    account_code="4020",
                    entry_type="CREDIT",
                    amount=shipping,
                    memo=f"Order {order_id} shipping income",
                )
            )

        # Credit: VAT / Sales Tax Payable (if applicable)
        if tax > Decimal("0.0000"):
            entries.append(
                EntryCreate(
                    account_code="2100",
                    entry_type="CREDIT",
                    amount=tax,
                    memo=f"Order {order_id} sales tax payable",
                )
            )

        return await FinancialService.post_transaction(
            session,
            tenant_id,
            reference_type="order",
            reference_id=order_id,
            currency=currency,
            entries=entries,
            decision_id=decision_id,
            effect_id=effect_id,
            description=f"Revenue recognition for order {order_id}",
        )

    @staticmethod
    async def post_refund(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        refund_id: uuid.UUID,
        order_id: uuid.UUID,
        total_refund: Decimal,
        tax_refunded: Decimal = Decimal("0.0000"),
        currency: str = "SAR",
        decision_id: uuid.UUID | None = None,
        effect_id: uuid.UUID | None = None,
    ) -> FinancialTransaction:
        """Post journal entry for a customer refund."""
        await FinancialService.seed_default_chart_of_accounts(session, tenant_id, currency=currency)

        entries: list[EntryCreate] = []
        product_refund = total_refund - tax_refunded

        # Debit: Sales Returns / Discounts (or debit revenue)
        entries.append(
            EntryCreate(
                account_code="4010",
                entry_type="DEBIT",
                amount=product_refund,
                memo=f"Refund {refund_id} for order {order_id}",
            )
        )

        # Debit: VAT Payable (reversing output tax)
        if tax_refunded > Decimal("0.0000"):
            entries.append(
                EntryCreate(
                    account_code="2100",
                    entry_type="DEBIT",
                    amount=tax_refunded,
                    memo=f"Tax adjustment for refund {refund_id}",
                )
            )

        # Credit: Cash & Bank
        entries.append(
            EntryCreate(
                account_code="1010",
                entry_type="CREDIT",
                amount=total_refund,
                memo=f"Disbursement for refund {refund_id}",
            )
        )

        return await FinancialService.post_transaction(
            session,
            tenant_id,
            reference_type="refund",
            reference_id=refund_id,
            currency=currency,
            entries=entries,
            decision_id=decision_id,
            effect_id=effect_id,
            description=f"Refund processed for order {order_id}",
        )

    @staticmethod
    async def get_trial_balance(
        session: AsyncSession, tenant_id: uuid.UUID, currency: str = "SAR"
    ) -> TrialBalanceOut:
        """Generate a complete Trial Balance aggregating debits and credits per account."""
        accounts = (
            (
                await session.execute(
                    select(ChartOfAccount)
                    .where(
                        ChartOfAccount.tenant_id == tenant_id,
                        ChartOfAccount.is_active.is_(True),
                    )
                    .order_by(ChartOfAccount.code)
                )
            )
            .scalars()
            .all()
        )

        items: list[TrialBalanceItem] = []
        grand_debits = Decimal("0.0000")
        grand_credits = Decimal("0.0000")

        for acc in accounts:
            debit_sum = (
                await session.scalar(
                    select(func.coalesce(func.sum(FinancialEntry.amount), 0)).where(
                        FinancialEntry.tenant_id == tenant_id,
                        FinancialEntry.account_id == acc.account_id,
                        FinancialEntry.entry_type == "DEBIT",
                    )
                )
            ) or Decimal("0.0000")

            credit_sum = (
                await session.scalar(
                    select(func.coalesce(func.sum(FinancialEntry.amount), 0)).where(
                        FinancialEntry.tenant_id == tenant_id,
                        FinancialEntry.account_id == acc.account_id,
                        FinancialEntry.entry_type == "CREDIT",
                    )
                )
            ) or Decimal("0.0000")

            debit_sum = Decimal(str(debit_sum))
            credit_sum = Decimal(str(credit_sum))
            grand_debits += debit_sum
            grand_credits += credit_sum

            # For ASSET and EXPENSE: normal balance is DEBIT (debit - credit)
            # For LIABILITY, EQUITY, REVENUE: normal balance is CREDIT (credit - debit)
            if acc.account_type in ("ASSET", "EXPENSE"):
                net = debit_sum - credit_sum
            else:
                net = credit_sum - debit_sum

            items.append(
                TrialBalanceItem(
                    account_id=acc.account_id,
                    code=acc.code,
                    name=acc.name,
                    account_type=acc.account_type,
                    total_debit=debit_sum,
                    total_credit=credit_sum,
                    net_balance=net,
                )
            )

        return TrialBalanceOut(
            tenant_id=tenant_id,
            currency=currency,
            generated_at=datetime.now(UTC),
            items=items,
            total_debits=grand_debits,
            total_credits=grand_credits,
            is_balanced=(grand_debits == grand_credits),
        )

    @staticmethod
    def get_payment_adapter() -> PaymentPort:
        """Return the active payment adapter (Sandbox by default)."""
        return SandboxPaymentAdapter()
