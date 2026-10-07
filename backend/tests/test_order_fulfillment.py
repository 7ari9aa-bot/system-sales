"""W4-T2: the fulfillment half of an order — shipments + the §139 saga state.

Two things were missing in the same place. `shipments` was migrated but had no
writer, so an order could read `shipped` with no carrier and no tracking number
anywhere; and `orders.process_state` had a validated machine with no caller, so
the column stayed at its `created` default for every order ever placed.

These tests assert the shipped behaviour: checkout, capture, cancel and
delivery each move the saga, the shipment record is created through the SAME
validated status path as the order (so the two facts cannot diverge), and an
explicit human command on the saga stays strict while the bookkeeping done as a
side effect of a business event stays lenient.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders.models import Order, OrderStatusHistory, Shipment
from app.modules.orders.service import _PROCESS_TRANSITIONS, OrderService

# ------------------------------------------------------------------ helpers ----


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    warehouse = Warehouse(
        tenant_id=tenant_id,
        name="Fulfil WH",
        code=f"WH-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    return warehouse


async def _order(db: AsyncSession, tenant_id: uuid.UUID, *, stock: int = 10, qty: int = 1) -> Order:
    """A placed order (stock reserved, `pending`), the saga's starting point."""
    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        "whatsapp",
        f"wa-{uuid.uuid4().hex[:10]}",
        name="Buyer",
    )
    product = await CatalogService.create_product(
        db, tenant_id, title="F", slug=f"f-{uuid.uuid4().hex[:10]}"
    )
    # §M4: checkout refuses a draft product, and `draft` is the column default —
    # this fixture's whole job is to hand back an order that got placed, so it
    # publishes the product first.
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(db, tenant_id, product.id, price="40.00")
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        (await _warehouse(db, tenant_id)).id,
        direction="in",
        quantity=stock,
        reason="purchase",
    )
    return await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": qty}]
    )


async def _to_processing(db: AsyncSession, tenant_id: uuid.UUID, order: Order) -> None:
    await OrderService.change_status(db, tenant_id, order.id, "confirmed")
    await OrderService.change_status(db, tenant_id, order.id, "processing")


# ------------------------------------------------- §139 saga: real callers ----


def test_the_saga_machine_allows_stock_reserved_before_payment():
    """Checkout reserves stock BEFORE any money exists (COD is the norm here).

    With only `created -> paid` in the map, the state describing the real
    order of events was unreachable, i.e. the machine could not describe an
    order at all.
    """
    assert "stock_reserved" in _PROCESS_TRANSITIONS["created"]
    assert "paid" in _PROCESS_TRANSITIONS["stock_reserved"]


