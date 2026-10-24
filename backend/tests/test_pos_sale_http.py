"""`POST /pos/registers/{id}/sales`: a sale over real HTTP, with no shift and no payment.

The real app, the real permission chain (`orders:write` as the DB grants it to each role) and the
real database. Only authentication and the tenant session are swapped, as in the other HTTP-surface
tests. The old payment fields are not part of this contract and must be refused, not ignored: a
client that still sends a `method` believes money is being handled.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.modules.identity.deps import get_db, get_tenant_ctx
from app.modules.inventory.models import InventoryBalance
from app.modules.orders.models import OrderPayment
from app.modules.pos.models import PosCashMovement
from app.modules.pos.service import PosService
from tests._pos_helpers import ctx_for, till, start_day

pytestmark = pytest.mark.asyncio


def _app(ctx):
    app = create_app()
    app.user_middleware = [
        m for m in app.user_middleware if m.cls not in {IdempotencyMiddleware, RateLimitMiddleware}
    ]
    app.middleware_stack = None

    async def _session():
        yield ctx.session

    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _session
    return app


async def _post(ctx, path, body):
    transport = ASGITransport(app=_app(ctx))
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.post(path, json=body)


async def _shop(db, tenant_ctx):
    shift, variant, customer = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id, counted_cash="0.00")
    await start_day(db, tenant_ctx, shift.register_id)
    return shift.register_id, variant, customer


async def test_a_sale_over_http_records_the_invoice_and_takes_the_stock(db, tenant_ctx) -> None:
    register_id, variant, customer = await _shop(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    before = (
        await db.execute(
            select(InventoryBalance.on_hand).where(InventoryBalance.variant_id == variant.id)
        )
    ).scalar_one()

    r = await _post(
        ctx,
        f"/api/v1/pos/registers/{register_id}/sales",
        {
            "items": [{"variant_id": str(variant.id), "quantity": 2}],
            "customer_id": str(customer.id),
        },
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["grand_total"] == "200.00"
    assert body["receipt_number"].startswith("POS-")
    after = (
        await db.execute(
            select(InventoryBalance.on_hand).where(InventoryBalance.variant_id == variant.id)
        )
    ).scalar_one()
    assert before - after == 2
    assert (await db.execute(select(func.count()).select_from(OrderPayment))).scalar_one() == 0
    assert (await db.execute(select(func.count()).select_from(PosCashMovement))).scalar_one() == 0


async def test_the_seller_on_the_receipt_is_the_caller_not_a_field_in_the_body(
    db, tenant_ctx
) -> None:
    register_id, variant, customer = await _shop(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    r = await _post(
        ctx,
        f"/api/v1/pos/registers/{register_id}/sales",
        {
            "items": [{"variant_id": str(variant.id), "quantity": 1}],
            "customer_id": str(customer.id),
        },
    )
    assert r.status_code == 201, r.text
    receipt = await PosService.get_receipt(db, tenant_ctx.tenant_id, r.json()["receipt_id"])
    assert receipt["receipt"]["sold_by_user_id"] == str(tenant_ctx.user.id)


@pytest.mark.parametrize(
    "extra",
    [
        {"method": "cash"},
        {"amount": "100.00"},
        {"tenders": [{"method": "cash", "amount": "100.00"}]},
        {"tendered_cash": "200.00"},
        {"sold_by_user_id": "00000000-0000-0000-0000-000000000001"},
    ],
)
async def test_payment_fields_and_a_forged_seller_are_refused_not_ignored(
    db, tenant_ctx, extra
) -> None:
    register_id, variant, customer = await _shop(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    r = await _post(
        ctx,
        f"/api/v1/pos/registers/{register_id}/sales",
        {
            "items": [{"variant_id": str(variant.id), "quantity": 1}],
            "customer_id": str(customer.id),
            **extra,
        },
    )
    assert r.status_code == 422, r.text
    assert (await db.execute(select(func.count()).select_from(OrderPayment))).scalar_one() == 0


async def test_a_caller_without_orders_write_cannot_sell(db, tenant_ctx) -> None:
    """Every seeded role holds `orders:write`, so the gate is proven with the grant removed."""
    register_id, variant, customer = await _shop(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "staff")
    ctx.permission_codes.discard("orders:write")
    r = await _post(
        ctx,
        f"/api/v1/pos/registers/{register_id}/sales",
        {
            "items": [{"variant_id": str(variant.id), "quantity": 1}],
            "customer_id": str(customer.id),
        },
    )
    assert r.status_code == 403, r.text
    assert (await db.execute(select(func.count()).select_from(OrderPayment))).scalar_one() == 0


async def test_an_empty_basket_and_an_unknown_register_are_refused(db, tenant_ctx) -> None:
    import uuid

    register_id, variant, customer = await _shop(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    empty = await _post(ctx, f"/api/v1/pos/registers/{register_id}/sales", {"items": []})
    assert empty.status_code == 422, empty.text
    ghost = await _post(
        ctx,
        f"/api/v1/pos/registers/{uuid.uuid4()}/sales",
        {
            "items": [{"variant_id": str(variant.id), "quantity": 1}],
            "customer_id": str(customer.id),
        },
    )
    assert ghost.status_code == 404, ghost.text


async def test_overselling_over_http_is_a_clear_conflict_not_a_500(db, tenant_ctx) -> None:
    register_id, variant, customer = await _shop(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    r = await _post(
        ctx,
        f"/api/v1/pos/registers/{register_id}/sales",
        {
            "items": [{"variant_id": str(variant.id), "quantity": 999}],
            "customer_id": str(customer.id),
        },
    )
    assert r.status_code in (409, 422), r.text
    assert r.status_code != 500


async def test_asking_for_the_session_never_opens_a_day(db, tenant_ctx) -> None:
    """Looking at the till must not start the day: the balance has to be entered first."""
    from app.modules.pos.models import PosSession

    shift, _variant, _customer = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id, counted_cash="0.00")
    ctx = await ctx_for(db, tenant_ctx, "owner")

    r = await _post(ctx, f"/api/v1/pos/registers/{shift.register_id}/working-session", {})

    assert r.status_code == 200, r.text
    assert r.json() == {"started": False, "session": None}
    open_now = (
        await db.execute(
            select(func.count())
            .select_from(PosSession)
            .where(PosSession.register_id == shift.register_id, PosSession.status == "OPEN")
        )
    ).scalar_one()
    assert open_now == 0, "a read must never open a day"


async def test_open_day_needs_a_balance_and_keeps_the_first_one(db, tenant_ctx) -> None:
    from app.modules.pos.models import PosSession

    shift, _variant, _customer = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id, counted_cash="0.00")
    ctx = await ctx_for(db, tenant_ctx, "owner")
    url = f"/api/v1/pos/registers/{shift.register_id}/open-day"

    for bad in ({}, {"opening_float": None}, {"opening_float": "-5"}, {"opening_float": "abc"}):
        refused = await _post(ctx, url, bad)
        assert refused.status_code == 422, (bad, refused.text)
    extra = await _post(ctx, url, {"opening_float": "10", "method": "card"})
    assert extra.status_code == 422, extra.text

    first = await _post(ctx, url, {"opening_float": "250.50"})
    second = await _post(ctx, url, {"opening_float": "999.00"})
    assert first.status_code == 201, first.text
    assert first.json()["started"] is True
    assert second.json()["session"]["id"] == first.json()["session"]["id"]
    row = (
        await db.execute(select(PosSession).where(PosSession.id == first.json()["session"]["id"]))
    ).scalar_one()
    assert str(row.opening_float) == "250.50", "the first figure stands; a second call never overwrites it"

    seen = await _post(ctx, f"/api/v1/pos/registers/{shift.register_id}/working-session", {})
    assert seen.json()["started"] is True
    assert seen.json()["session"]["id"] == first.json()["session"]["id"]


async def test_a_sale_is_refused_until_the_day_is_started(db, tenant_ctx) -> None:
    shift, variant, customer = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id, counted_cash="0.00")
    ctx = await ctx_for(db, tenant_ctx, "owner")
    body = {"items": [{"variant_id": str(variant.id), "quantity": 1}]}

    refused = await _post(ctx, f"/api/v1/pos/registers/{shift.register_id}/sales", body)
    assert refused.status_code == 409, refused.text
    assert "opening balance" in refused.text

    await start_day(db, tenant_ctx, shift.register_id, "100.00")
    ok = await _post(ctx, f"/api/v1/pos/registers/{shift.register_id}/sales", body)
    assert ok.status_code == 201, ok.text


async def test_working_session_needs_orders_write_and_a_real_register(db, tenant_ctx) -> None:
    import uuid

    register_id, _variant, _customer = await _shop(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "staff")
    ctx.permission_codes.discard("orders:write")
    denied = await _post(ctx, f"/api/v1/pos/registers/{register_id}/working-session", {})
    assert denied.status_code == 403, denied.text

    owner = await ctx_for(db, tenant_ctx, "owner")
    ghost = await _post(owner, f"/api/v1/pos/registers/{uuid.uuid4()}/working-session", {})
    assert ghost.status_code == 404, ghost.text
