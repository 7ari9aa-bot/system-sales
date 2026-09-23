"""MarketingService tests — campaigns, touchpoint capture, first/last-touch
attribution, leads."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.modules.customers.models import Customer
from app.modules.marketing.models import Attribution
from app.modules.marketing.service import MarketingService


async def _customer(db: AsyncSession, tenant_id: uuid.UUID, name: str) -> Customer:
    customer = Customer(tenant_id=tenant_id, name=name)
    db.add(customer)
    await db.flush()
    return customer


async def _attributions(
    db: AsyncSession, tenant_id: uuid.UUID, conversion_id: uuid.UUID
) -> list[Attribution]:
    return list(
        (
            await db.execute(
                select(Attribution).where(
                    Attribution.tenant_id == tenant_id,
                    Attribution.conversion_id == conversion_id,
                )
            )
        )
        .scalars()
        .all()
    )


async def test_create_campaign_defaults_and_tenant_guard(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id

    campaign = await MarketingService.create_campaign(
        db, tenant_id, name="Ramadan Sale", provider="facebook", budget=100
    )
    assert campaign.status == "draft"
    assert campaign.provider == "facebook"
    assert float(campaign.budget) == 100

    # Tenant guard: another tenant cannot see it.
    with pytest.raises(NotFoundError):
        await MarketingService.get_campaign(db, uuid.uuid4(), campaign.id)
    assert (await MarketingService.get_campaign(db, tenant_id, campaign.id)).id == campaign.id

    listed = await MarketingService.list_campaigns(db, tenant_id)
    assert [c.id for c in listed] == [campaign.id]
    assert await MarketingService.list_campaigns(db, uuid.uuid4()) == []

    # Invalid provider is rejected in the service.
    with pytest.raises(ValidationError):
        await MarketingService.create_campaign(db, tenant_id, name="X", provider="pigeon")
    await db.flush()


async def test_first_and_last_touch_attribution(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id, "Attributed Customer")

    facebook_tp = await MarketingService.record_touchpoint(
        db, tenant_id, customer_id=customer.id, source="facebook", medium="cpc"
    )
    google_tp = await MarketingService.record_touchpoint(
        db, tenant_id, customer_id=customer.id, source="google", medium="cpc"
    )
    conversion = await MarketingService.record_conversion(
        db, tenant_id, customer_id=customer.id, value=200
    )

    rows = await _attributions(db, tenant_id, conversion.id)
    assert len(rows) == 2
    by_model = {row.model: row for row in rows}
    assert set(by_model) == {"first_touch", "last_touch"}
    assert by_model["first_touch"].touchpoint_id == facebook_tp.id
    assert by_model["last_touch"].touchpoint_id == google_tp.id
    assert float(by_model["first_touch"].weight) == 1.0
    assert float(by_model["last_touch"].weight) == 1.0
    assert float(by_model["first_touch"].credited_value) == 200
    assert float(by_model["last_touch"].credited_value) == 200
    # ...which is TWO VIEWS of one 200 order, not 400 of revenue: each model is
    # complete on its own, so a rollup filters to one (§167).
    for model in sorted({r.model for r in rows}):
        same_model = [r for r in rows if r.model == model]
        assert sum(float(r.credited_value) for r in same_model) == pytest.approx(200.0)
    await db.flush()


async def test_conversion_without_touchpoints_stands_alone(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id, "Never Touched")

    conversion = await MarketingService.record_conversion(
        db, tenant_id, customer_id=customer.id, order_id=None, value=75
    )
    assert await _attributions(db, tenant_id, conversion.id) == []

    # Anonymous conversion (no customer at all) also has no attribution.
    anonymous = await MarketingService.record_conversion(db, tenant_id, value=10)
    assert await _attributions(db, tenant_id, anonymous.id) == []
    await db.flush()


async def test_lead_status_transitions(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    campaign = await MarketingService.create_campaign(db, tenant_id, name="Leads Camp")

    lead = await MarketingService.create_lead(
        db,
        tenant_id,
        name="Ali Hassan",
        phone="+201000000001",
        email="ali@test.local",
        source="facebook",
        campaign_id=campaign.id,
    )
    assert lead.status == "new"

    contacted = await MarketingService.update_lead_status(db, tenant_id, lead.id, "contacted")
    assert contacted.status == "contacted"

    converted = await MarketingService.update_lead_status(db, tenant_id, lead.id, "converted")
    assert converted.status == "converted"

    # Unknown status -> ValidationError; lead row keeps its previous status.
    with pytest.raises(ValidationError):
        await MarketingService.update_lead_status(db, tenant_id, lead.id, "maybe")
    assert lead.status == "converted"

    # Tenant guard on leads too.
    with pytest.raises(NotFoundError):
        await MarketingService.update_lead_status(db, uuid.uuid4(), lead.id, "lost")
    await db.flush()
