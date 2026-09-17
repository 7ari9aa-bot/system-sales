"""Analytics tests — orders summary, revenue by source/campaign, ROAS, daily
orders. Seeds: one campaign, one customer, two orders, one facebook touchpoint
linked to the campaign, one 150 EGP conversion attributed to it."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import Customer
from app.modules.marketing import analytics
from app.modules.marketing.service import MarketingService
from app.modules.orders.models import Order


@pytest.fixture
async def analytics_seed(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id

    campaign = await MarketingService.create_campaign(
        db, tenant_id, name="Ramadan Sale", provider="facebook", budget=100
    )
    customer = Customer(tenant_id=tenant_id, name="Analytics Customer")
    db.add(customer)
    await db.flush()

    order_100 = Order(
        tenant_id=tenant_id,
        number=f"SO-{uuid.uuid4().hex[:10].upper()}",
        customer_id=customer.id,
        status="pending",
        grand_total=100,
    )
    order_50 = Order(
        tenant_id=tenant_id,
        number=f"SO-{uuid.uuid4().hex[:10].upper()}",
        customer_id=customer.id,
        status="pending",
        grand_total=50,
    )
    db.add_all([order_100, order_50])
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
    summary = await analytics.orders_summary(db, analytics_seed["tenant_id"])
    assert summary["orders_count"] == 2
    assert summary["revenue"] == pytest.approx(150.0)
    assert summary["aov"] == pytest.approx(75.0)


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


async def test_campaign_roas(db: AsyncSession, analytics_seed):
    rows = await analytics.campaign_roas(db, analytics_seed["tenant_id"])
    target = [row for row in rows if row["campaign_id"] == analytics_seed["campaign"].id]
    assert len(target) == 1
    assert target[0]["name"] == "Ramadan Sale"
    assert target[0]["spend"] == pytest.approx(100.0)
    assert target[0]["revenue"] == pytest.approx(150.0)
    assert target[0]["roas"] == pytest.approx(1.5)


async def test_daily_orders(db: AsyncSession, analytics_seed):
    rows = await analytics.daily_orders(db, analytics_seed["tenant_id"])
    assert len(rows) == 1  # both orders placed "now" land on the same day
    assert rows[0]["orders"] == 2
    assert rows[0]["revenue"] == pytest.approx(150.0)
