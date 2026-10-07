"""OrderService tests — checkout reserves stock, outbox, lifecycle, payments."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import ProductPrice
from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.inventory.models import InventoryBalance, Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders.errors import InsufficientStockError
from app.modules.orders.models import OrderItem, OrderPayment, OrderStatusHistory
from app.modules.orders.service import OrderService
from app.modules.platform.models import OutboxEvent


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    warehouse = Warehouse(
        tenant_id=tenant_id,
        name="Order WH",
        code=f"WH-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    return warehouse


async def _customer_and_variant(db: AsyncSession, tenant_id: uuid.UUID, stock: int = 10):
    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        "whatsapp",
        f"wa-{uuid.uuid4().hex[:10]}",
        name="Test Buyer",
        phone=f"+2010{uuid.uuid4().hex[:8]}",
    )
    wh = await _warehouse(db, tenant_id)
    product = await CatalogService.create_product(
        db, tenant_id, title="Widget", slug=f"w-{uuid.uuid4().hex[:10]}"
    )
    # §M4: checkout sells an `active` product and nothing else, and `draft` is
    # create_product's default. These tests are about money and stock, so the
    # fixture publishes the goods; the draft/archived refusals are pinned in
    # test_checkout_rules.py.
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(
        db, tenant_id, product.id, sku=f"WGT-{uuid.uuid4().hex[:6].upper()}", price="25.50"
    )
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        wh.id,
        direction="in",
        quantity=stock,
        reason="purchase",
    )
    return customer, variant, wh


async def _order_events(db: AsyncSession, order_id: uuid.UUID) -> list[OutboxEvent]:
    return list(
        (await db.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == order_id)))
        .scalars()
        .all()
    )


async def _balance(
    db: AsyncSession, tenant_id: uuid.UUID, variant_id: uuid.UUID, warehouse_id: uuid.UUID
) -> InventoryBalance:
    return (
        await db.execute(
            select(InventoryBalance).where(
                InventoryBalance.tenant_id == tenant_id,
                InventoryBalance.variant_id == variant_id,
                InventoryBalance.warehouse_id == warehouse_id,
            )
        )
    ).scalar_one()


async def test_create_order_reserves_and_writes_outbox(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, wh = await _customer_and_variant(db, tenant_id, stock=10)

    order = await OrderService.create_order(
        db,
        tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 3}],
        channel="whatsapp",
        shipping_address={"city": "Cairo"},
    )
    await db.flush()

    assert order.number.startswith("ORD-")
    assert order.status == "pending"
    assert float(order.subtotal) == pytest.approx(76.5)
    assert float(order.grand_total) == pytest.approx(76.5)
    assert float(order.discount_total) == 0.0
    assert order.channel == "whatsapp"
    assert order.placed_at is not None

    # Stock reserved at the warehouse the order used.
    balance = await _balance(db, tenant_id, variant.id, wh.id)
    assert balance.on_hand == 10
    assert balance.reserved == 3

    # Line snapshot.
    items = (
        (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    )
    assert len(items) == 1
    item = items[0]
    assert item.variant_id == variant.id
    assert item.quantity == 3
    assert float(item.unit_price) == pytest.approx(25.5)
    assert float(item.total) == pytest.approx(76.5)
    assert item.sku == variant.sku
    assert item.title  # snapshot non-empty

    # Status history None -> pending.
    history = (
        (
            await db.execute(
                select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(history) == 1
    assert history[0].from_status is None
    assert history[0].to_status == "pending"

    # Outbox row written in the same transaction, queryable by aggregate_id.
    events = await _order_events(db, order.id)
    assert [e.payload["event_type"] for e in events] == ["order.created"]
    event = events[0]
    assert event.aggregate_type == "order"
    assert event.stream == "order.events"
    assert event.status == "pending"
    assert event.meta["tenant_id"] == str(tenant_id)
    assert event.payload["number"] == order.number


async def test_create_order_bootstraps_main_warehouse(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.create_product(
        db, tenant_id, title="Gadget", slug=f"g-{uuid.uuid4().hex[:10]}"
    )
    # Sellable (§M4): this test checks out, and only an active product sells.
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(db, tenant_id, product.id, price="5.00")

    # No warehouse exists yet — the service bootstraps "Main" (race-safe).
    main = await OrderService._default_warehouse(db, tenant_id)
    assert main.name == "Main"
    assert main.code == "MAIN"
    # Bootstrapping twice converges on the same row.
    again = await OrderService._default_warehouse(db, tenant_id)
    assert again.id == main.id

    await InventoryService.move(
        db, tenant_id, variant.id, main.id, direction="in", quantity=5, reason="purchase"
    )
    order = await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 2}]
    )
    await db.flush()

    warehouses = (
        (await db.execute(select(Warehouse).where(Warehouse.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    assert len(warehouses) == 1

    balance = await _balance(db, tenant_id, variant.id, main.id)
    assert balance.reserved == 2
    assert balance.on_hand == 5
    assert order.extra["warehouse_id"] == str(main.id)


async def test_cancel_order_releases_stock_and_emits_event(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, wh = await _customer_and_variant(db, tenant_id, stock=10)

    order = await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 4}]
    )
    cancelled = await OrderService.cancel_order(
        db, tenant_id, order.id, by_user_id=tenant_ctx.user.id
    )
    await db.flush()

    assert cancelled.status == "cancelled"
    balance = await _balance(db, tenant_id, variant.id, wh.id)
    assert balance.reserved == 0  # released
    assert balance.on_hand == 10

    history = (
        (
            await db.execute(
                select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id)
            )
        )
        .scalars()
        .all()
    )
    assert {h.to_status for h in history} == {"pending", "cancelled"}
    assert any(h.from_status == "pending" for h in history)

    events = await _order_events(db, order.id)
    assert {e.payload["event_type"] for e in events} == {
        "order.created",
        "order.cancelled",
    }


async def test_cancel_confirmed_order_releases(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, wh = await _customer_and_variant(db, tenant_id, stock=6)
    order = await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 2}]
    )
    await OrderService.change_status(db, tenant_id, order.id, "confirmed")
    cancelled = await OrderService.cancel_order(db, tenant_id, order.id)
    assert cancelled.status == "cancelled"
    assert (await _balance(db, tenant_id, variant.id, wh.id)).reserved == 0
    await db.flush()


async def test_cancel_after_processing_conflicts(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, _wh = await _customer_and_variant(db, tenant_id, stock=6)
    order = await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 1}]
    )
    for status in ("confirmed", "processing"):
        await OrderService.change_status(db, tenant_id, order.id, status)

    with pytest.raises(ConflictError):
        await OrderService.cancel_order(db, tenant_id, order.id)
    await db.flush()


async def test_illegal_transition_raises_conflict(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, _wh = await _customer_and_variant(db, tenant_id, stock=6)
    order = await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 1}]
    )

    with pytest.raises(ConflictError):
        await OrderService.change_status(db, tenant_id, order.id, "shipped")
    with pytest.raises(ConflictError):
        await OrderService.change_status(db, tenant_id, order.id, "delivered")
    await db.flush()


async def test_full_lifecycle_writes_history_and_events(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, _wh = await _customer_and_variant(db, tenant_id, stock=6)
    order = await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 1}]
    )

    path = ["confirmed", "processing", "shipped", "delivered", "completed", "refunded"]
    for to_status in path:
        await OrderService.change_status(
            db, tenant_id, order.id, to_status, by_user_id=tenant_ctx.user.id
        )
        assert order.status == to_status
    await db.flush()

    history = (
        (
            await db.execute(
                select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id)
            )
        )
        .scalars()
        .all()
    )
    assert {h.to_status for h in history} == {"pending", *path}

    events = await _order_events(db, order.id)
    status_events = [e for e in events if e.payload["event_type"] == "order.status_changed"]
    assert len(status_events) == len(path)


async def test_wrong_tenant_order_is_not_found(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, _wh = await _customer_and_variant(db, tenant_id, stock=6)
    order = await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 1}]
    )

    other_tenant = uuid.uuid4()
    with pytest.raises(NotFoundError):
        await OrderService.get(db, other_tenant, order.id)
    with pytest.raises(NotFoundError):
        await OrderService.cancel_order(db, other_tenant, order.id)
    with pytest.raises(NotFoundError):
        await OrderService.change_status(db, other_tenant, order.id, "confirmed")
    assert await OrderService.list_orders(db, other_tenant) == []
    await db.flush()


async def test_add_payment_confirms_pending_order(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, _wh = await _customer_and_variant(db, tenant_id, stock=6)
    order = await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 1}]
    )

    payment = await OrderService.add_payment(db, tenant_id, order.id, method="cash", amount="25.50")
    await db.flush()

    assert payment.status == "captured"
    assert float(payment.amount) == pytest.approx(25.5)
    assert payment.paid_at is not None
    assert order.status == "confirmed"

    with pytest.raises(ValueError):
        await OrderService.add_payment(db, tenant_id, order.id, method="cash", amount=0)


async def test_reconcile_unknown_payment_captures_once(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, _wh = await _customer_and_variant(db, tenant_id, stock=6)
    order = await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 1}]
    )
    payment = OrderPayment(
        tenant_id=tenant_id,
        order_id=order.id,
        method="card",
        status="unknown",
        amount=25.5,
        currency="EGP",
        provider="test-gateway",
    )
    db.add(payment)
    await db.flush()

    resolved = await OrderService.reconcile_payment(
        db,
        tenant_id,
        order.id,
        payment.id,
        provider_status="succeeded",
        provider_ref="pay_123",
    )

    assert resolved.status == "captured"
    assert resolved.provider_ref == "pay_123"
    assert order.status == "confirmed"

    again = await OrderService.reconcile_payment(
        db, tenant_id, order.id, payment.id, provider_status="captured"
    )
    assert again.status == "captured"


async def test_register_refund_tracks_payment_state(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, _wh = await _customer_and_variant(db, tenant_id, stock=6)
    order = await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 1}]
    )
    # Pay the order's exact balance: the over-payment guard rejects anything
    # above it (the old test paid 100 on a 25.50 order, which is no longer
    # allowed by design).
    payment = await OrderService.add_payment(db, tenant_id, order.id, method="card", amount="25.50")

    # Refund scenario aligned to the real 25.50 balance (the old 30/71/70
    # amounts were built on the over-payment the guard now forbids).
    partial = await OrderService.register_refund(
        db, tenant_id, order.id, payment.id, amount=10, reason="damaged item"
    )
    assert Decimal(str(partial.amount)) == Decimal("10")
    assert partial.status == "processed"
    assert payment.status == "partially_refunded"

    # Over-refunding (10 already refunded + 20 > 25.50 captured) is a domain
    # ConflictError (error contract v2), not a bare ValueError.
    with pytest.raises(ConflictError):
        await OrderService.register_refund(db, tenant_id, order.id, payment.id, amount=20)

    final = await OrderService.register_refund(
        db, tenant_id, order.id, payment.id, amount=Decimal("15.50")
    )
    assert payment.status == "refunded"
    assert Decimal(str(final.amount)) == Decimal("15.50")

    with pytest.raises(NotFoundError):
        await OrderService.register_refund(db, tenant_id, order.id, uuid.uuid4(), amount=10)
    await db.flush()


async def test_create_order_input_validation(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, _variant, _wh = await _customer_and_variant(db, tenant_id, stock=6)

    with pytest.raises(NotFoundError):
        await OrderService.create_order(
            db, tenant_id, customer.id, [{"variant_id": uuid.uuid4(), "quantity": 1}]
        )
    with pytest.raises(NotFoundError):
        await OrderService.create_order(
            db, tenant_id, uuid.uuid4(), [{"variant_id": uuid.uuid4(), "quantity": 1}]
        )
    # Empty items → domain ValidationError (error contract v2), not a bare
    # ValueError. This was the contract change the old test predated.
    with pytest.raises(ValidationError):
        await OrderService.create_order(db, tenant_id, customer.id, [])
    await db.flush()


async def test_insufficient_stock_aborts_order_atomically(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, wh = await _customer_and_variant(db, tenant_id, stock=1)

    with pytest.raises(InsufficientStockError):
        await OrderService.create_order(
            db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 5}]
        )
    # Nothing leaked: no order, no reservation.
    assert await OrderService.list_orders(db, tenant_id) == []
    balance = await _balance(db, tenant_id, variant.id, wh.id)
    assert balance.reserved == 0
    await db.flush()


async def test_checkout_variant_and_price_reads_do_not_grow_with_cart_size(
    db: AsyncSession, tenant_ctx, _engine, monkeypatch
):
    """The prepared phase reads the cart in TWO queries, not two per line.

    A 30-line cart used to issue a variant read and a price read per line
    (60+ queries) before reserving anything. The batched path fetches every
    variant and every price ladder once; only reserve's own per-line reads
    (the FOR UPDATE path, deliberately per-item) still grow with the cart.
    """
    tenant_id = tenant_ctx.tenant_id
    customer, variant, wh = await _customer_and_variant(db, tenant_id, stock=10)
    variants = [variant]
    for _ in range(5):
        extra = await CatalogService.add_variant(
            db,
            tenant_id,
            variant.product_id,
            sku=f"WGT-{uuid.uuid4().hex[:6].upper()}",
            price="10.00",
        )
        await InventoryService.move(
            db,
            tenant_id,
            extra.id,
            wh.id,
            direction="in",
            quantity=10,
            reason="purchase",
        )
        variants.append(extra)
    await db.flush()

    counted: list[str] = []

    def _count(_conn, _cursor, statement, _parameters, _context, _executemany):
        lowered = statement.lower()
        if "product_variants" in lowered or "product_prices" in lowered:
            counted.append(lowered)

    event.listen(_engine.sync_engine, "before_cursor_execute", _count)
    calls = {"price_for": 0}
    real_price_for = CatalogService.price_for

    async def price_for_spy(*args, **kwargs):
        calls["price_for"] += 1
        return await real_price_for(*args, **kwargs)

    monkeypatch.setattr(CatalogService, "price_for", staticmethod(price_for_spy))
    try:
        order = await OrderService.create_order(
            db,
            tenant_id,
            customer.id,
            [{"variant_id": v.id, "quantity": 1} for v in variants],
        )
    finally:
        event.remove(_engine.sync_engine, "before_cursor_execute", _count)

    # The cart itself must have succeeded — the counts below mean nothing
    # if the batched path could not check this cart out at all.
    assert order.status == "pending"

    variant_reads = [s for s in counted if "product_variants" in s]
    price_reads = [s for s in counted if "product_prices" in s]
    # Price ladders: ONE read for the whole cart — the old path spent one
    # per line.
    assert len(price_reads) == 1
    # Variants: one batched read for the cart plus one per line inside
    # reserve's FOR UPDATE path (per-item on purpose, lock-order rule).
    assert len(variant_reads) == len(variants) + 1
    # The batch is the only variant read that fans out over ids.
    assert sum(1 for s in variant_reads if " in (" in s) == 1
    # The per-line price read is gone entirely.
    assert calls["price_for"] == 0


async def test_checkout_duplicate_lines_price_tiers_like_per_item_path(
    db: AsyncSession, tenant_ctx
):
    """Duplicate cart lines and quantity tiers survive the batched read path.

    Each duplicate line must be priced for its OWN quantity from the shared
    ladder, and the batched result must equal the per-item path (``price_for``
    called line by line) for a tiered case — including the §47 rule that a
    foreign-currency tier sitting on this shop prices nothing.
    """
    tenant_id = tenant_ctx.tenant_id
    customer, variant, wh = await _customer_and_variant(db, tenant_id, stock=100)
    # Ladder in the tenant's currency (EGP): 5+ units at 20.00, 10+ at 15.00.
    await CatalogService.set_variant_price(db, tenant_id, variant.id, "20.00", min_quantity=5)
    await CatalogService.set_variant_price(db, tenant_id, variant.id, "15.00", min_quantity=10)
    # A USD tier left on this EGP shop must never price a line (§47) — the
    # write path refuses it, so the read-side filter gets a raw row to ignore.
    db.add(
        ProductPrice(
            tenant_id=tenant_id,
            variant_id=variant.id,
            currency="USD",
            unit_price=Decimal("1.00"),
            min_quantity=1,
        )
    )
    await db.flush()

    quantities = [2, 5, 12]  # below the ladder, on the first tier, on the deepest
    order = await OrderService.create_order(
        db,
        tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": q} for q in quantities],
    )
    await db.flush()

    items = (
        (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    )
    assert len(items) == len(quantities)
    priced = {item.quantity: item.unit_price for item in items}

    expected: dict[int, Decimal] = {}
    for quantity in quantities:
        # The OLD per-item path, called for the same quantities.
        expected[quantity] = await CatalogService.price_for(
            db, tenant_id, variant, currency=order.currency, quantity=quantity
        )
    assert priced == expected
    # Tier edges: the base price below the ladder, each tier at its own
    # threshold — and never the USD tier.
    assert float(priced[2]) == pytest.approx(25.5)
    assert float(priced[5]) == pytest.approx(20.0)
    assert float(priced[12]) == pytest.approx(15.0)

    # Duplicate lines reserve as separate holds, exactly as before.
    balance = await _balance(db, tenant_id, variant.id, wh.id)
    assert balance.reserved == sum(quantities)


async def test_checkout_reserves_in_variant_id_order(db: AsyncSession, tenant_ctx, monkeypatch):
    """The reserve loop walks variants in VARIANT-ID order, never the cart's.

    Two concurrent checkouts holding the same variants in opposite line orders
    deadlock on the FOR UPDATE row locks when reservation follows the
    customer's line order (reproduced 25/25 pre-fix). The line order is data;
    the lock order is a global rule — asserted here by recording the calls.
    """
    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.service import InventoryService

    tenant_id = tenant_ctx.tenant_id
    customer, variant_a, wh = await _customer_and_variant(db, tenant_id, stock=10)
    variant_b = await CatalogService.add_variant(
        db,
        tenant_id,
        variant_a.product_id,
        sku=f"WGT-{uuid.uuid4().hex[:6].upper()}",
        price="30.00",
    )
    await InventoryService.move(
        db, tenant_id, variant_b.id, wh.id, direction="in", quantity=10, reason="purchase"
    )
    await db.flush()

    calls: list[uuid.UUID] = []
    real_reserve = InventoryService.reserve

    async def spy(session, tid, variant_id, warehouse_id, quantity):
        calls.append(variant_id)
        return await real_reserve(session, tid, variant_id, warehouse_id, quantity)

    monkeypatch.setattr(InventoryService, "reserve", staticmethod(spy))

    # The cart lists the HIGHER id first — the customer's order must not
    # decide the lock order.
    first, second = sorted([variant_a, variant_b], key=lambda v: v.id)
    await OrderService.create_order(
        db,
        tenant_id,
        customer.id,
        [
            {"variant_id": str(second.id), "quantity": 1},
            {"variant_id": str(first.id), "quantity": 1},
        ],
        channel="whatsapp",
    )

    assert calls == [first.id, second.id]
