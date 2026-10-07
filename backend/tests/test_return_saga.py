"""W4-T2b (§139): the goods-return process runs on the saga engine.

ADR-051 left `returned`/`failed` deliberately inert: a parcel that came back
restocked nothing and closed nothing, so the order stayed at `shipped` with
`process_state=fulfilled` forever — while `app/core/saga.py` and the migrated
`sagas` table sat with zero callers. §139 names exactly this half of the
process ("Fulfillment failed → compensation policy"), so the engine gets its
first real driver here instead of being retired.

The process, and what each step owes the one before it:

    step 0  restock   paid line: the units go back on the shelf (`in`/return)
                      unpaid line: the hold that never settled is released
                      undo: the same units taken off it again
    step 1  close     order -> `returned`, history row, outbox event
                      undo: the previous status restored

The refund is deliberately NOT a step: §115 lists "Refund approval" among the
critical flows, so giving money back stays an approved human action
(`POST /orders/{id}/payments/{pid}/refunds`) — never a side effect of a box
arriving at a warehouse.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.saga import Saga, SagaManager, SagaStatus, SagaStepHandler
from app.main import create_app
from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.errors import ConflictError, NotFoundError
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.inventory.models import InventoryMovement, InventoryReservation, Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders.models import Order, OrderStatusHistory
from app.modules.orders.service import TRANSITIONS, OrderService

# ------------------------------------------------------------------ helpers ----

RETURN_SAGA_TYPE = "order_return"
_RANK = {"pending": 0, "confirmed": 1, "processing": 2, "shipped": 3, "delivered": 4}
_PATH = ["confirmed", "processing", "shipped", "delivered"]


async def _stocked_variant(
    db: AsyncSession, tenant_id: uuid.UUID, *, stock: int = 10
) -> tuple[object, Warehouse]:
    product = await CatalogService.create_product(
        db, tenant_id, title="Returnable", slug=f"r-{uuid.uuid4().hex[:10]}"
    )
    # §M4: only an `active` product sells and `draft` is the default status, so
    # the fixture publishes it — this file is about the return saga, not about
    # what checkout refuses (that is test_checkout_rules.py).
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(db, tenant_id, product.id, price="40.00")
    warehouse = Warehouse(
        tenant_id=tenant_id,
        name="Returns WH",
        code=f"RW-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=stock,
        reason="purchase",
    )
    return variant, warehouse


async def _order_at(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    status: str,
    *,
    paid: bool = False,
    qty: int = 3,
) -> tuple[Order, object, Warehouse]:
    """An order walked to `status` through the real service calls.

    `paid` captures the payment, which is what converts the reservation into a
    sale — i.e. the difference between stock that physically left and stock that
    is merely held.
    """
    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        "whatsapp",
        f"wa-{uuid.uuid4().hex[:10]}",
        name="Buyer",
    )
    variant, warehouse = await _stocked_variant(db, tenant_id)
    order = await OrderService.create_order(
        db,
        tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": qty}],
        warehouse_id=warehouse.id,
    )
    if paid:
        await OrderService.add_payment(
            db, tenant_id, order.id, method="cash", amount=Decimal("120.00")
        )
    # Read the live status from the DB rather than trusting the object: a
    # captured payment moves a `pending` order to `confirmed` by itself, and
    # `_transition` writes through a compare-and-swap UPDATE.
    at = _RANK[(await db.execute(select(Order.status).where(Order.id == order.id))).scalar_one()]
    for step in _PATH:
        if not at < _RANK[step] <= _RANK[status]:
            continue
        await OrderService.change_status(db, tenant_id, order.id, step)
    # Stop the helper lying to the tests below it: a walk that ends somewhere
    # else than asked makes every later assertion fail for a reason that has
    # nothing to do with the return process.
    await db.refresh(order)
    assert order.status == status, f"the walk ended at {order.status}"
    return order, variant, warehouse


async def _balance(db: AsyncSession, tenant_id, variant, warehouse):
    balance = await InventoryService.get_balance(db, tenant_id, variant.id, warehouse.id)
    await db.refresh(balance)
    return balance


async def _movements(db: AsyncSession, order_id) -> list[InventoryMovement]:
    return list(
        (
            await db.execute(
                select(InventoryMovement).where(
                    InventoryMovement.reference_type == "order",
                    InventoryMovement.reference_id == order_id,
                )
            )
        )
        .scalars()
        .all()
    )


async def _reload(db: AsyncSession, saga_id) -> Saga:
    """Re-read the saga row from the DB, past the identity map."""
    db.expire_all()
    return (await db.execute(select(Saga).where(Saga.id == saga_id))).scalar_one()


# ------------------------------------------------- the engine, driven for real ----


class _CountingStep(SagaStepHandler):
    """Appends to a shared log, so a test can see the order the engine acted in."""

    def __init__(self, label: str, log: list[str], *, fail: bool = False) -> None:
        self.label = label
        self.log = log
        self.fail = fail

    async def execute(self, session, tenant_id, saga, context) -> dict:
        if self.fail:
            self.log.append(f"run:{self.label}")
            raise RuntimeError(f"{self.label} refused")
        self.log.append(f"run:{self.label}")
        return {self.label: "done"}

    async def compensate(self, session, tenant_id, saga, context) -> dict:
        self.log.append(f"undo:{self.label}")
        return {self.label: "undone"}


@pytest.fixture
def saga_registry():
    """Register handlers on a throw-away saga type, and unregister afterwards.

    `SagaManager._handlers` is process-global: entries left behind would leak
    their steps into every later run of the engine.
    """
    registered: list[tuple[str, int]] = []

    def _register(saga_type: str, steps: list[SagaStepHandler]) -> str:
        for index, step in enumerate(steps):
            SagaManager._handlers[(saga_type, index)] = step
            registered.append((saga_type, index))
        return saga_type

    yield _register
    for key in registered:
        SagaManager._handlers.pop(key, None)


async def test_a_failing_step_compensates_the_completed_ones(
    db: AsyncSession, tenant_ctx, saga_registry
) -> None:
    tenant_id = tenant_ctx.tenant_id
    log: list[str] = []
    saga_registry(
        "test_compensation",
        [_CountingStep("restock", log), _CountingStep("close", log, fail=True)],
    )
    saga = await SagaManager.create_saga(
        db,
        tenant_id,
        saga_type="test_compensation",
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
    )
    await SagaManager.execute_next(db, tenant_id, saga.id)
    with pytest.raises(RuntimeError, match="close refused"):
        await SagaManager.execute_next(db, tenant_id, saga.id)

    assert log == ["run:restock", "run:close", "undo:restock"]
    assert (await _reload(db, saga.id)).status == SagaStatus.FAILED.value


async def test_the_compensation_result_is_stored_not_just_applied(
    db: AsyncSession, tenant_ctx, saga_registry
) -> None:
    """`step_results` is JSONB, so editing a nested dict in place is invisible to
    the unit of work. Unless the engine writes the list back, the row claims the
    first step is still completed after it was undone.
    """
    tenant_id = tenant_ctx.tenant_id
    log: list[str] = []
    saga_registry(
        "test_stored",
        [_CountingStep("restock", log), _CountingStep("close", log, fail=True)],
    )
    saga = await SagaManager.create_saga(
        db,
        tenant_id,
        saga_type="test_stored",
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
    )
    await SagaManager.execute_next(db, tenant_id, saga.id)
    with pytest.raises(RuntimeError):
        await SagaManager.execute_next(db, tenant_id, saga.id)

    fresh = await _reload(db, saga.id)
    assert [r["status"] for r in fresh.step_results] == ["compensated", "failed"]


async def test_the_engine_publishes_its_own_lifecycle(
    db: AsyncSession, tenant_ctx, saga_registry
) -> None:
    from app.modules.platform.models import OutboxEvent

    tenant_id = tenant_ctx.tenant_id
    log: list[str] = []
    saga_registry("test_lifecycle", [_CountingStep("only", log)])
    saga = await SagaManager.create_saga(
        db,
        tenant_id,
        saga_type="test_lifecycle",
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
    )
    await SagaManager.execute_next(db, tenant_id, saga.id)
    finished = await SagaManager.execute_next(db, tenant_id, saga.id)
    assert finished.status == SagaStatus.COMPLETED.value

    types = {
        e.payload["event_type"]
        for e in (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_type == "saga",
                    OutboxEvent.aggregate_id == saga.id,
                )
            )
        )
        .scalars()
        .all()
    }
    assert types == {"saga.started", "saga.completed"}


async def test_a_saga_of_another_tenant_is_not_found(
    db: AsyncSession, tenant_ctx, saga_registry
) -> None:
    tenant_id = tenant_ctx.tenant_id
    log: list[str] = []
    saga_registry("test_isolation", [_CountingStep("only", log)])
    saga = await SagaManager.create_saga(
        db,
        tenant_id,
        saga_type="test_isolation",
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
    )
    with pytest.raises(NotFoundError):
        await SagaManager.execute_next(db, uuid.uuid4(), saga.id)


# ------------------------------------------- the return process: a paid order ----


async def test_returning_a_paid_order_puts_the_stock_back(db, tenant_ctx) -> None:
    from app.modules.orders.returns import ReturnsService

    tenant_id = tenant_ctx.tenant_id
    order, variant, warehouse = await _order_at(db, tenant_id, "shipped", paid=True)
    sold = await _balance(db, tenant_id, variant, warehouse)
    assert sold.on_hand == 7  # 10 in, 3 converted to a sale

    await ReturnsService.process_return(db, tenant_id, order.id, by_user_id=tenant_ctx.user.id)

    back = await _balance(db, tenant_id, variant, warehouse)
    assert back.on_hand == 10
    assert back.reserved == 0


async def test_a_paid_return_writes_one_ledger_row_per_line(db, tenant_ctx) -> None:
    from app.modules.orders.returns import ReturnsService

    tenant_id = tenant_ctx.tenant_id
    order, variant, warehouse = await _order_at(db, tenant_id, "delivered", paid=True)

    await ReturnsService.process_return(db, tenant_id, order.id)

    restocked = [m for m in await _movements(db, order.id) if m.reason == "return"]
    assert [(m.direction, m.quantity, m.variant_id) for m in restocked] == [("in", 3, variant.id)]
    assert restocked[0].warehouse_id == warehouse.id
    assert restocked[0].balance_after == 10


async def test_returning_closes_the_order_and_its_saga_state(db, tenant_ctx) -> None:
    from app.modules.orders.returns import ReturnsService

    tenant_id = tenant_ctx.tenant_id
    order, _variant, _warehouse = await _order_at(db, tenant_id, "shipped", paid=True)

    await ReturnsService.process_return(db, tenant_id, order.id)

    fresh = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert fresh.status == "returned"
    assert fresh.process_state == "returned"
    history = list(
        (
            await db.execute(
                select(OrderStatusHistory).where(
                    OrderStatusHistory.order_id == order.id,
                    OrderStatusHistory.to_status == "returned",
                )
            )
        )
        .scalars()
        .all()
    )
    assert [h.from_status for h in history] == ["shipped"]


async def test_the_return_is_recorded_as_a_completed_saga(db, tenant_ctx) -> None:
    from app.modules.orders.returns import ReturnsService

    tenant_id = tenant_ctx.tenant_id
    order, _variant, _warehouse = await _order_at(db, tenant_id, "shipped", paid=True)

    saga = await ReturnsService.process_return(db, tenant_id, order.id)

    assert saga.saga_type == RETURN_SAGA_TYPE
    assert saga.aggregate_type == "order"
    assert saga.aggregate_id == order.id
    fresh = await _reload(db, saga.id)
    assert fresh.status == SagaStatus.COMPLETED.value
    assert fresh.current_step == 2
    assert [r["step"] for r in fresh.step_results] == [0, 1]


async def test_a_returned_order_is_not_returnable_again(db, tenant_ctx) -> None:
    from app.modules.orders.returns import ReturnsService

    tenant_id = tenant_ctx.tenant_id
    order, _variant, _warehouse = await _order_at(db, tenant_id, "shipped", paid=True)
    await ReturnsService.process_return(db, tenant_id, order.id)

    with pytest.raises(ConflictError):
        await ReturnsService.process_return(db, tenant_id, order.id)
    assert len((await db.execute(select(Saga).where(Saga.aggregate_id == order.id))).all()) == 1


# ----------------------------------------- the return process: cash on delivery ----


async def test_returning_an_unpaid_order_releases_the_hold(db, tenant_ctx) -> None:
    """A COD order's stock was never sold — it was held.

    Putting units back on the shelf here would invent stock: `on_hand` still
    carries them, and the only thing to undo is the reservation.
    """
    from app.modules.orders.returns import ReturnsService

    tenant_id = tenant_ctx.tenant_id
    order, variant, warehouse = await _order_at(db, tenant_id, "shipped", paid=False)
    held = await _balance(db, tenant_id, variant, warehouse)
    assert (held.on_hand, held.reserved) == (10, 3)

    await ReturnsService.process_return(db, tenant_id, order.id)

    after = await _balance(db, tenant_id, variant, warehouse)
    assert (after.on_hand, after.reserved) == (10, 0)
    fresh = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert fresh.process_state == "returned"  # it was `stock_reserved`: never paid
    # Nothing was ever taken off the shelf, so the return must record no
    # order-referenced movement at all. (`_movements` is order-scoped; the
    # `purchase` intake that stocked the warehouse belongs to no order.)
    assert [m.reason for m in await _movements(db, order.id)] == []
    reservations = list(
        (
            await db.execute(
                select(InventoryReservation).where(InventoryReservation.order_id == order.id)
            )
        )
        .scalars()
        .all()
    )
    assert [r.status for r in reservations] == ["CANCELLED"]


# --------------------------------------------------------- compensation ----


async def test_when_the_close_step_fails_the_restock_is_undone(db, tenant_ctx, monkeypatch) -> None:
    """The reason the engine exists: units that went back on the shelf must come
    back off, or the ledger reports stock the warehouse does not have.
    """
    from app.modules.orders.returns import ReturnsService

    tenant_id = tenant_ctx.tenant_id
    order, variant, warehouse = await _order_at(db, tenant_id, "shipped", paid=True)

    async def refuse(*args, **kwargs):
        raise RuntimeError("the order row refused")

    monkeypatch.setattr(OrderService, "_transition", refuse)

    with pytest.raises(RuntimeError):
        await ReturnsService.process_return(db, tenant_id, order.id)

    after = await _balance(db, tenant_id, variant, warehouse)
    assert after.on_hand == 7
    # _movements is order-scoped, so the warehouse's inbound `purchase` row is
    # not in this list. What must be here is the capture's `out/sale`, the
    # restock's `in/return`, and the compensation that takes them out again.
    assert sorted((m.direction, m.reason) for m in await _movements(db, order.id)) == [
        ("in", "return"),
        ("out", "return_reversal"),
        ("out", "sale"),
    ]
    fresh = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert fresh.status == "shipped"
    saga = (await db.execute(select(Saga).where(Saga.aggregate_id == order.id))).scalar_one()
    assert saga.status == SagaStatus.FAILED.value


# ------------------------------------- compensation of a released (COD) hold ----


async def test_an_undone_release_restores_the_reservation_it_released(
    db, tenant_ctx, monkeypatch
) -> None:
    """A re-held balance with no ACTIVE row is a lie the retry can act on.

    Compensation re-reserves the units, but the failed step cancelled the
    durable §140 row — so a retry reads "this order never held anything" and
    puts units on the shelf that were never taken off it.
    """
    from app.modules.orders.returns import ReturnsService

    tenant_id = tenant_ctx.tenant_id
    order, variant, warehouse = await _order_at(db, tenant_id, "shipped", paid=False)

    async def refuse(*args, **kwargs):
        raise RuntimeError("the order row refused")

    monkeypatch.setattr(OrderService, "_transition", refuse)
    with pytest.raises(RuntimeError):
        await ReturnsService.process_return(db, tenant_id, order.id)
    monkeypatch.undo()

    held = await _balance(db, tenant_id, variant, warehouse)
    assert (held.on_hand, held.reserved) == (10, 3)
    rows = (
        (
            await db.execute(
                select(InventoryReservation).where(InventoryReservation.order_id == order.id)
            )
        )
        .scalars()
        .all()
    )
    assert sorted(r.status for r in rows) == ["ACTIVE", "CANCELLED"]

    # The retry now starts from the position the first attempt started from:
    # the hold is released, and nothing is ever added to the shelf.
    await ReturnsService.process_return(db, tenant_id, order.id)
    final = await _balance(db, tenant_id, variant, warehouse)
    assert (final.on_hand, final.reserved) == (10, 0)
    assert [m.reason for m in await _movements(db, order.id)] == []


# ------------------------------------------------------------ the trigger ----


async def test_a_carrier_return_runs_the_same_process(db, tenant_ctx) -> None:
    """`in_transit -> returned` is the carrier saying the goods are back, so it
    cannot be a status that leaves the stock sold and the order open
    (ADR-051 decision 2, superseded here).
    """
    tenant_id = tenant_ctx.tenant_id
    order, variant, warehouse = await _order_at(db, tenant_id, "processing", paid=True)
    shipment = await OrderService.create_shipment(
        db, tenant_id, order.id, carrier="Aramex", tracking_number="T-1"
    )
    await OrderService.set_shipment_status(db, tenant_id, shipment.id, "picked_up")
    await OrderService.set_shipment_status(db, tenant_id, shipment.id, "in_transit")

    await OrderService.set_shipment_status(db, tenant_id, shipment.id, "returned")

    fresh = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert fresh.status == "returned"
    assert (await _balance(db, tenant_id, variant, warehouse)).on_hand == 10
    carrier_rows = list(
        (
            await db.execute(
                select(InventoryMovement).where(
                    InventoryMovement.reason == "return",
                    InventoryMovement.reference_id == order.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(carrier_rows) == 1


async def test_an_unshipped_order_cannot_be_returned(db, tenant_ctx) -> None:
    """The refusal must happen before the process starts, not half-way."""
    from app.modules.orders.returns import ReturnsService

    tenant_id = tenant_ctx.tenant_id
    order, variant, warehouse = await _order_at(db, tenant_id, "processing", paid=True)

    with pytest.raises(ConflictError):
        await ReturnsService.process_return(db, tenant_id, order.id)

    assert (await _balance(db, tenant_id, variant, warehouse)).on_hand == 7
    assert [m.reason for m in await _movements(db, order.id)] == ["sale"]
    fresh = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert fresh.status == "processing"
    assert (
        await db.execute(select(Saga).where(Saga.aggregate_id == order.id))
    ).scalar_one_or_none() is None


# ------------------------------------------------------------ the contract ----


def test_returned_is_a_state_both_machines_know() -> None:
    """The status machine and the saga machine must both admit `returned`, or an
    order says two different things about the same event.

    The saga half is the one CI caught: a paid order returns from `paid`, and a
    cash-on-delivery order that never settled returns from `stock_reserved`, so
    both must reach the terminal state. Only `delivered`/`completed` fulfil it.
    """
    assert "returned" in TRANSITIONS["shipped"]
    assert "returned" in TRANSITIONS["delivered"]

    from app.modules.orders.service import _PROCESS_TRANSITIONS

    for state in ("paid", "stock_reserved", "fulfilled"):
        assert "returned" in _PROCESS_TRANSITIONS[state], (
            f"an order at process_state={state!r} would be returned while its "
            "saga column still names the money"
        )
    assert _PROCESS_TRANSITIONS["returned"] == set()


def test_return_route_is_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert "/api/v1/orders/{order_id}/return" in paths


async def test_return_requires_orders_write(db: AsyncSession, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    order, _variant, _warehouse = await _order_at(db, tenant_id, "shipped", paid=True)

    ctx = TenantContext(
        session=db,
        user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_id, role_code="agent"),
        tenant_id=tenant_id,
        role_code="agent",
        permission_codes=set(),
    )
    app = create_app()

    async def _ctx() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _ctx
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/orders/{order.id}/return", json={})
    assert response.status_code == 403
