"""Tests for Financial Double-Entry Ledger and PaymentPort (V12 Wave C §31).

Unit tests using in-memory mock session and zero-network sandbox adapter:
- Strict invariant: SUM(debits) == SUM(credits)
- Order sale double-entry posting rules
- Refund double-entry posting rules
- Sandbox payment processing: success, decline, and ambiguous timeout
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.core.errors import ConflictError, ValidationError
from app.modules.financial.models import ChartOfAccount
from app.modules.financial.ports import SandboxPaymentAdapter
from app.modules.financial.schemas import EntryCreate
from app.modules.financial.service import FinancialService

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def test_validate_balanced_accepts_equal_debits_and_credits():
    entries = [
        EntryCreate(account_code="1010", entry_type="DEBIT", amount=Decimal("115.00")),
        EntryCreate(account_code="4010", entry_type="CREDIT", amount=Decimal("100.00")),
        EntryCreate(account_code="2100", entry_type="CREDIT", amount=Decimal("15.00")),
    ]
    # Must not raise
    FinancialService.validate_balanced(entries)


def test_validate_balanced_rejects_unbalanced_entries():
    entries = [
        EntryCreate(account_code="1010", entry_type="DEBIT", amount=Decimal("115.00")),
        EntryCreate(account_code="4010", entry_type="CREDIT", amount=Decimal("100.00")),
        # Missing 15.00 credit!
    ]
    with pytest.raises(ConflictError) as exc_info:
        FinancialService.validate_balanced(entries)

    assert "unbalanced" in str(exc_info.value).lower()
    assert "115" in str(exc_info.value)
    assert "100" in str(exc_info.value)


class _MockFinancialSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.accounts: dict[str, ChartOfAccount] = {}

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, ChartOfAccount):
            self.accounts[obj.code] = obj

    async def flush(self) -> None:
        pass

    async def scalar(self, stmt: Any) -> Any:
        try:
            params = stmt.compile().params
            for p_val in params.values():
                if isinstance(p_val, str) and p_val in self.accounts:
                    return self.accounts[p_val]
        except Exception:
            pass
        return None


@pytest.mark.asyncio
async def test_post_order_sale_generates_balanced_entries():
    session = _MockFinancialSession()
    order_id = uuid.uuid4()

    tx = await FinancialService.post_order_sale(
        session,  # type: ignore[arg-type]
        TENANT_ID,
        order_id=order_id,
        subtotal=Decimal("200.0000"),
        shipping=Decimal("20.0000"),
        tax=Decimal("33.0000"),
        total=Decimal("253.0000"),
        currency="SAR",
        is_paid=True,
    )

    assert tx.reference_type == "order"
    assert tx.reference_id == order_id
    assert tx.status == "POSTED"

    # Verify all created entries are balanced
    entry_rows = [obj for obj in session.added if hasattr(obj, "entry_type")]
    assert len(entry_rows) == 4  # Cash, Revenue, Shipping, VAT

    debits = sum(e.amount for e in entry_rows if e.entry_type == "DEBIT")
    credits = sum(e.amount for e in entry_rows if e.entry_type == "CREDIT")
    assert debits == Decimal("253.0000")
    assert credits == Decimal("253.0000")


@pytest.mark.asyncio
async def test_post_refund_generates_balanced_entries():
    session = _MockFinancialSession()
    order_id = uuid.uuid4()
    refund_id = uuid.uuid4()

    tx = await FinancialService.post_refund(
        session,  # type: ignore[arg-type]
        TENANT_ID,
        refund_id=refund_id,
        order_id=order_id,
        total_refund=Decimal("115.0000"),
        tax_refunded=Decimal("15.0000"),
        currency="SAR",
    )

    assert tx.reference_type == "refund"
    assert tx.reference_id == refund_id

    entry_rows = [obj for obj in session.added if hasattr(obj, "entry_type")]
    debits = sum(e.amount for e in entry_rows if e.entry_type == "DEBIT")
    credits = sum(e.amount for e in entry_rows if e.entry_type == "CREDIT")
    assert debits == Decimal("115.0000")
    assert credits == Decimal("115.0000")


@pytest.mark.asyncio
async def test_sandbox_payment_adapter_flow():
    adapter = SandboxPaymentAdapter(fee_percentage=Decimal("0.02"))

    # 1. Successful charge
    res_success = await adapter.charge(
        TENANT_ID,
        amount=Decimal("500.00"),
        currency="SAR",
        source_token="tok_success_visa",
        reference_id=uuid.uuid4(),
    )
    assert res_success.status == "SUCCEEDED"
    assert res_success.fee_amount == Decimal("10.0000")  # 2% of 500
    assert res_success.provider_reference.startswith("sbx_ch_")

    # 2. Declined charge
    res_decline = await adapter.charge(
        TENANT_ID,
        amount=Decimal("100.00"),
        currency="SAR",
        source_token="tok_decline_card",
        reference_id=uuid.uuid4(),
    )
    assert res_decline.status == "FAILED"
    assert res_decline.error_code == "card_declined"

    # 3. Ambiguous charge (timeout simulation)
    res_timeout = await adapter.charge(
        TENANT_ID,
        amount=Decimal("250.00"),
        currency="SAR",
        source_token="tok_timeout_upstream",
        reference_id=uuid.uuid4(),
    )
    assert res_timeout.status == "AMBIGUOUS"
    assert res_timeout.error_code == "gateway_timeout"

    # 4. Verify ambiguous charge -> resolves to SUCCEEDED
    verified = await adapter.verify(TENANT_ID, provider_reference=res_timeout.provider_reference)
    assert verified.status == "SUCCEEDED"
    assert verified.amount == Decimal("250.00")

    # 5. Refund successful charge
    res_refund = await adapter.refund(
        TENANT_ID,
        provider_reference=res_success.provider_reference,
        amount=Decimal("500.00"),
        currency="SAR",
        reason="customer_request",
    )
    assert res_refund.status == "SUCCEEDED"
    assert res_refund.provider_reference.startswith("sbx_rf_")


@pytest.mark.asyncio
async def test_create_account_validation():
    session = _MockFinancialSession()

    # Invalid account_type
    with pytest.raises(ValidationError):
        await FinancialService.create_account(
            session,  # type: ignore[arg-type]
            TENANT_ID,
            code="9999",
            name="Bogus Account",
            account_type="INVALID_TYPE",
        )

    # Valid account creation
    acc = await FinancialService.create_account(
        session,  # type: ignore[arg-type]
        TENANT_ID,
        code="1020",
        name="Petty Cash",
        account_type="ASSET",
    )
    assert acc.code == "1020"
    assert acc.account_type == "ASSET"

    # Duplicate code
    with pytest.raises(ConflictError):
        await FinancialService.create_account(
            session,  # type: ignore[arg-type]
            TENANT_ID,
            code="1020",
            name="Petty Cash Duplicate",
            account_type="ASSET",
        )
