"""``require_customer`` was stored and shown in settings but never enforced: a till that demanded a
customer still sold to nobody. These tests sell through the real service the way a client would."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.modules.errors import ValidationError
from app.modules.pos.profiles import PosProfileService
from app.modules.pos.service import PosService
from tests.test_pos_phase6 import _customer, _register, _sellable_variant, _warehouse

pytestmark = pytest.mark.asyncio


async def _till(db, tenant_ctx, *, require_customer, with_default=False):
    wh = await _warehouse(db, tenant_ctx)
    default = await _customer(db, tenant_ctx) if with_default else None
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="till",
        code=f"P{uuid.uuid4().hex[:6]}",
        warehouse_id=wh.id,
        require_customer=require_customer,
        default_customer_id=default.id if default else None,
        allowed_payment_methods=["cash"],
    )
    register = await _register(db, tenant_ctx)
    shift = await PosService.open_session(
        db,
        tenant_ctx.tenant_id,
        register.id,
        profile_id=profile.id,
        opened_by=tenant_ctx.user.id,
        cashier_user_id=tenant_ctx.user.id,
    )
    return shift, await _sellable_variant(db, tenant_ctx, price="40.00")


async def _order_count(db, tenant_ctx):
    return (
        await db.execute(
            sa.text("SELECT count(*) FROM orders WHERE tenant_id = :t"), {"t": tenant_ctx.tenant_id}
        )
    ).scalar_one()


async def _sell(db, tenant_ctx, shift, variant, **kw):
    return await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        tenders=[{"method": "cash", "amount": "40.00"}],
        actor_user_id=tenant_ctx.user.id,
        **kw,
    )


async def test_a_till_that_requires_a_customer_refuses_a_sale_with_none(db, tenant_ctx):
    shift, variant = await _till(db, tenant_ctx, require_customer=True)
    before = await _order_count(db, tenant_ctx)
    with pytest.raises(ValidationError, match="requires a customer"):
        await _sell(db, tenant_ctx, shift, variant)
    assert await _order_count(db, tenant_ctx) == before  # nothing was created


async def test_a_default_walk_in_does_not_satisfy_require_customer(db, tenant_ctx):
    """The walk-in fallback is exactly what 'requires a customer' rules out."""
    shift, variant = await _till(db, tenant_ctx, require_customer=True, with_default=True)
    with pytest.raises(ValidationError, match="requires a customer"):
        await _sell(db, tenant_ctx, shift, variant)


async def test_a_named_customer_is_accepted(db, tenant_ctx):
    shift, variant = await _till(db, tenant_ctx, require_customer=True)
    customer = await _customer(db, tenant_ctx)
    sold = await _sell(db, tenant_ctx, shift, variant, customer_id=customer.id)
    assert sold["order_id"]


async def test_without_the_flag_a_walk_in_sale_still_works(db, tenant_ctx):
    shift, variant = await _till(db, tenant_ctx, require_customer=False)
    sold = await _sell(db, tenant_ctx, shift, variant)
    assert sold["order_id"]
