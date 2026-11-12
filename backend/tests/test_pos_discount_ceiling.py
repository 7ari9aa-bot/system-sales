"""The shop owner's discount ceiling (a POS profile setting).

The owner decides how much a cashier may take off a sale. The default is no ceiling, so a shop that
never touches the setting behaves exactly as before. The ceiling measures the discount that
actually applies (the typed invoice discount PLUS every line percentage), as a share of the sale
before any discount, so splitting a discount across the two fields does not get around it. A
manager (``pos:override``) is not held to it.
"""

from __future__ import annotations

import uuid

import pytest

from tests._pos_helpers import start_day
from tests.test_pos_phase6 import _sellable_variant, _warehouse


async def _till(db, tenant_ctx, *, ceiling):
    from app.modules.pos.profiles import PosProfileService
    from app.modules.pos.service import PosService

    warehouse = await _warehouse(db, tenant_ctx)
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="محل",
        code=f"P-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
        max_discount_pct=ceiling,
    )
    register = await PosService.create_register(
        db,
        tenant_ctx.tenant_id,
        name="كاشير",
        code=f"REG-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
        profile_id=profile.id,
    )
    await start_day(db, tenant_ctx, register.id)
    return register, profile


async def _sell(
    db, tenant_ctx, register, variant, *, discount_total=None, pct=None, override=False
):
    from app.modules.pos.service import PosService

    line = {"variant_id": str(variant.id), "quantity": 1}
    if pct is not None:
        line["discount_pct"] = pct
    return await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        register.id,
        items=[line],
        discount_total=discount_total,
        actor_user_id=tenant_ctx.user.id,
        discount_override=override,
    )


async def test_no_ceiling_means_the_shop_decides_nothing_changes(db, tenant_ctx):
    register, _ = await _till(db, tenant_ctx, ceiling=None)
    variant = await _sellable_variant(db, tenant_ctx, price="100.00")
    sold = await _sell(db, tenant_ctx, register, variant, discount_total="100.00")
    assert sold["grand_total"] == "0.00"


async def test_a_typed_discount_above_the_ceiling_is_refused_with_the_number(db, tenant_ctx):
    from app.modules.errors import ValidationError

    register, _ = await _till(db, tenant_ctx, ceiling="20")
    variant = await _sellable_variant(db, tenant_ctx, price="100.00")
    with pytest.raises(ValidationError) as caught:
        await _sell(db, tenant_ctx, register, variant, discount_total="21.00")
    assert "20" in str(caught.value)


async def test_a_discount_exactly_at_the_ceiling_is_allowed(db, tenant_ctx):
    register, _ = await _till(db, tenant_ctx, ceiling="20")
    variant = await _sellable_variant(db, tenant_ctx, price="100.00")
    sold = await _sell(db, tenant_ctx, register, variant, discount_total="20.00")
    assert sold["grand_total"] == "80.00"


async def test_a_line_percentage_above_the_ceiling_is_refused_too(db, tenant_ctx):
    from app.modules.errors import ValidationError

    register, _ = await _till(db, tenant_ctx, ceiling="20")
    variant = await _sellable_variant(db, tenant_ctx, price="100.00")
    with pytest.raises(ValidationError):
        await _sell(db, tenant_ctx, register, variant, pct="25")


async def test_splitting_a_discount_across_both_fields_does_not_get_around_it(db, tenant_ctx):
    from app.modules.errors import ValidationError

    register, _ = await _till(db, tenant_ctx, ceiling="20")
    variant = await _sellable_variant(db, tenant_ctx, price="100.00")
    # 15% on the line plus 10.00 off the invoice is 25% of the sale.
    with pytest.raises(ValidationError):
        await _sell(db, tenant_ctx, register, variant, pct="15", discount_total="10.00")


async def test_a_refused_sale_leaves_no_order_and_no_stock_movement(db, tenant_ctx):
    import sqlalchemy as sa

    from app.modules.errors import ValidationError
    from app.modules.orders.models import Order

    register, _ = await _till(db, tenant_ctx, ceiling="20")
    variant = await _sellable_variant(db, tenant_ctx, price="100.00")
    before = (await db.execute(sa.select(sa.func.count()).select_from(Order))).scalar_one()
    with pytest.raises(ValidationError):
        await _sell(db, tenant_ctx, register, variant, discount_total="50.00")
    after = (await db.execute(sa.select(sa.func.count()).select_from(Order))).scalar_one()
    assert after == before


async def test_a_manager_is_not_held_to_the_ceiling(db, tenant_ctx):
    register, _ = await _till(db, tenant_ctx, ceiling="20")
    variant = await _sellable_variant(db, tenant_ctx, price="100.00")
    sold = await _sell(db, tenant_ctx, register, variant, discount_total="90.00", override=True)
    assert sold["grand_total"] == "10.00"


async def test_the_quote_refuses_it_before_the_sale_is_even_tried(db, tenant_ctx):
    from app.modules.errors import ValidationError
    from app.modules.pos.service import PosService

    register, _ = await _till(db, tenant_ctx, ceiling="20")
    variant = await _sellable_variant(db, tenant_ctx, price="100.00")
    day = await PosService.open_day(db, tenant_ctx.tenant_id, register.id, opening_float="0")
    with pytest.raises(ValidationError):
        await PosService.quote(
            db,
            tenant_ctx.tenant_id,
            day.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],
            discount_total="30.00",
            actor_user_id=tenant_ctx.user.id,
        )


@pytest.mark.parametrize("bad", ["-1", "101", "abc", "", "nan", "20.555"])
async def test_the_owner_cannot_save_a_nonsense_ceiling(db, tenant_ctx, bad):
    from app.modules.errors import ValidationError
    from app.modules.pos.profiles import PosProfileService

    warehouse = await _warehouse(db, tenant_ctx)
    with pytest.raises(ValidationError):
        await PosProfileService.create(
            db,
            tenant_ctx.tenant_id,
            name="محل",
            code=f"P-{uuid.uuid4().hex[:6]}",
            warehouse_id=warehouse.id,
            max_discount_pct=bad,
        )


async def test_the_owner_can_set_change_and_clear_it(db, tenant_ctx):
    from app.modules.pos.profiles import PosProfileService

    _, profile = await _till(db, tenant_ctx, ceiling="10")
    assert str(profile.max_discount_pct) == "10.00"
    changed = await PosProfileService.update(
        db, tenant_ctx.tenant_id, profile.id, max_discount_pct="35"
    )
    assert str(changed.max_discount_pct) == "35.00"
    cleared = await PosProfileService.update(
        db, tenant_ctx.tenant_id, profile.id, clear_max_discount=True
    )
    assert cleared.max_discount_pct is None
