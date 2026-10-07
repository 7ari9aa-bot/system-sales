"""M5 — conversions were unreachable and unguarded.

`MarketingService.record_conversion` existed with no route in front of it, so the
conversion data every ROAS/attribution figure divides by could only be written by
a backfill; and it had no dedupe of any kind, so a replayed order event booked the
same order twice — which inflates the conversion count AND the credited revenue.

Idempotence needs a uniqueness guarantee at the database (a SELECT-then-INSERT
check races two retries into two rows), and the API needs to answer a duplicate
with 409, not a 500 from a raw IntegrityError.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.customers.models import Customer
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.marketing.models import Attribution, Conversion
from app.modules.marketing.service import MarketingService
from app.modules.orders.models import Order


def test_conversion_routes_are_registered() -> None:
    """DB-free: the read surface this gap is about simply did not exist."""
    paths = set(create_app().openapi()["paths"])
    assert "/api/v1/marketing/conversions" in paths
    assert "/api/v1/marketing/campaigns/{campaign_id}/conversions" in paths


async def _order(db: AsyncSession, tenant_id: uuid.UUID) -> Order:
    customer = Customer(tenant_id=tenant_id, name="Conversion Customer")
    db.add(customer)
    await db.flush()
    order = Order(
        tenant_id=tenant_id,
        number=f"SO-{uuid.uuid4().hex[:10].upper()}",
        customer_id=customer.id,
        status="pending",
        grand_total=250,
    )
    db.add(order)
    await db.flush()
    return order


async def test_the_database_refuses_two_purchase_conversions_for_one_order(
    db: AsyncSession, tenant_ctx
) -> None:
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)

    first = await MarketingService.record_conversion(
        db, tenant_id, order_id=order.id, type="purchase", value=250
    )
    await db.flush()

    async with db.begin_nested():
        db.add(
            Conversion(
                tenant_id=tenant_id,
                order_id=order.id,
                type="purchase",
                value=250,
                occurred_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
    # An aborted savepoint must not have eaten the accepted row.
    count = (
        await db.execute(
            select(func.count())
            .select_from(Conversion)
            .where(Conversion.tenant_id == tenant_id, Conversion.order_id == order.id)
        )
    ).scalar_one()
    assert count == 1
    assert first.order_id == order.id


async def test_a_second_order_may_still_convert_and_a_null_order_is_not_capped(
    db: AsyncSession, tenant_ctx
) -> None:
    """The key is per order, not per tenant — anonymous conversions stay legal."""
    tenant_id = tenant_ctx.tenant_id
    order_a = await _order(db, tenant_id)
    order_b = await _order(db, tenant_id)

    await MarketingService.record_conversion(
        db, tenant_id, order_id=order_a.id, type="purchase", value=10
    )
    second = await MarketingService.record_conversion(
        db, tenant_id, order_id=order_b.id, type="purchase", value=20
    )
    anonymous = await MarketingService.record_conversion(db, tenant_id, type="signup", value=None)
    other_type = await MarketingService.record_conversion(
        db, tenant_id, order_id=order_a.id, type="lead", value=None
    )
    await db.flush()

    assert second.order_id == order_b.id
    assert anonymous.order_id is None
    assert other_type.order_id == order_a.id
    total = (
        await db.execute(
            select(func.count()).select_from(Conversion).where(Conversion.tenant_id == tenant_id)
        )
    ).scalar_one()
    assert total == 4


async def test_recording_a_conversion_is_idempotent_when_asked(
    db: AsyncSession, tenant_ctx
) -> None:
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await MarketingService.record_touchpoint(
        db, tenant_id, customer_id=order.customer_id, source="facebook"
    )

    created = await MarketingService.record_conversion(
        db, tenant_id, order_id=order.id, customer_id=order.customer_id, value=250
    )
    replay = await MarketingService.record_conversion(
        db,
        tenant_id,
        order_id=order.id,
        customer_id=order.customer_id,
        value=250,
        idempotent=True,
    )
    await db.flush()

    assert replay.id == created.id
    attributed = (
        await db.execute(
            select(func.count())
            .select_from(Attribution)
            .where(Attribution.tenant_id == tenant_id, Attribution.conversion_id == created.id)
        )
    ).scalar_one()
    assert attributed == 2  # first + last view of ONE credited order, not two orders


async def test_a_replayed_conversion_raises_a_conflict_not_a_double_row(
    db: AsyncSession, tenant_ctx
) -> None:
    from app.core.errors import ConflictError

    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await MarketingService.record_conversion(
        db, tenant_id, order_id=order.id, type="purchase", value=250
    )

    with pytest.raises(ConflictError):
        await MarketingService.record_conversion(
            db, tenant_id, order_id=order.id, type="purchase", value=250
        )


# ------------------------------------------------------------- the API -----


def _client(db: AsyncSession, tenant_ctx, perms: set[str]) -> AsyncClient:
    app: FastAPI = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(
                id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner"
            ),
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
            permission_codes=perms,
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_posting_the_same_order_twice_answers_409_not_500(
    db: AsyncSession, tenant_ctx
) -> None:
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    async with _client(db, tenant_ctx, {"marketing:write"}) as client:
        body = {"order_id": str(order.id), "type": "purchase", "value": "250.00"}
        created = await client.post("/api/v1/marketing/conversions", json=body)
        assert created.status_code == 201, created.text
        replay = await client.post("/api/v1/marketing/conversions", json=body)

    assert replay.status_code == 409, replay.text
    assert replay.json()["error"]["code"] == "conflict"


async def test_a_campaign_lists_its_conversions_and_another_tenant_sees_none(
    db: AsyncSession, tenant_ctx
) -> None:
    tenant_id = tenant_ctx.tenant_id
    campaign = await MarketingService.create_campaign(
        db, tenant_id, name="Listing Camp", provider="facebook"
    )
    other_campaign = await MarketingService.create_campaign(
        db, tenant_id, name="Not This One", provider="google"
    )
    customer = Customer(tenant_id=tenant_id, name="Listed Customer")
    db.add(customer)
    await db.flush()

    await MarketingService.record_touchpoint(
        db, tenant_id, customer_id=customer.id, source="facebook", campaign_id=campaign.id
    )
    await MarketingService.record_touchpoint(
        db, tenant_id, customer_id=customer.id, source="google", campaign_id=other_campaign.id
    )
    in_scope = await MarketingService.record_conversion(
        db, tenant_id, customer_id=customer.id, value=300
    )
    await MarketingService.record_conversion(db, tenant_id, value=99)  # no touchpoint
    await db.flush()

    async with _client(db, tenant_ctx, set()) as client:
        listed = await client.get(f"/api/v1/marketing/campaigns/{campaign.id}/conversions")
        foreign = await client.get(f"/api/v1/marketing/campaigns/{uuid.uuid4()}/conversions")

    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert [i["id"] for i in items] == [str(in_scope.id)]
    # An amount crosses as a Decimal string (ADR-001/§47), not a float64.
    assert items[0]["value"] == "300.00"
    assert items[0]["currency"]  # every money figure names its currency
    # The row says which VIEWs of this conversion credit the campaign.
    assert items[0]["attribution_models"] == ["first_touch"]
    assert foreign.status_code == 404
