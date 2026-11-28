"""Unit tests for tax rate resolution, effective dates, and invoice stamping."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.platform.billing.models import Invoice, TaxRate
from app.platform.billing.services.tax import (
    calculate_tax_amount,
    get_effective_tax_rate,
    resolve_applicable_tax_rate,
)


def test_calculate_tax_amount():
    # 14% on 100.00 EGP
    assert calculate_tax_amount(Decimal("100.00"), Decimal("0.1400")) == Decimal("14.00")
    # 15% on 250.00 SAR
    assert calculate_tax_amount(Decimal("250.00"), Decimal("0.1500")) == Decimal("37.50")
    # None / 0% tax (e.g. Qatar)
    assert calculate_tax_amount(Decimal("500.00"), None) == Decimal("0.00")
    assert calculate_tax_amount(Decimal("500.00"), Decimal("0.0000")) == Decimal("0.00")


@pytest.mark.asyncio
async def test_resolve_applicable_tax_rate_fallback():
    # When no DB session is provided, resolves from static CountrySpec
    rate_eg = await resolve_applicable_tax_rate(None, "EG")
    assert rate_eg == Decimal("0.14")

    rate_sa = await resolve_applicable_tax_rate(None, "SA")
    assert rate_sa == Decimal("0.15")

    rate_ae = await resolve_applicable_tax_rate(None, "AE")
    assert rate_ae == Decimal("0.05")

    # Qatar has tax_regime="none", so it must resolve to None, NOT 0% VAT
    rate_qa = await resolve_applicable_tax_rate(None, "QA")
    assert rate_qa is None

    # Unknown country
    assert await resolve_applicable_tax_rate(None, "XX") is None


@pytest.mark.asyncio
async def test_get_effective_tax_rate_from_db():
    # Mock session returning a TaxRate row
    mock_session = AsyncMock()
    mock_tax_rate = TaxRate(
        country_code="SA",
        rate=Decimal("0.1500"),
        effective_from=date(2020, 7, 1),
        effective_until=None,
        label_ar="ضريبة القيمة المضافة",
        label_en="VAT",
        is_active=True,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_tax_rate
    mock_session.execute.return_value = mock_result

    res = await get_effective_tax_rate(mock_session, "SA", as_of_date=date(2026, 1, 1))
    assert res is not None
    assert res.rate == Decimal("0.1500")
    assert res.country_code == "SA"


def test_invoice_model_has_tax_rate_applied():
    inv = Invoice(
        subtotal=Decimal("100.00"),
        tax=Decimal("14.00"),
        tax_rate_applied=Decimal("0.1400"),
        total=Decimal("114.00"),
        number="INV-2026-0001",
    )
    assert inv.tax_rate_applied == Decimal("0.1400")
    assert inv.tax == Decimal("14.00")
    assert inv.total == Decimal("114.00")