async def test_checkout_leaves_the_saga_at_stock_reserved(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await db.flush()

    row = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert row.process_state == "stock_reserved"


async def test_capture_advances_the_saga_to_paid(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await OrderService.add_payment(db, tenant_id, order.id, method="cash", amount=Decimal("40.00"))
    await db.flush()

    row = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert row.process_state == "paid"


async def test_a_second_capture_does_not_fail_for_saga_bookkeeping(db: AsyncSession, tenant_ctx):
    """Split payments are normal; a saga already at `paid` must not 409 them.

    The advance is bookkeeping for an event that really happened, not a human
    command — the only honest response to "already there" is to leave it.
    """
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id, stock=10, qty=2)
    for _ in range(2):
        await OrderService.add_payment(
            db, tenant_id, order.id, method="cash", amount=Decimal("40.00")
        )
    await db.flush()

    row = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert row.process_state == "paid"


async def test_delivery_advances_the_saga_to_fulfilled(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    # The capture itself confirms the pending order, so the next step is the
    # one a merchant takes after that: processing.
    await OrderService.add_payment(db, tenant_id, order.id, method="cash", amount=Decimal("40.00"))
    await OrderService.change_status(db, tenant_id, order.id, "processing")
    await OrderService.change_status(db, tenant_id, order.id, "shipped")
    await OrderService.change_status(db, tenant_id, order.id, "delivered")
    await db.flush()

    row = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert row.process_state == "fulfilled"


async def test_cancel_sets_the_saga_cancelled(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await OrderService.cancel_order(db, tenant_id, order.id)
    await db.flush()

    row = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert row.process_state == "cancelled"


async def test_explicit_saga_command_stays_strict(db: AsyncSession, tenant_ctx):
    """A human driving the saga directly gets a refusal; the side effect does not.

    Checkout already put this order at `stock_reserved`, so the illegal move is
    the backwards one — a saga never re-opens.
    """
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)

    with pytest.raises(ConflictError):
        await OrderService.transition_process_state(db, tenant_id, order.id, "created")
    await db.flush()


# ------------------------------------------------------------- shipments ----


async def test_create_shipment_records_the_carrier_and_ships_the_order(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await _to_processing(db, tenant_id, order)

    shipment = await OrderService.create_shipment(
        db,
        tenant_id,
        order.id,
        carrier="Aramex",
        tracking_number="ARX-1",
        label_url="https://labels.test/arx-1.pdf",
    )
    await db.flush()

    assert shipment.status == "pending"
    assert (shipment.carrier, shipment.tracking_number) == ("Aramex", "ARX-1")
    assert shipment.shipped_at is not None
    assert shipment.delivered_at is None

    row = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert row.status == "shipped"
    # Going through the one status path means the audit trail exists too.
    history = (
        (
            await db.execute(
                select(OrderStatusHistory).where(
                    OrderStatusHistory.order_id == order.id,
                    OrderStatusHistory.to_status == "shipped",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(history) == 1


async def test_create_shipment_requires_a_processing_order(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)

    with pytest.raises(ConflictError):
        await OrderService.create_shipment(
            db, tenant_id, order.id, carrier="Aramex", tracking_number="ARX-2"
        )
    assert (
        await db.execute(select(Shipment).where(Shipment.order_id == order.id))
    ).scalars().all() == []
    await db.flush()


async def test_shipment_delivery_advances_the_order(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await _to_processing(db, tenant_id, order)
    shipment = await OrderService.create_shipment(
        db, tenant_id, order.id, carrier="Myler", tracking_number="MY-1"
    )

    for status in ("picked_up", "in_transit", "delivered"):
        shipment = await OrderService.set_shipment_status(db, tenant_id, shipment.id, status)
    await db.flush()

    assert shipment.delivered_at is not None
    row = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert row.status == "delivered"


async def test_shipment_status_machine_rejects_an_illegal_jump(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await _to_processing(db, tenant_id, order)
    shipment = await OrderService.create_shipment(
        db, tenant_id, order.id, carrier="Myler", tracking_number="MY-2"
    )

    from app.modules.orders.service import SHIPMENT_TRANSITIONS

    assert SHIPMENT_TRANSITIONS["pending"] == {"picked_up"}
    with pytest.raises(ConflictError):
        await OrderService.set_shipment_status(db, tenant_id, shipment.id, "delivered")
    # A status that is not in the vocabulary at all is a malformed request, not
    # a disagreement with the current state.
    with pytest.raises(ValidationError):
        await OrderService.set_shipment_status(db, tenant_id, shipment.id, "lost")
    await db.flush()


async def test_a_shipment_is_not_visible_to_another_tenant(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await _to_processing(db, tenant_id, order)
    shipment = await OrderService.create_shipment(
        db, tenant_id, order.id, carrier="Myler", tracking_number="MY-3"
    )

    with pytest.raises(NotFoundError):
        await OrderService.get_shipment(db, uuid.uuid4(), shipment.id)
    assert await OrderService.list_shipments(db, uuid.uuid4(), order.id) == []


async def test_list_shipments_returns_the_order_s_own_rows(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await _to_processing(db, tenant_id, order)
    assert await OrderService.list_shipments(db, tenant_id, order.id) == []

    first = await OrderService.create_shipment(
        db, tenant_id, order.id, carrier="Aramex", tracking_number="MY-4"
    )
    assert await OrderService.list_shipments(db, tenant_id, order.id) == [first]

    # The order has left `processing`, so it cannot be shipped a second time —
    # a second label would be a second claim that goods went out.
    with pytest.raises(ConflictError):
        await OrderService.create_shipment(
            db, tenant_id, order.id, carrier="Aramex", tracking_number="MY-5"
        )
    assert await OrderService.list_shipments(db, tenant_id, order.id) == [first]
    await db.flush()


# ------------------------------------------------------------ route surface ----


_MOUNTED = [
    ("/api/v1/orders/{order_id}/shipments", ["get", "post"]),
    ("/api/v1/shipments/{shipment_id}/status", ["post"]),
]


@pytest.mark.parametrize("path,methods", _MOUNTED)
def test_shipment_routes_are_mounted(path: str, methods: list[str]):
    """No service method is reachable unless a route exposes it."""
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    assert path in paths, f"{path} is not mounted"
    for method in methods:
        assert method in paths[path], f"{method.upper()} {path} is missing"


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/v1/orders/{order_id}/shipments", {"carrier": "Aramex"}),
        ("/api/v1/shipments/{shipment_id}/status", {"status": "picked_up"}),
    ],
)
async def test_shipment_writes_require_the_write_permission(
    db: AsyncSession, tenant_ctx, path: str, payload: dict
):
    """403 through the real stack — a write route without the gate moves stock
    for anyone who can reach the port."""
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app
    from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx

    ctx = TenantContext(
        session=db,
        user=AuthedUser(
            id=tenant_ctx.user.id,
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes=set(),  # no orders:write
    )

    async def _fake_ctx() -> TenantContext:
        return ctx

    app = create_app()
    app.dependency_overrides[get_tenant_ctx] = _fake_ctx
    transport = ASGITransport(app=app)
    order_id = uuid.uuid4()
    shipment_id = uuid.uuid4()
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            path.format(order_id=order_id, shipment_id=shipment_id), json=payload
        )
        assert response.status_code == 403, response.text
