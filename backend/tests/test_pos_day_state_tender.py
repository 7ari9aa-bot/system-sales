"""The till learns HOW it may take money from the day-state call it already makes.

A shop that turns ``pos.take_payments`` on refuses every sale that carries no payment line, so a
screen that does not know the setting cannot sell at all. ``working-session`` and ``open-day`` now
say, for the till the day runs on: whether payments are recorded, whether a sale may go on the
customer's account, which methods the till accepts and which of them need a reference. The cashier
role must be able to read it (it is not behind ``settings:read``).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.modules.identity.deps import get_db, get_tenant_ctx
from app.modules.settings.service import SettingsService
from tests._pos_helpers import ctx_for
from tests.test_pos_take_payments import _shop

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


async def _day(ctx, register_id):
    async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as c:
        return await c.post(f"/api/v1/pos/registers/{register_id}/working-session", json={})


async def test_a_till_that_records_payments_says_so_with_its_methods(db, tenant_ctx) -> None:
    register, _variant, _customer = await _shop(db, tenant_ctx, methods=("cash", "card"))
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.reference_required_methods", ["card"])
    ctx = await ctx_for(db, tenant_ctx, "owner")

    r = await _day(ctx, register.id)

    assert r.status_code == 200, r.text
    tender = r.json()["tender"]
    assert tender["take_payments"] is True
    assert tender["allow_on_account"] is False
    assert sorted(tender["methods"]) == ["card", "cash"]
    assert tender["reference_required"] == ["card"]


async def test_a_till_that_does_not_record_payments_says_so(db, tenant_ctx) -> None:
    register, _variant, _customer = await _shop(db, tenant_ctx, take_payments=False)
    ctx = await ctx_for(db, tenant_ctx, "owner")

    tender = (await _day(ctx, register.id)).json()["tender"]

    assert tender["take_payments"] is False
    assert tender["allow_on_account"] is False
    assert tender["methods"] == [], "a till that records no payment offers no method"
    assert tender["reference_required"] == []


async def test_selling_on_account_is_offered_only_with_payments_on_too(db, tenant_ctx) -> None:
    """The server refuses an account sale unless BOTH settings are on; the screen must not offer it
    on one alone."""
    register, _variant, _customer = await _shop(db, tenant_ctx, take_payments=False)
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.allow_sale_on_account", True)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    assert (await _day(ctx, register.id)).json()["tender"]["allow_on_account"] is False

    register2, _v, _c = await _shop(db, tenant_ctx)
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.allow_sale_on_account", True)
    ctx2 = await ctx_for(db, tenant_ctx, "owner")
    assert (await _day(ctx2, register2.id)).json()["tender"]["allow_on_account"] is True


async def test_a_staff_member_who_sells_can_read_it(db, tenant_ctx) -> None:
    register, _variant, _customer = await _shop(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "staff")

    r = await _day(ctx, register.id)

    assert r.status_code == 200, r.text
    assert r.json()["tender"]["take_payments"] is True


async def test_starting_the_day_returns_the_same_rules(db, tenant_ctx) -> None:
    """The screen reads the rules from whichever call opened the day, not only from a later read."""
    from app.modules.pos.service import PosService
    from tests._pos_helpers import till

    shift, _variant, _customer = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as c:
        r = await c.post(
            f"/api/v1/pos/registers/{shift.register_id}/open-day", json={"opening_float": "10"}
        )
    assert r.status_code == 201, r.text
    assert r.json()["tender"] is not None
    assert r.json()["tender"]["take_payments"] is False


async def _sell_http(ctx, register_id, variant, body_extra, customer_id=None):
    body = {"items": [{"variant_id": str(variant.id), "quantity": 1}], **body_extra}
    if customer_id:
        body["customer_id"] = str(customer_id)
    async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as c:
        return await c.post(f"/api/v1/pos/registers/{register_id}/sales", json=body)


async def test_the_payloads_the_cashier_screen_builds_are_what_the_server_accepts(
    db, tenant_ctx
) -> None:
    """Same shapes ``buildTender`` (frontend/src/cashier/api/tenderPlan.js) produces: a split card +
    cash sale with a reference and change, a part-paid sale on account, and a refusal the screen
    would have caught first."""
    from decimal import Decimal

    from app.modules.customer_accounts.service import CustomerAccountService as Accounts

    register, variant, customer = await _shop(db, tenant_ctx, methods=("cash", "card"))
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set("pos.reference_required_methods", ["card"])
    await svc.set("pos.allow_sale_on_account", True)
    await Accounts.open_account(db, tenant_ctx.tenant_id, customer.id, credit_limit="100000")
    ctx = await ctx_for(db, tenant_ctx, "owner")

    price = Decimal(str(variant.price))

    # the screen would not send a card line without its reference: the server refuses it too
    no_ref = await _sell_http(
        ctx, register.id, variant, {"payments": [{"method": "card", "amount": str(price)}]}
    )
    assert no_ref.status_code in (400, 422), no_ref.text

    # cash handed over above the amount (tendered) + the rest on a card with its reference
    cash_part = (price / 2).quantize(Decimal("0.01"))
    card_part = price - cash_part
    ok = await _sell_http(
        ctx,
        register.id,
        variant,
        {
            "payments": [
                {"method": "cash", "amount": str(cash_part), "tendered": str(cash_part + 50)},
                {"method": "card", "amount": str(card_part), "reference": "4455"},
            ]
        },
    )
    assert ok.status_code == 201, ok.text

    # part now, the rest on the named customer's account, with the flag the screen sets
    part = await _sell_http(
        ctx,
        register.id,
        variant,
        {"payments": [{"method": "cash", "amount": "1.00"}], "on_account": True},
        customer_id=customer.id,
    )
    assert part.status_code == 201, part.text

    # more than the total is refused, and so is an account sale with nobody named
    over = await _sell_http(
        ctx, register.id, variant, {"payments": [{"method": "cash", "amount": str(price + 1)}]}
    )
    assert over.status_code in (400, 422), over.text
    nobody = await _sell_http(ctx, register.id, variant, {"payments": [], "on_account": True})
    assert nobody.status_code in (400, 422), nobody.text

    # paying LESS than the total, without putting the rest on the account, is refused: only an
    # account sale may be part-paid, or the shop loses the difference with no debt to chase
    short = await _sell_http(
        ctx, register.id, variant, {"payments": [{"method": "cash", "amount": "1.00"}]}
    )
    assert short.status_code in (400, 422), short.text
