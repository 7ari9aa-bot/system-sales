"""Tax calculation and statutory rate resolution with effective-date semantics.

Enforces:
1. Database-driven tax rates: Rates are looked up from `tax_rates` by country and date.
2. Historical immutability: Querying with `as_of_date` returns the rate legally in force.
3. CountrySpec fallback: Fallback to CountrySpec when DB is unavailable.
4. Non-taxable markets: Markets with tax_regime="none" (e.g. QA) resolve to None / 0 tax.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.country.registry import get_country
from app.modules.billing.models import TaxRate


async def get_effective_tax_rate(
    session: AsyncSession,
    country_code: str | None,
    *,
    as_of_date: date | None = None,
) -> TaxRate | None:
    """Retrieve the statutory TaxRate row active in a country as of a given date."""
    if not country_code:
        return None
    clean_code = country_code.strip().upper()
    target_date = as_of_date or date.today()

    stmt = (
        select(TaxRate)
        .where(
            TaxRate.country_code == clean_code,
            TaxRate.is_active.is_(True),
            TaxRate.effective_from <= target_date,
            or_(TaxRate.effective_until.is_(None), TaxRate.effective_until >= target_date),
        )
        .order_by(TaxRate.effective_from.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def resolve_applicable_tax_rate(
    session: AsyncSession | None,
    country_code: str | None,
    *,
    as_of_date: date | None = None,
) -> Decimal | None:
    """Resolve the numeric tax rate (e.g. Decimal('0.1400')) for a country on a date.

    Returns None if the market has no tax regime (e.g. Qatar) or rate is unspecified.
    """
    if not country_code:
        return None
    clean_code = country_code.strip().upper()

    # 1. Try DB lookup first when session is available
    if session is not None:
        try:
            db_rate = await get_effective_tax_rate(session, clean_code, as_of_date=as_of_date)
            if db_rate is not None:
                return Decimal(str(db_rate.rate))
        except Exception:
            pass  # Fall through to static spec fallback on DB disconnection / test mock

    # 2. Fall back to static CountrySpec
    spec = get_country(clean_code)
    if spec is None or spec.tax_regime == "none" or spec.tax_standard_rate is None:
        return None
    return Decimal(str(spec.tax_standard_rate))


def calculate_tax_amount(
    subtotal: Decimal,
    tax_rate: Decimal | None,
) -> Decimal:
    """Calculate the tax amount rounded to 2 decimal places."""
    if tax_rate is None or tax_rate <= 0:
        return Decimal("0.00")
    return (subtotal * tax_rate).quantize(Decimal("0.01"))
