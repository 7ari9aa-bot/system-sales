"""§189/§188 POS flow — DB-backed (P6/P7).

The full adapter story in one transaction per test: open a drawer, sell from
stock, watch the §140 machinery settle it, close the drawer with a counted
figure, and see the variance stored as a record. Runs wherever a database URL
is configured; conftest skips otherwise.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.errors import ConflictError, ValidationError
from app.modules.inventory.models import InventoryReservation
from app.modules.inventory.service import InventoryService
from app.modules.orders.models import Order, OrderPayment
from app.modules.platform.models import OutboxEvent
from app.modules.pos.service import PosService


async def _register(db, tenant_ctx):
    warehouse = await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)
    return await PosService.create_register(
        db,
        tenant_ctx.tenant_id,
        name="كاشير الفرع",
        code=f"REG-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
    )


async def _sellable_variant(db, tenant_ctx):
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="كوباية", slug=f"c-{uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.update_product(
        db, tenant_ctx.tenant_id, product.id, status="active"
    )
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="سعة كبيرة", price="25.00"
    )
    warehouse = await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)
    await InventoryService.move(
        db,
        tenant_ctx.tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=5,
        reason="purchase",
    )
    return variant


async def _customer(db, tenant_ctx):
    return await CustomerService.create_from_import(
        db, tenant_ctx.tenant_id, name="زبون نقدي", source="pos"
    )


async def test_one_open_session_per_register(db, tenant_ctx):
    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, opening_float="50.00"
    )
    assert pos_session.status == "OPEN"
    assert Decimal(pos_session.opening_float) == 50
    with pytest.raises(ConflictError):
        await PosService.open_session(db, tenant_ctx.tenant_id, register.id)


async def test_sell_runs_the_whole_commerce_chain(db, tenant_ctx):
    from decimal import Decimal

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)

    result = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": variant.id, "quantity": 1}],
    )
    assert result["receipt_number"].startswith("POS-")

    order = (await db.execute(select(Order).where(Order.id == result["order_id"]))).scalar_one()
    assert order.channel == "pos"
    assert order.grand_total == Decimal("25.00")
    payment = (
        await db.execute(select(OrderPayment).where(OrderPayment.order_id == order.id))
    ).scalar_one()
    assert payment.status == "captured"
    # §140: the captured payment settled the reservation — the POS never
    # touched the balance itself.
    (reservation,) = (
        (
            await db.execute(
                select(InventoryReservation).where(InventoryReservation.order_id == order.id)
            )
        )
        .scalars()
        .all()
    )
    assert reservation.status == "CONVERTED"
    balance = await InventoryService.list_balances(db, tenant_ctx.tenant_id)
    mine = [b for b in balance if b.variant_id == variant.id]
    assert mine and mine[0].on_hand == 4
    # The drawer booked the cash, in the same transaction.
    detail = await PosService.get_session(db, tenant_ctx.tenant_id, pos_session.id)
    assert detail["inflow"] == Decimal("25.00")


async def test_close_stores_the_closing_balance_and_publishes_once(db, tenant_ctx):
    from decimal import Decimal

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": variant.id, "quantity": 1}],
    )

    closed = await PosService.close_session(db, tenant_ctx.tenant_id, pos_session.id)
    assert closed.status == "CLOSED"
    # closing balance = opening + invoices - returns; nothing is counted, so no variance exists
    assert closed.expected_cash == Decimal("25.00")
    assert closed.counted_cash is None
    assert closed.variance is None
    with pytest.raises(ConflictError):
        await PosService.close_session(db, tenant_ctx.tenant_id, pos_session.id)
    events = (
        (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_type == "pos_session",
                )
            )
        )
        .scalars()
        .all()
    )
    # The outbox is cross-tenant: the tenant rides in the §19 meta envelope
    # and the event type is the payload's first key.
    assert any(
        "pos.session.closed" in e.payload
        and str(e.meta.get("tenant_id")) == str(tenant_ctx.tenant_id)
        for e in events
    )


async def test_sell_on_a_closed_session_is_refused(db, tenant_ctx):
    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, pos_session.id)
    with pytest.raises(ConflictError):
        await PosService.sell(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            customer_id=customer.id,
            items=[{"variant_id": variant.id, "quantity": 1}],
        )


@pytest.mark.parametrize("quantity", [0, -1, "0", "-3", "abc"])
async def test_sell_with_a_non_positive_quantity_is_a_validation_error_not_a_500(
    db, tenant_ctx, quantity
):
    """/quote already refused these; /sell let them reach OrderService, whose bare ValueError became
    an HTTP 500 marked retryable. It must be the same 400-class ValidationError, and nothing is
    reserved or sold."""
    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    with pytest.raises(ValidationError):
        await PosService.sell(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            items=[{"variant_id": variant.id, "quantity": quantity}],
        )
    reserved = (await db.execute(select(InventoryReservation))).scalars().all()
    assert [r for r in reserved if r.variant_id == variant.id] == []


async def test_sell_validates_every_line_before_touching_anything(db, tenant_ctx):
    """A good line followed by a bad one must not leave the good line reserved."""
    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    with pytest.raises(ValidationError):
        await PosService.sell(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            items=[
                {"variant_id": variant.id, "quantity": 1},
                {"variant_id": variant.id, "quantity": -2},
            ],
        )
    reserved = (await db.execute(select(InventoryReservation))).scalars().all()
    assert [r for r in reserved if r.variant_id == variant.id] == []


async def test_close_records_the_day_never_a_count_or_a_shortage(db, tenant_ctx):
    """The close is not a drawer count: no counted figure, no variance, no reconciliation rows.
    The report carries opening balance, invoices, returns and the derived closing balance."""
    from decimal import Decimal

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": variant.id, "quantity": 1}],
    )  # 25.00

    closed = await PosService.close_session(db, tenant_ctx.tenant_id, pos_session.id)
    assert closed.counted_cash is None
    assert closed.variance is None

    report = await PosService.session_report(db, tenant_ctx.tenant_id, pos_session.id)
    assert "variance_total" not in report
    assert "by_method" not in report
    assert Decimal(report["sales"]["total"]) == Decimal("25.00")
    assert Decimal(report["closing_balance"]) == Decimal(report["opening_balance"]) + Decimal(
        "25.00"
    )
