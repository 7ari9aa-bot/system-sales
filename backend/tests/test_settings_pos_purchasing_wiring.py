"""The settings that gate till and goods-receipt behaviour change that behaviour, and only then.

Each case flips ONE setting and checks both directions: the default keeps today's behaviour, the
override changes it. A switch that moves nothing is what the ``enforced`` flag exists to prevent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

import app.modules.customers.models  # noqa: F401  (pos_held_carts has an FK to customers)
from app.modules.errors import ConflictError, ValidationError
from app.modules.settings.service import SettingsService
from tests._pos_sell import sell as pos_sell
from tests.test_pos_line_discounts import _customer, _register, _sellable_variant


async def _open_day(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    return await PosService.open_session(db, tenant_ctx.tenant_id, register.id)


# --------------------------------------------------------------- pos.allow_hold_cart --


async def test_a_cart_can_be_held_by_default(db, tenant_ctx):
    from app.modules.pos.service import PosService

    pos_session = await _open_day(db, tenant_ctx)
    variant = await _sellable_variant(db, tenant_ctx)
    held = await PosService.hold_cart(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    assert held.id is not None


async def test_turning_hold_off_refuses_the_hold(db, tenant_ctx):
    from app.modules.pos.service import PosService

    pos_session = await _open_day(db, tenant_ctx)
    variant = await _sellable_variant(db, tenant_ctx)
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.allow_hold_cart", False)
    with pytest.raises(ConflictError, match="pos.allow_hold_cart"):
        await PosService.hold_cart(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],
        )


# -------------------------------------------------------------- pos.return_max_days --


async def _sold_order(db, tenant_ctx, pos_session):
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    result = await pos_sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    return variant, result["order_id"]


async def _age_receipt(db, order_id, days):
    from app.modules.pos.models import PosReceipt

    await db.execute(
        update(PosReceipt)
        .where(PosReceipt.order_id == order_id, PosReceipt.kind == "sale")
        .values(issued_at=datetime.now(UTC) - timedelta(days=days))
    )
    await db.flush()


async def test_a_return_inside_the_window_is_accepted(db, tenant_ctx):
    from app.modules.pos.service import PosService

    pos_session = await _open_day(db, tenant_ctx)
    variant, order_id = await _sold_order(db, tenant_ctx, pos_session)
    await _age_receipt(db, order_id, 10)
    out = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=uuid.UUID(str(order_id)),
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    assert out


async def test_a_return_past_the_default_window_is_refused(db, tenant_ctx):
    from app.modules.pos.service import PosService

    pos_session = await _open_day(db, tenant_ctx)
    variant, order_id = await _sold_order(db, tenant_ctx, pos_session)
    await _age_receipt(db, order_id, 31)  # the default window is 30 days
    with pytest.raises(ConflictError, match="pos.return_max_days"):
        await PosService.return_sale(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            order_id=uuid.UUID(str(order_id)),
            lines=[{"variant_id": str(variant.id), "quantity": 1}],
        )


async def test_widening_the_window_accepts_the_same_old_sale(db, tenant_ctx):
    from app.modules.pos.service import PosService

    pos_session = await _open_day(db, tenant_ctx)
    variant, order_id = await _sold_order(db, tenant_ctx, pos_session)
    await _age_receipt(db, order_id, 31)
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.return_max_days", 60)
    out = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=uuid.UUID(str(order_id)),
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    assert out


# -------------------------------------------------- purchasing.allow_over_receipt --


async def _po_and_line(db, tenant_ctx, quantity="10"):
    from decimal import Decimal

    from app.modules.catalog.models import Product, ProductVariant
    from app.modules.inventory.models import Warehouse
    from app.modules.purchasing.service import PurchaseService, SupplierService

    tid = tenant_ctx.tenant_id
    wh = Warehouse(tenant_id=tid, name="WH-OR", code=f"OR{uuid.uuid4().hex[:5]}", is_active=True)
    sup = await SupplierService.create(db, tid, name="Over Receipt Co")
    prod = Product(tenant_id=tid, title="Tee", slug=f"tee-{uuid.uuid4().hex[:8]}", status="active")
    db.add_all([wh, prod])
    await db.flush()
    var = ProductVariant(
        tenant_id=tid,
        product_id=prod.id,
        sku=f"TEE-{uuid.uuid4().hex[:6]}",
        title="M",
        price=Decimal("90"),
    )
    db.add(var)
    await db.flush()
    po = await PurchaseService.create(
        db,
        tid,
        supplier_id=sup.id,
        warehouse_id=wh.id,
        lines=[{"variant_id": var.id, "quantity": int(quantity), "unit_cost": "50.00"}],
    )
    line = (await PurchaseService._lines_in(db, tid, po.id))[0]
    return po, line, var


def _receipt_line(line, var, qty):
    return {
        "purchase_order_line_id": str(line.id),
        "variant_id": str(var.id),
        "quantity": qty,
        "unit_cost": "50.00",
        "condition": "good",
    }


async def test_over_receipt_is_refused_by_default(db, tenant_ctx):
    from app.modules.purchasing.service import GoodsReceiptService

    po, line, var = await _po_and_line(db, tenant_ctx, "10")
    with pytest.raises(ValidationError, match="remain on the PO line"):
        await GoodsReceiptService.create(
            db, tenant_ctx.tenant_id, purchase_order_id=po.id, lines=[_receipt_line(line, var, 12)]
        )


async def test_allowing_over_receipt_accepts_the_extra_units(db, tenant_ctx):
    from app.modules.purchasing.service import GoodsReceiptService

    po, line, var = await _po_and_line(db, tenant_ctx, "10")
    await SettingsService(db, tenant_ctx.tenant_id).set("purchasing.allow_over_receipt", True)
    receipt = await GoodsReceiptService.create(
        db, tenant_ctx.tenant_id, purchase_order_id=po.id, lines=[_receipt_line(line, var, 12)]
    )
    assert receipt.status == "draft"


# ------------------------------------------------ purchasing.allow_partial_receipt --


async def test_a_partial_receipt_is_accepted_by_default(db, tenant_ctx):
    from app.modules.purchasing.service import GoodsReceiptService

    po, line, var = await _po_and_line(db, tenant_ctx, "10")
    receipt = await GoodsReceiptService.create(
        db, tenant_ctx.tenant_id, purchase_order_id=po.id, lines=[_receipt_line(line, var, 4)]
    )
    assert receipt.status == "draft"


async def test_turning_partial_receipt_off_demands_the_full_remainder(db, tenant_ctx):
    from app.modules.purchasing.service import GoodsReceiptService

    po, line, var = await _po_and_line(db, tenant_ctx, "10")
    await SettingsService(db, tenant_ctx.tenant_id).set("purchasing.allow_partial_receipt", False)
    with pytest.raises(ValidationError, match="allow_partial_receipt"):
        await GoodsReceiptService.create(
            db, tenant_ctx.tenant_id, purchase_order_id=po.id, lines=[_receipt_line(line, var, 4)]
        )
    full = await GoodsReceiptService.create(
        db, tenant_ctx.tenant_id, purchase_order_id=po.id, lines=[_receipt_line(line, var, 10)]
    )
    assert full.status == "draft"


# ------------------------------------------------------------ pos.require_customer --


async def _sell_without_customer(db, tenant_ctx):
    pos_session = await _open_day(db, tenant_ctx)
    variant = await _sellable_variant(db, tenant_ctx)
    return await pos_sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
    )


async def test_a_walk_in_sale_goes_through_by_default(db, tenant_ctx):
    assert (await _sell_without_customer(db, tenant_ctx))["order_id"]


async def test_the_shop_wide_setting_makes_a_named_customer_mandatory(db, tenant_ctx):
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.require_customer", True)
    with pytest.raises(ValidationError, match="requires a customer"):
        await _sell_without_customer(db, tenant_ctx)


# ------------------------------------------------- inventory.safety_stock_default --


async def _policy(db, tenant_ctx, **kw):
    from app.modules.inventory.services.replenishment import ReplenishmentService

    variant = await _sellable_variant(db, tenant_ctx)
    from app.modules.inventory.models import Warehouse

    wh = Warehouse(
        tenant_id=tenant_ctx.tenant_id,
        name="WH-SS",
        code=f"SS{uuid.uuid4().hex[:5]}",
        is_active=True,
    )
    db.add(wh)
    await db.flush()
    return await ReplenishmentService.set_policy(
        db, tenant_ctx.tenant_id, variant_id=variant.id, warehouse_id=wh.id, min_stock=5, **kw
    )


async def test_a_policy_with_no_safety_stock_gets_zero_by_default(db, tenant_ctx):
    assert (await _policy(db, tenant_ctx)).safety_stock == 0


async def test_a_policy_with_no_safety_stock_takes_the_shop_default(db, tenant_ctx):
    await SettingsService(db, tenant_ctx.tenant_id).set("inventory.safety_stock_default", 7)
    assert (await _policy(db, tenant_ctx)).safety_stock == 7


async def test_an_explicit_safety_stock_beats_the_shop_default(db, tenant_ctx):
    await SettingsService(db, tenant_ctx.tenant_id).set("inventory.safety_stock_default", 7)
    assert (await _policy(db, tenant_ctx, safety_stock=2)).safety_stock == 2
    assert (await _policy(db, tenant_ctx, safety_stock=0)).safety_stock == 0
