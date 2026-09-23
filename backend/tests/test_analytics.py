"""Analytics tests — orders summary, revenue by source/campaign, ROAS, daily
orders. Seeds: one campaign, one customer, two placed orders each with a
captured payment, one facebook touchpoint linked to the campaign, one 150 EGP
conversion attributed to it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import Customer
from app.modules.marketing import analytics
from app.modules.marketing.service import MarketingService
from app.modules.orders.models import Order, OrderPayment


@pytest.fixture
async def analytics_seed(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id

    campaign = await MarketingService.create_campaign(
        db, tenant_id, name="Ramadan Sale", provider="facebook", budget=100
    )
    customer = Customer(tenant_id=tenant_id, name="Analytics Customer")
    db.add(customer)
    await db.flush()

    now = datetime.now(UTC)
    order_100 = Order(
        tenant_id=tenant_id,
        number=f"SO-{uuid.uuid4().hex[:10].upper()}",
        customer_id=customer.id,
        status="completed",
        grand_total=Decimal("100.00"),
        placed_at=now,
    )
    order_50 = Order(
        tenant_id=tenant_id,
        number=f"SO-{uuid.uuid4().hex[:10].upper()}",
        customer_id=customer.id,
        status="completed",
        grand_total=Decimal("50.00"),
        placed_at=now,
    )
    db.add_all([order_100, order_50])
    await db.flush()
    # §55: "revenue" is captured money, not order totals — the seed has to carry
    # payments or the read models it feeds would correctly report nothing.
    db.add_all(
        [
            OrderPayment(
                tenant_id=tenant_id,
                order_id=order_100.id,
                method="cash",
                status="captured",
                amount=Decimal("100.00"),
                paid_at=now,
            ),
            OrderPayment(
                tenant_id=tenant_id,
                order_id=order_50.id,
                method="cash",
                status="captured",
                amount=Decimal("50.00"),
                paid_at=now,
            ),
        ]
    )
    await db.flush()

    await MarketingService.record_touchpoint(
        db, tenant_id, customer_id=customer.id, source="facebook", campaign_id=campaign.id
    )
    conversion = await MarketingService.record_conversion(
        db, tenant_id, customer_id=customer.id, order_id=order_100.id, value=150
    )
    await db.flush()
    return {
        "tenant_id": tenant_id,
        "campaign": campaign,
        "customer": customer,
        "order_100": order_100,
        "order_50": order_50,
        "conversion": conversion,
    }


async def test_orders_summary(db: AsyncSession, analytics_seed):
    """M7/§55: the summary names each money family instead of one "revenue"."""
    summary = await analytics.orders_summary(db, analytics_seed["tenant_id"])
    assert summary["orders_count"] == 2
    assert summary["gross_revenue"] == pytest.approx(150.0)
    assert summary["refunded_amount"] == pytest.approx(0.0)
    assert summary["net_revenue"] == pytest.approx(150.0)
    assert summary["gross_aov"] == pytest.approx(75.0)
    assert summary["net_aov"] == pytest.approx(75.0)
    assert summary["refund_excess"] == pytest.approx(0.0)


async def test_revenue_by_source(db: AsyncSession, analytics_seed):
    rows = await analytics.revenue_by_source(db, analytics_seed["tenant_id"])
    facebook = [row for row in rows if row["source"] == "facebook"]
    assert len(facebook) == 1
    assert facebook[0]["revenue"] == pytest.approx(150.0)
    assert facebook[0]["conversions"] == 1


async def test_revenue_by_campaign(db: AsyncSession, analytics_seed):
    rows = await analytics.revenue_by_campaign(db, analytics_seed["tenant_id"])
    target = [row for row in rows if row["campaign_id"] == analytics_seed["campaign"].id]
    assert len(target) == 1
    assert target[0]["campaign_name"] == "Ramadan Sale"
    assert target[0]["revenue"] == pytest.approx(150.0)
    assert target[0]["conversions"] == 1


async def test_campaign_roas_names_its_own_denominator(db: AsyncSession, analytics_seed):
    """M5: `budget` is what was PLANNED, not what was burned.

    The row may report a return on the plan, but it must say so and must not
    hand the plan to the caller under the name "spend".
    """
    rows = await analytics.campaign_budget_roas(db, analytics_seed["tenant_id"])
    target = [row for row in rows if row["campaign_id"] == analytics_seed["campaign"].id]
    assert len(target) == 1
    row = target[0]
    assert row["name"] == "Ramadan Sale"
    assert row["revenue"] == pytest.approx(150.0)
    assert row["planned_budget"] == pytest.approx(100.0)
    assert row["budget_roas"] == pytest.approx(1.5)
    assert row["basis"] == analytics.BASIS_PLANNED_BUDGET
    # No spend feed exists in this schema, so the honest answer is "none".
    assert row["actual_spend"] is None
    assert row["spend_roas"] is None


async def test_a_spend_feed_is_the_only_thing_that_can_produce_spend_roas():
    """The seam is one function; nothing else may invent burned money."""
    row = analytics.roas_row(
        campaign_id=None,
        name="c",
        revenue=Decimal("150.00"),
        planned_budget=Decimal("100.00"),
    )
    assert row["basis"] == analytics.BASIS_PLANNED_BUDGET
    assert row["spend_roas"] is None
    burned = analytics.roas_row(
        campaign_id=None,
        name="c",
        revenue=Decimal("150.00"),
        planned_budget=Decimal("100.00"),
        actual_spend=Decimal("50.00"),
    )
    assert burned["basis"] == analytics.BASIS_ACTUAL_SPEND
    assert burned["budget_roas"] == pytest.approx(1.5)
    assert burned["spend_roas"] == pytest.approx(3.0)


async def test_daily_orders(db: AsyncSession, analytics_seed):
    rows = await analytics.daily_orders(db, analytics_seed["tenant_id"])
    assert len(rows) == 1  # both orders placed "now" land on the same day
    assert rows[0]["orders"] == 2
    assert rows[0]["gross_revenue"] == pytest.approx(150.0)
    assert rows[0]["net_revenue"] == pytest.approx(150.0)
    assert rows[0]["refunded_amount"] == pytest.approx(0.0)
