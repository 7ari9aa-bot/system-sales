"""The profile's discount ceiling is enforced by the SERVICE, not by the screen.

`discount_ceiling_pct` was stored and editable and `ensure_discount_allowed` was tested alone,
but `sell` never called it: any discount went through. A hidden button is not a control; a till can
be driven by a script, by the AI agent, or by a stale client.

Rule: the discount actually priced onto the order (document discount PLUS every line discount) may
not exceed `ceiling_pct` of the subtotal, unless the caller holds `pos:override`. A ceiling of 0
means every discount needs the override. A till with no profile gets the safe default (ceiling 0).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.errors import ValidationError
from app.modules.pos.profiles import PosProfileService
from app.modules.pos.service import PosService
from tests.test_pos_returns import _customer, _register, _sellable_variant

pytestmark = pytest.mark.asyncio


async def _till(db, tenant_ctx, *, ceiling, with_profile=True):
    from tests.test_pos_returns import _warehouse

    register = await _register(db, tenant_ctx)
    profile_id = None
    if with_profile:
        wh = await _warehouse(db, tenant_ctx)
        profile = await PosProfileService.create(
            db,
            tenant_ctx.tenant_id,
            name="كاشير",
            code=f"P{uuid.uuid4().hex[:6]}",
            warehouse_id=wh.id,
            discount_ceiling_pct=ceiling,
            allowed_payment_methods=["cash"],
        )
        profile_id = profile.id
    shift = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, profile_id=profile_id
    )
    variant = await _sellable_variant(db, tenant_ctx, price="100.00", stock=50)
    customer = await _customer(db, tenant_ctx)
    return shift, variant, customer


async def _sell(db, tenant_ctx, shift, variant, customer, **kw):
    items = kw.pop("items", [{"variant_id": str(variant.id), "quantity": 1}])
    return await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        customer_id=customer.id,
        items=items,
        tenders=[{"method": "cash", "amount": kw.pop("pay", None)}],
        **kw,
    )


async def test_a_discount_within_the_ceiling_goes_through(db, tenant_ctx):
    shift, variant, customer = await _till(db, tenant_ctx, ceiling="10")
    sold = await _sell(
        db, tenant_ctx, shift, variant, customer, discount_total="10.00", pay="90.00"
    )
    assert Decimal(sold["grand_total"]) == Decimal("90.00")


async def test_a_discount_over_the_ceiling_is_refused(db, tenant_ctx):
    shift, variant, customer = await _till(db, tenant_ctx, ceiling="10")
    with pytest.raises(ValidationError, match="ceiling"):
        await _sell(db, tenant_ctx, shift, variant, customer, discount_total="10.01", pay="89.99")


async def test_the_override_lets_a_manager_go_over(db, tenant_ctx):
    shift, variant, customer = await _till(db, tenant_ctx, ceiling="10")
    sold = await _sell(
        db, tenant_ctx, shift, variant, customer,
        discount_total="40.00", pay="60.00", discount_override=True,
    )  # fmt: skip
    assert Decimal(sold["grand_total"]) == Decimal("60.00")


async def test_a_ceiling_of_zero_means_every_discount_needs_the_override(db, tenant_ctx):
    shift, variant, customer = await _till(db, tenant_ctx, ceiling="0")
    with pytest.raises(ValidationError, match="ceiling"):
        await _sell(db, tenant_ctx, shift, variant, customer, discount_total="0.01", pay="99.99")
    sold = await _sell(db, tenant_ctx, shift, variant, customer, pay="100.00")
    assert Decimal(sold["grand_total"]) == Decimal("100.00")


async def test_a_line_discount_counts_toward_the_ceiling(db, tenant_ctx):
    """The ceiling cannot be dodged by moving the discount from the document onto a line."""
    shift, variant, customer = await _till(db, tenant_ctx, ceiling="10")
    items = [{"variant_id": str(variant.id), "quantity": 1, "discount_pct": "50"}]
    with pytest.raises(ValidationError, match="ceiling"):
        await _sell(db, tenant_ctx, shift, variant, customer, items=items, pay="50.00")


async def test_line_and_document_discounts_are_added_together(db, tenant_ctx):
    shift, variant, customer = await _till(db, tenant_ctx, ceiling="10")
    # 6% on the line + 5.00 off the document = 11 of 100: over 10%, though each alone is under.
    items = [{"variant_id": str(variant.id), "quantity": 1, "discount_pct": "6"}]
    with pytest.raises(ValidationError, match="ceiling"):
        await _sell(
            db, tenant_ctx, shift, variant, customer,
            items=items, discount_total="5.00", pay="89.00",
        )  # fmt: skip


async def test_a_till_with_no_profile_does_not_get_a_free_pass(db, tenant_ctx):
    shift, variant, customer = await _till(db, tenant_ctx, ceiling="0", with_profile=False)
    with pytest.raises(ValidationError, match="ceiling"):
        await _sell(db, tenant_ctx, shift, variant, customer, discount_total="5.00", pay="95.00")


async def test_a_refused_discount_leaves_no_order_behind(db, tenant_ctx):
    import sqlalchemy as sa

    shift, variant, customer = await _till(db, tenant_ctx, ceiling="5")
    count = "SELECT count(*) FROM orders WHERE tenant_id = :t"
    before = (await db.execute(sa.text(count), {"t": tenant_ctx.tenant_id})).scalar_one()
    sp = await db.begin_nested()
    with pytest.raises(ValidationError):
        await _sell(db, tenant_ctx, shift, variant, customer, discount_total="50.00", pay="50.00")
    await sp.rollback()
    after = (await db.execute(sa.text(count), {"t": tenant_ctx.tenant_id})).scalar_one()
    assert after == before


# ------------------------------------------------ the route, with REAL role permissions -----


async def _ctx_for(db, tenant_ctx, role_code):
    """A TenantContext carrying the permissions the DB really grants that role."""
    import sqlalchemy as sa

    from app.modules.identity.deps import TenantContext

    codes = set(
        (
            await db.execute(
                sa.text(
                    "SELECT p.code FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
                    "JOIN permissions p ON p.id = rp.permission_id WHERE r.code = :c"
                ),
                {"c": role_code},
            )
        ).scalars()
    )
    return TenantContext(
        session=db,
        user=tenant_ctx.user,
        tenant_id=tenant_ctx.tenant_id,
        role_code=role_code,
        permission_codes=codes,
    )


def _body(variant, customer):
    from app.modules.pos.router import SellRequest

    return SellRequest(
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        customer_id=customer.id,
        discount_total="40.00",
        tenders=[{"method": "cash", "amount": "60.00"}],
    )


async def test_the_database_grants_the_override_to_owner_and_manager_but_not_staff(db, tenant_ctx):
    owner = await _ctx_for(db, tenant_ctx, "owner")
    manager = await _ctx_for(db, tenant_ctx, "manager")
    staff = await _ctx_for(db, tenant_ctx, "staff")
    assert "pos:override" in owner.permission_codes
    assert "pos:override" in manager.permission_codes
    assert "pos:override" not in staff.permission_codes
    assert "orders:write" in staff.permission_codes  # the cashier can still sell


async def test_a_cashier_on_the_route_cannot_sell_past_the_ceiling(db, tenant_ctx):
    from app.modules.pos.router import sell

    shift, variant, customer = await _till(db, tenant_ctx, ceiling="10")
    staff = await _ctx_for(db, tenant_ctx, "staff")
    with pytest.raises(ValidationError, match="ceiling"):
        await sell(shift.id, _body(variant, customer), staff)


async def test_a_manager_on_the_route_can(db, tenant_ctx):
    from app.modules.pos.router import sell

    shift, variant, customer = await _till(db, tenant_ctx, ceiling="10")
    manager = await _ctx_for(db, tenant_ctx, "manager")
    out = await sell(shift.id, _body(variant, customer), manager)
    assert Decimal(out["grand_total"]) == Decimal("60.00")


async def test_the_sell_request_has_no_way_to_ask_for_the_override(db, tenant_ctx):
    """The override comes from who you ARE, never from a field in the body."""
    from app.modules.pos.router import SellRequest

    assert "discount_override" not in SellRequest.model_fields
    assert "override" not in " ".join(SellRequest.model_fields)
