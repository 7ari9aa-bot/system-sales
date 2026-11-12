"""Who did it: a return/exchange names its actor, and a day has a holder.

Found by driving the real HTTP surface as a plain `staff` cashier (no `pos:override`):

* the return receipt and the exchange's new-sale receipt were stored with ``sold_by = NULL`` and
  the ``pos.sale.returned`` / ``pos.sale.exchanged`` events carried no actor, so the first route
  to till fraud left no trail;
* ``open_day`` never set ``cashier_user_id``, so ``_ensure_holds_shift`` saw a drawer nobody holds
  and any ``orders:write`` user could close another cashier's day.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.modules.identity.deps import TenantContext, get_db, get_tenant_ctx
from app.modules.identity.models import User
from app.modules.pos.models import PosReceipt, PosSession
from app.modules.pos.service import PosService
from tests._pos_helpers import ctx_for, till

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


async def _call(ctx, method, path, body=None):
    async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as c:
        return await c.request(method, path, json=body)


async def _day(db, tenant_ctx):
    """A till whose day is opened over HTTP by plain staff user A (the real opening path)."""
    shift, variant, customer = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)
    staff_a = await ctx_for(db, tenant_ctx, "staff")
    r = await _call(
        staff_a,
        "POST",
        f"/api/v1/pos/registers/{shift.register_id}/open-day",
        {"opening_float": "0.00"},
    )
    assert r.status_code == 201, r.text
    return shift.register_id, r.json()["session"]["id"], variant, customer, staff_a


async def _sell(ctx, register_id, variant, customer, qty=2):
    r = await _call(
        ctx,
        "POST",
        f"/api/v1/pos/registers/{register_id}/sales",
        {
            "items": [{"variant_id": str(variant.id), "quantity": qty}],
            "customer_id": str(customer.id),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _staff_b(db, tenant_ctx, like):
    b = User(email=f"b-{uuid.uuid4().hex[:8]}@test.local", password_hash="x", full_name="Cashier B")
    db.add(b)
    await db.flush()
    return TenantContext(
        session=db,
        user=b,
        tenant_id=tenant_ctx.tenant_id,
        role_code="staff",
        permission_codes=like.permission_codes,
    ), b


async def test_the_day_is_held_by_whoever_opened_it(db, tenant_ctx) -> None:
    _, day_id, _, _, _ = await _day(db, tenant_ctx)
    row = (await db.execute(select(PosSession).where(PosSession.id == day_id))).scalar_one()
    assert row.cashier_user_id == tenant_ctx.user.id


async def test_another_plain_cashier_cannot_close_or_return_against_my_day(db, tenant_ctx) -> None:
    register_id, day_id, variant, customer, staff_a = await _day(db, tenant_ctx)
    sale = await _sell(staff_a, register_id, variant, customer)
    staff_b, _ = await _staff_b(db, tenant_ctx, staff_a)

    ret = await _call(
        staff_b,
        "POST",
        f"/api/v1/pos/sessions/{day_id}/returns",
        {
            "order_id": sale["order_id"],
            "lines": [{"variant_id": str(variant.id), "quantity": 1}],
            "restock": True,
        },
    )
    close = await _call(staff_b, "POST", f"/api/v1/pos/sessions/{day_id}/close")

    assert ret.status_code == 403, ret.text
    assert close.status_code == 403, close.text
    row = (await db.execute(select(PosSession).where(PosSession.id == day_id))).scalar_one()
    assert row.status == "OPEN"


async def test_a_manager_with_override_can_still_close_another_cashiers_day(db, tenant_ctx) -> None:
    register_id, day_id, variant, customer, staff_a = await _day(db, tenant_ctx)
    await _sell(staff_a, register_id, variant, customer)
    manager, _ = await _staff_b(db, tenant_ctx, await ctx_for(db, tenant_ctx, "manager"))

    close = await _call(manager, "POST", f"/api/v1/pos/sessions/{day_id}/close")

    assert close.status_code == 200, close.text


async def test_a_return_and_an_exchange_name_who_made_them(db, tenant_ctx) -> None:
    register_id, day_id, variant, customer, staff_a = await _day(db, tenant_ctx)
    sale = await _sell(staff_a, register_id, variant, customer)
    ret = await _call(
        staff_a,
        "POST",
        f"/api/v1/pos/sessions/{day_id}/returns",
        {
            "order_id": sale["order_id"],
            "lines": [{"variant_id": str(variant.id), "quantity": 1}],
            "restock": True,
        },
    )
    assert ret.status_code == 201, ret.text
    sale2 = await _sell(staff_a, register_id, variant, customer, qty=1)
    ex = await _call(
        staff_a,
        "POST",
        f"/api/v1/pos/sessions/{day_id}/exchanges",
        {
            "order_id": sale2["order_id"],
            "return_lines": [{"variant_id": str(variant.id), "quantity": 1}],
            "new_lines": [{"variant_id": str(variant.id), "quantity": 1}],
            "restock": True,
        },
    )
    assert ex.status_code == 201, ex.text

    receipts = (
        (await db.execute(select(PosReceipt).where(PosReceipt.session_id == day_id)))
        .scalars()
        .all()
    )
    by_kind = [(r.kind, r.sold_by_user_id) for r in receipts]
    assert by_kind, "no receipts recorded"
    assert all(who == tenant_ctx.user.id for _, who in by_kind), by_kind
    assert {"sale", "return"} <= {k for k, _ in by_kind}
