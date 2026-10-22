"""The sale itself, over real HTTP, against the discount ceiling and the manager PIN.

``test_pos_approval_over_http.py`` proves this contract for a cash-out. This is the call the till
makes when it sells with a discount: a plain cashier crosses the ceiling, is told a manager must
approve, a wrong PIN is refused, the right PIN lets the SAME sale through, and a discount within the
ceiling needs nobody. A refusal must book no order: production wraps every request in one
transaction and rolls it back on an error (``get_db``), so a savepoint stands in for that here.

The in-memory Redis fixture (``_redis``) is imported on purpose: without it ``set_pin`` talks to the
process-wide Redis client, which is bound to an earlier test's event loop ("Event loop is closed").
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core.errors import DomainError, build_error_body
from app.modules.identity.deps import get_tenant_ctx
from app.modules.pos.router import router as pos_router
from tests.test_pos_manager_pin import (  # noqa: F401  (_redis: the autouse in-memory Redis)
    _ctx,
    _redis,
    _setup,
)

pytestmark = pytest.mark.asyncio


def _app(ctx) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=build_error_body(exc))

    app.include_router(pos_router, prefix="/api/v1")

    async def _the_cashier():
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _the_cashier
    return app


async def test_a_sale_discount_over_the_ceiling_needs_a_manager_pin_over_http(db, tenant_ctx):
    """The cash-out contract, on the sale itself: this is the call the till makes."""
    from sqlalchemy import func, select

    from app.modules.orders.models import Order
    from tests.test_pos_discount_ceiling import _till

    manager, cashier, ctx = await _setup(db, tenant_ctx, pin="4821")
    shift, variant, customer = await _till(db, tenant_ctx, ceiling="10")
    url = f"/api/v1/pos/sessions/{shift.id}/sell"

    def body(discount, pay):
        return {
            "customer_id": str(customer.id),
            "items": [{"variant_id": str(variant.id), "quantity": 1}],
            "discount_total": discount,
            "tenders": [{"method": "cash", "amount": pay}],
        }

    async def orders():
        return (await db.execute(select(func.count()).select_from(Order))).scalar_one()

    async def post(**kw):
        # One transaction per request in production; a savepoint stands in for it here.
        sp = await db.begin_nested()
        res = await http.post(url, **kw)
        if res.status_code >= 400:
            await sp.rollback()
        else:
            await sp.commit()
        return res

    before = await orders()
    async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as http:
        # 1. 20% on a 10% till, a plain cashier: refused, and no order is left behind.
        refused = await post(json=body("20.00", "80.00"))
        assert refused.status_code in (400, 403), refused.text
        assert "ceiling" in refused.text or "approval" in refused.text, refused.text
        assert await orders() == before

        # 2. A wrong PIN is refused too, and still books nothing.
        wrong = await post(
            json=body("20.00", "80.00"),
            headers={"X-Manager-Id": str(manager.id), "X-Manager-Pin": "0000"},
        )
        assert wrong.status_code == 403
        assert await orders() == before

        # 3. The right PIN: the same sale goes through at the discounted total.
        ok = await post(
            json=body("20.00", "80.00"),
            headers={"X-Manager-Id": str(manager.id), "X-Manager-Pin": "4821"},
        )
        assert ok.status_code == 200, ok.text
        assert Decimal(ok.json()["grand_total"]) == Decimal("80.00")

        # 4. Within the ceiling needs nobody.
        within = await post(json=body("10.00", "90.00"))
        assert within.status_code == 200, within.text
        assert Decimal(within.json()["grand_total"]) == Decimal("90.00")
