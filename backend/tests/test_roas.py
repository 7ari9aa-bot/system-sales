"""M5 / §167 — a ROAS figure must name its own denominator.

§167 (docs/spec/ARCHITECTURE_PATCH_125-177.txt:1994, "METRIC DEFINITIONS") demands
one definition per metric carrying an explicit ``source``. This schema records a
*planned* ``campaigns.budget``, has no burned-spend column, and has no channel
delivery-metrics sync — so a field literally named ``spend`` was a false claim:
budget is what was planned, spend is what was burned.

These tests pin the honest shape: every ratio says which denominator produced it,
a zero or missing denominator yields ``None`` rather than 0.0 or a crash, and the
single seam through which real spend would ever enter is named and empty.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.customers.models import Customer
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.marketing import analytics
from app.modules.marketing.service import MarketingService

_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# 1. The row builder (DB-free — this is the labelling contract itself)
# ---------------------------------------------------------------------------


def test_a_budget_denominator_is_labelled_as_a_plan_and_never_called_spend() -> None:
    row = analytics.roas_row(
        campaign_id=_ID,
        name="Ramadan Sale",
        revenue=Decimal("150.00"),
        planned_budget=Decimal("100.00"),
    )

    assert row["basis"] == "planned_budget"
    assert row["planned_budget"] == pytest.approx(100.0)
    assert row["budget_roas"] == pytest.approx(1.5)
    # Nothing here pretends to have been burned.
    assert row["actual_spend"] is None
    assert row["spend_roas"] is None
    assert "spend" not in row
    assert "roas" not in row


def test_a_zero_or_missing_budget_gives_no_ratio_instead_of_zero_or_a_crash() -> None:
    for budget in (Decimal("0.00"), None):
        row = analytics.roas_row(
            campaign_id=_ID,
            name="Unbudgeted",
            revenue=Decimal("150.00"),
            planned_budget=budget,
        )
        assert row["budget_roas"] is None, budget
        assert row["basis"] == "planned_budget"


def test_real_spend_supplied_to_the_seam_takes_over_the_ratio_and_the_label() -> None:
    row = analytics.roas_row(
        campaign_id=_ID,
        name="Ramadan Sale",
        revenue=Decimal("150.00"),
        planned_budget=Decimal("100.00"),
        actual_spend=Decimal("60.00"),
    )

    assert row["basis"] == "actual_spend"
    assert row["actual_spend"] == pytest.approx(60.0)
    assert row["spend_roas"] == pytest.approx(2.5)
    # The plan figure stays visible next to it — it is a different number.
    assert row["budget_roas"] == pytest.approx(1.5)


def test_a_zero_spend_denominator_is_also_guarded() -> None:
    row = analytics.roas_row(
        campaign_id=_ID,
        name="Not yet delivered",
        revenue=Decimal("150.00"),
        planned_budget=Decimal("100.00"),
        actual_spend=Decimal("0.00"),
    )
    assert row["spend_roas"] is None


# ---------------------------------------------------------------------------
# 2. The spend seam (CI Postgres): nothing in this schema has burned money
# ---------------------------------------------------------------------------


async def test_the_spend_seam_is_the_only_producer_and_is_currently_empty(
    db: AsyncSession, tenant_ctx
) -> None:
    campaign = await MarketingService.create_campaign(
        db, tenant_ctx.tenant_id, name="Budget Only", provider="facebook", budget=500
    )
    await db.flush()

    spend = await analytics.campaign_actual_spend(db, tenant_ctx.tenant_id, [campaign.id])
    assert spend == {}


async def test_campaign_budget_roas_reports_the_plan_basis_end_to_end(
    db: AsyncSession, tenant_ctx
) -> None:
    tenant_id = tenant_ctx.tenant_id
    campaign = await MarketingService.create_campaign(
        db, tenant_id, name="Ramadan Sale", provider="facebook", budget=100
    )
    customer = Customer(tenant_id=tenant_id, name="ROAS Customer")
    db.add(customer)
    await db.flush()

    await MarketingService.record_touchpoint(
        db, tenant_id, customer_id=customer.id, source="facebook", campaign_id=campaign.id
    )
    await MarketingService.record_conversion(db, tenant_id, customer_id=customer.id, value=150)
    await db.flush()

    rows = await analytics.campaign_budget_roas(db, tenant_id)
    row = next(r for r in rows if r["campaign_id"] == campaign.id)

    assert row["basis"] == "planned_budget"
    assert row["planned_budget"] == pytest.approx(100.0)
    assert row["revenue"] == pytest.approx(150.0)
    assert row["budget_roas"] == pytest.approx(1.5)
    assert row["actual_spend"] is None
    assert row["spend_roas"] is None
    assert "spend" not in row and "roas" not in row


async def test_the_summary_route_says_budget_roas_and_not_roas(
    db: AsyncSession, tenant_ctx
) -> None:
    """The mislabelling reached the API, so the API is where it has to stop."""
    tenant_id = tenant_ctx.tenant_id
    campaign = await MarketingService.create_campaign(
        db, tenant_id, name="Route Check", provider="facebook", budget=200
    )
    customer = Customer(tenant_id=tenant_id, name="Route Customer")
    db.add(customer)
    await db.flush()
    await MarketingService.record_touchpoint(
        db, tenant_id, customer_id=customer.id, source="facebook", campaign_id=campaign.id
    )
    await MarketingService.record_conversion(db, tenant_id, customer_id=customer.id, value=100)
    await db.flush()

    app: FastAPI = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(
                id=tenant_ctx.user.id, tenant_id=tenant_id, role_code="owner"
            ),
            tenant_id=tenant_id,
            role_code="owner",
            permission_codes=set(),
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/analytics/summary")

    assert response.status_code == 200, response.text
    body = response.json()
    assert "campaign_roas" not in body
    rows = body["campaign_budget_roas"]
    row = next(r for r in rows if r["campaign_id"] == str(campaign.id))
    assert row["basis"] == "planned_budget"
    assert row["budget_roas"] == pytest.approx(0.5)
