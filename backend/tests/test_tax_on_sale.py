"""Tax on a real sale: the customer's total never moves, the tax inside it is extracted."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.modules.catalog.models import Product
from app.modules.orders.models import Order, OrderItem
from app.modules.taxation.service import TaxationService
from tests._pos_helpers import start_day, till
from tests._pos_sell import sell

D = Decimal


async def _ready(db, tenant_ctx):
    shift, variant, customer = await till(db, tenant_ctx)
    await start_day(db, tenant_ctx, shift.register_id)
    return shift, variant, customer


async def _sell(db, tenant_ctx, shift, variant, customer, qty=1, discount=None):
    await sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        items=[{"variant_id": str(variant.id), "quantity": qty}],
        customer_id=customer.id,
        discount_total=discount,
    )
    order = (await db.execute(select(Order).order_by(Order.created_at.desc()))).scalars().first()
    items = (
        (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    )
    return order, items


async def _register_vat(db, tenant_ctx) -> None:
    await TaxationService.upsert_profile(
        db,
        tenant_ctx.tenant_id,
        legal_name="متجر الاختبار",
        vat_status="registered",
        tax_registration_number="123456789",
    )


async def test_a_shop_that_is_not_vat_registered_sells_exactly_as_before(db, tenant_ctx) -> None:
    shift, variant, customer = await _ready(db, tenant_ctx)
    order, items = await _sell(db, tenant_ctx, shift, variant, customer)
    assert D(str(order.grand_total)) == D("100.00")
    assert D(str(order.tax_included)) == D("0.00")
    assert D(str(order.tax_total)) == D("0.00")
    assert [D(str(i.tax_included)) for i in items] == [D("0.00")]


async def test_a_registered_shop_charges_the_same_and_extracts_the_tax(db, tenant_ctx) -> None:
    await _register_vat(db, tenant_ctx)
    shift, variant, customer = await _ready(db, tenant_ctx)
    order, items = await _sell(db, tenant_ctx, shift, variant, customer)
    # 100.00 on the shelf is 100.00 at the till: VAT does not make the customer pay more.
    assert D(str(order.grand_total)) == D("100.00")
    assert D(str(order.tax_total)) == D("0.00")  # nothing ADDED on top
    assert D(str(order.tax_included)) == D("12.28")  # 100 - 100/1.14, inside the price
    assert D(str(items[0].tax_rate)) == D("0.1400")
    assert D(str(items[0].tax_included)) == D("12.28")


async def test_the_tax_follows_the_quantity(db, tenant_ctx) -> None:
    await _register_vat(db, tenant_ctx)
    shift, variant, customer = await _ready(db, tenant_ctx)
    order, items = await _sell(db, tenant_ctx, shift, variant, customer, qty=3)
    assert D(str(order.grand_total)) == D("300.00")
    assert D(str(order.tax_included)) == D("36.84")  # 300 - 300/1.14


async def test_a_discount_lowers_the_tax_with_the_price(db, tenant_ctx) -> None:
    await _register_vat(db, tenant_ctx)
    shift, variant, customer = await _ready(db, tenant_ctx)
    order, _ = await _sell(db, tenant_ctx, shift, variant, customer, qty=2, discount="50.00")
    assert D(str(order.grand_total)) == D("150.00")
    # tax is on what was actually paid (150), not on the undiscounted 200
    assert D(str(order.tax_included)) == D("18.42")  # 150 - 150/1.14


async def test_a_zero_rated_product_carries_no_tax(db, tenant_ctx) -> None:
    await _register_vat(db, tenant_ctx)
    classes = {
        c.code: c for c in await TaxationService.ensure_default_classes(db, tenant_ctx.tenant_id)
    }
    shift, variant, customer = await _ready(db, tenant_ctx)
    product = await db.get(Product, variant.product_id)
    product.tax_class_id = classes["ZERO"].id
    await db.flush()
    order, items = await _sell(db, tenant_ctx, shift, variant, customer)
    assert D(str(order.grand_total)) == D("100.00")
    assert D(str(order.tax_included)) == D("0.00")
    assert D(str(items[0].tax_rate)) == D("0")


async def test_editing_a_class_later_does_not_rewrite_an_issued_receipt(db, tenant_ctx) -> None:
    await _register_vat(db, tenant_ctx)
    shift, variant, customer = await _ready(db, tenant_ctx)
    order, items = await _sell(db, tenant_ctx, shift, variant, customer)
    before = D(str(items[0].tax_included))
    cls = await TaxationService.default_class(db, tenant_ctx.tenant_id)
    cls.rate = D("0.0500")
    await db.flush()
    await db.refresh(items[0])
    assert D(str(items[0].tax_included)) == before == D("12.28")
    assert D(str(items[0].tax_rate)) == D("0.1400")


async def test_the_line_taxes_always_add_up_to_the_order_tax(db, tenant_ctx) -> None:
    await _register_vat(db, tenant_ctx)
    shift, variant, customer = await _ready(db, tenant_ctx)
    for qty in (1, 2, 3, 7):
        order, items = await _sell(
            db, tenant_ctx, shift, variant, customer, qty=qty, discount="3.33"
        )
        assert sum(D(str(i.tax_included)) for i in items) == D(str(order.tax_included)), qty
