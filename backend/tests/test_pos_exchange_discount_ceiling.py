"""An exchange is held to the shop owner's discount ceiling like a sale.

The replacement half of an exchange takes per-line discounts. Before this, only ``quote`` and
``record_sale`` checked the ceiling, so a cashier could return an item and take the replacement at
100% off. A manager (``pos:override``) is not held to it, and a plain exchange is unaffected.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.errors import ValidationError
from tests._pos_sell import sell
from tests.test_pos_discount_ceiling import _till
from tests.test_pos_phase6 import _sellable_variant


async def _swap(db, tenant_ctx, *, ceiling, pct=None, override=False):
    from app.modules.pos.service import PosService

    register, _ = await _till(db, tenant_ctx, ceiling=ceiling)
    old = await _sellable_variant(db, tenant_ctx, price="100.00")
    new = await _sellable_variant(db, tenant_ctx, price="100.00")
    sess = await PosService._today_session(db, tenant_ctx.tenant_id, register)
    sold = await sell(
        db,
        tenant_ctx.tenant_id,
        sess.id,
        items=[{"variant_id": str(old.id), "quantity": 1}],
        actor_user_id=tenant_ctx.user.id,
    )
    line = {"variant_id": str(new.id), "quantity": 1}
    if pct is not None:
        line["discount_pct"] = pct
    return await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        sess.id,
        order_id=sold["order_id"],
        return_lines=[{"variant_id": str(old.id), "quantity": 1}],
        new_lines=[line],
        actor_user_id=tenant_ctx.user.id,
        shift_override=override,
    )


async def test_a_replacement_discount_above_the_ceiling_is_refused(db, tenant_ctx):
    with pytest.raises(ValidationError) as caught:
        await _swap(db, tenant_ctx, ceiling="10", pct="100")
    assert "10" in str(caught.value)


async def test_a_replacement_discount_within_the_ceiling_goes_through(db, tenant_ctx):
    result = await _swap(db, tenant_ctx, ceiling="10", pct="10")
    assert Decimal(result["new_total"]) == Decimal("90.00")


async def test_a_manager_may_exceed_it_on_an_exchange(db, tenant_ctx):
    result = await _swap(db, tenant_ctx, ceiling="10", pct="100", override=True)
    assert Decimal(result["new_total"]) == Decimal("0.00")


async def test_no_ceiling_means_an_exchange_is_unchanged(db, tenant_ctx):
    result = await _swap(db, tenant_ctx, ceiling=None, pct="100")
    assert Decimal(result["new_total"]) == Decimal("0.00")


async def test_a_plain_exchange_with_a_ceiling_set_still_works(db, tenant_ctx):
    result = await _swap(db, tenant_ctx, ceiling="10")
    assert Decimal(result["net"]) == Decimal("0.00")
