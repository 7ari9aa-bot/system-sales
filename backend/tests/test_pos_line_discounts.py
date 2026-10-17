"""§189 — per-line cashier discounts (the ground-shop discount).

The cashier types a percentage on a SPECIFIC piece; the line charges its net
and the discount is stored on the order item. No approval gate. DB-free
guards run everywhere; DB-backed flows run on CI and are reported UNVERIFIED
when only local runs were possible (AGENT_BRIEF §3a).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

SELL_PATH = "/api/v1/pos/sessions/{session_id}/sell"


# --------------------------------------------------------- DB-free guards --


def test_sell_wire_accepts_per_line_discounts() -> None:
    from app.modules.pos.router import SellRequest

    body = SellRequest(
        items=[
            {"variant_id": str(uuid.uuid4()), "quantity": 2, "discount_pct": "10.00"},
            {"variant_id": str(uuid.uuid4()), "quantity": 1},
        ],
        method="cash",
    )
    assert body.items[0]["discount_pct"] == "10.00"
    assert "discount_pct" not in body.items[1]


def test_line_discount_pct_bounds() -> None:
    from app.modules.errors import ValidationError
    from app.modules.pos.service import PosService

    assert PosService._line_discount_pct({}) == Decimal("0.00")
    assert PosService._line_discount_pct({"discount_pct": "12.5"}) == Decimal("12.50")
    for bad in ("-1", "100.01", "abc"):
        with pytest.raises(ValidationError):
            PosService._line_discount_pct({"discount_pct": bad})


# ----------------------------------------------------------- DB-backed -----


async def _warehouse(db, tenant_ctx):
    from app.modules.inventory.service import InventoryService

    return await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)


async def _register(db, tenant_ctx):
    from app.modules.pos.service import PosService

    warehouse = await _warehouse(db, tenant_ctx)
    return await PosService.create_register(
        db,
        tenant_ctx.tenant_id,
        name="كاشير",
        code=f"REG-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
    )


async def _sellable_variant(db, tenant_ctx, price="25.00", stock=10):
    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.service import InventoryService

    warehouse = await _warehouse(db, tenant_ctx)
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="صنف", slug=f"d-{uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.update_product(
        db, tenant_ctx.tenant_id, product.id, status="active"
    )
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="وحدة", price=price
    )
    await InventoryService.move(
        db, tenant_ctx.tenant_id, variant.id, warehouse.id,
        direction="in", quantity=stock, reason="purchase",
    )
    return variant


async def _customer(db, tenant_ctx):
    from app.modules.customers.service import CustomerService

    return await CustomerService.create_from_import(
        db, tenant_ctx.tenant_id, name="زبون الخصم", source="pos"
    )


async def test_line_discount_charges_the_net_and_persists(db, tenant_ctx):
    from app.modules.orders.models import Order, OrderItem
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    result = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[
            {
                "variant_id": str(variant.id),
                "quantity": 2,
                "discount_pct": "20.00",
            }
        ],
    )
    # 2 × 25 = 50 gross; 20% off → 10 discounted; net 40 charged.
    assert Decimal(result["grand_total"]) == Decimal("40.00")

    item = (
        (
            await db.execute(
                select(OrderItem).where(OrderItem.order_id == result["order_id"])
            )
        )
        .scalars()
        .one()
    )
    assert Decimal(str(item.discount_pct)) == Decimal("20.00")
    assert Decimal(str(item.unit_price)) == Decimal("25.00")  # ladder price intact
    assert Decimal(str(item.total)) == Decimal("40.00")

    order = (
        (
            await db.execute(select(Order).where(Order.id == result["order_id"]))
        )
        .scalars()
        .one()
    )
    assert Decimal(str(order.subtotal)) == Decimal("50.00")
    assert Decimal(str(order.discount_total)) == Decimal("10.00")

    detail = await PosService.get_session(db, tenant_ctx.tenant_id, pos_session.id)
    assert detail["inflow"] == Decimal("40.00")


async def test_quote_composes_line_and_invoice_discounts(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)

    quoted = await PosService.quote(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        items=[{"variant_id": str(variant.id), "quantity": 2, "discount_pct": "10.00"}],
        discount_total="5.00",
    )
    # gross 50 − line 5 − invoice 5 = 40.
    assert Decimal(quoted["discount_total"]) == Decimal("10.00")
    assert Decimal(quoted["grand_total"]) == Decimal("40.00")


async def test_line_discount_refuses_out_of_bounds(db, tenant_ctx):
    from app.modules.errors import ValidationError
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    with pytest.raises(ValidationError):
        await PosService.sell(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            customer_id=customer.id,
            items=[
                {
                    "variant_id": str(variant.id),
                    "quantity": 1,
                    "discount_pct": "120.00",
                }
            ],
        )


async def test_exchange_of_a_discounted_line_credits_its_net(db, tenant_ctx):
    """A 20%-discounted 25.00 line credits 20.00, not 25.00 — the customer is
    made whole for what they ACTUALLY paid."""
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    sold_variant = await _sellable_variant(db, tenant_ctx)
    new_variant = await _sellable_variant(db, tenant_ctx, price="15.00")
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[
            {"variant_id": str(sold_variant.id), "quantity": 1, "discount_pct": "20.00"}
        ],
        method="cash",
    )

    result = await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        return_lines=[{"variant_id": str(sold_variant.id), "quantity": 1}],
        new_lines=[{"variant_id": str(new_variant.id), "quantity": 1}],
    )
    # The line's net: 25 − 20% = 20 credited; the 15 replacement is funded
    # from it; 5 returns to the customer.
    assert Decimal(result["return_total"]) == Decimal("20.00")
    assert Decimal(result["net"]) == Decimal("-5.00")


async def test_held_cart_carries_the_line_discount(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    held = await PosService.hold_cart(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        items=[
            {
                "variant_id": str(variant.id),
                "quantity": 1,
                "discount_pct": "10.00",
            }
        ],
    )
    assert held.items[0]["discount_pct"] == "10.00"
