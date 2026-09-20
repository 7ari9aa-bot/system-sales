"""CUSTOMER 360 tests (spec W5) — the composed record, its timeline, and the
``customer_id`` list filters that the record page depends on.

Two classes of test live here:

* DB-free guards that every new route/query parameter is actually exposed, so
  a filter cannot be implemented in the service but forgotten in the router.
* DB-backed tests for the projection itself, including the cross-tenant guard.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.customers.models import CustomerEvent
from app.modules.customers.service import CustomerService
from app.modules.customers.timeline import Customer360Service
from app.modules.errors import NotFoundError
from app.modules.operations.models import Task
from app.modules.orders.models import Order, OrderPayment, Refund
from app.modules.orders.service import OrderService

BASE = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return BASE + timedelta(minutes=minutes)


# ------------------------------------------------------- route surface -----


def test_360_route_is_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert "/api/v1/customers/{customer_id}/360" in paths


@pytest.mark.parametrize(
    "path",
    ["/api/v1/orders", "/api/v1/conversations", "/api/v1/tasks"],
)
def test_list_routes_expose_the_customer_filter(path: str) -> None:
    """The record page pages by customer; the param must be on the wire.

    Without this the service could filter correctly while the router still
    ignores the argument, which is exactly how the drawer ended up filtering a
    tenant-wide page in the browser.
    """
    spec = create_app().openapi()
    params = spec["paths"][path]["get"].get("parameters", [])
    assert "customer_id" in {p["name"] for p in params}


# ------------------------------------------------------------- fixtures ----


async def _customer(db: AsyncSession, tenant_id: uuid.UUID, name: str = "Nour"):
    return await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:12]}", name=name
    )


async def _order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    *,
    minutes: int,
    total: str = "100.00",
    status: str = "confirmed",
) -> Order:
    order = Order(
        tenant_id=tenant_id,
        customer_id=customer_id,
        number=f"ORD-{uuid.uuid4().hex[:8]}",
        status=status,
        currency="EGP",
        grand_total=Decimal(total),
        created_at=_at(minutes),
    )
    db.add(order)
    await db.flush()
    return order


async def _payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    order_id: uuid.UUID,
    *,
    amount: str,
    status: str = "captured",
) -> OrderPayment:
    payment = OrderPayment(
        tenant_id=tenant_id,
        order_id=order_id,
        method="cash",
        status=status,
        amount=Decimal(amount),
        currency="EGP",
    )
    db.add(payment)
    await db.flush()
    return payment


# ------------------------------------------------------------ list_events --


async def test_list_events_returns_newest_first(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)

    for minutes, kind in ((10, "first"), (30, "third"), (20, "second")):
        db.add(
            CustomerEvent(
                tenant_id=tenant_id,
                customer_id=customer.id,
                event_type=kind,
                payload={"m": minutes},
                created_at=_at(minutes),
            )
        )
    await db.flush()

    events = await CustomerService.list_events(db, tenant_id, customer.id)
    assert [e.event_type for e in events] == ["third", "second", "first"]


async def test_list_events_refuses_an_unknown_customer(db: AsyncSession, tenant_ctx):
    """A 360 request for a missing customer must 404, never return empty."""
    with pytest.raises(NotFoundError):
        await CustomerService.list_events(db, tenant_ctx.tenant_id, uuid.uuid4())


# ------------------------------------------------------------------- 360 ---


async def test_360_on_a_bare_customer_is_empty_not_an_error(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)

    record = await Customer360Service.build(db, tenant_id, customer.id)

    assert record["customer"]["id"] == str(customer.id)
    for section in ("orders", "conversations", "tasks", "timeline", "notes"):
        assert record[section] == []
    assert record["stats"]["open_tasks"] == 0
    assert record["stats"]["unread_messages"] == 0
    # No orders means no committed value and nothing owed.
    assert Decimal(record["payments"]["orders_total"]) == Decimal("0")
    assert Decimal(record["payments"]["outstanding"]) == Decimal("0")


async def test_360_orders_and_payments_belong_to_this_customer_only(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    mine = await _customer(db, tenant_id, "Mine")
    theirs = await _customer(db, tenant_id, "Theirs")

    my_order = await _order(db, tenant_id, mine.id, minutes=10, total="250.00")
    await _order(db, tenant_id, theirs.id, minutes=20, total="999.00")
    await _payment(db, tenant_id, my_order.id, amount="250.00")

    record = await Customer360Service.build(db, tenant_id, mine.id)

    assert [o["number"] for o in record["orders"]] == [my_order.number]
    assert Decimal(record["payments"]["orders_total"]) == Decimal("250.00")
    assert Decimal(record["payments"]["paid_total"]) == Decimal("250.00")
    assert Decimal(record["payments"]["outstanding"]) == Decimal("0")
    assert record["payments"]["payment_count"] == 1


async def test_360_excludes_cancelled_orders_from_committed_value(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)

    await _order(db, tenant_id, customer.id, minutes=10, total="300.00")
    await _order(
        db, tenant_id, customer.id, minutes=20, total="500.00", status="cancelled"
    )

    record = await Customer360Service.build(db, tenant_id, customer.id)

    # Both orders are still listed (history is history) ...
    assert len(record["orders"]) == 2
    # ... but the cancelled one is not counted as committed value.
    assert Decimal(record["payments"]["orders_total"]) == Decimal("300.00")


async def test_360_outstanding_is_committed_minus_net_collected(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)

    order = await _order(db, tenant_id, customer.id, minutes=10, total="400.00")
    await _payment(db, tenant_id, order.id, amount="150.00")

    record = await Customer360Service.build(db, tenant_id, customer.id)

    assert Decimal(record["payments"]["paid_total"]) == Decimal("150.00")
    assert Decimal(record["payments"]["outstanding"]) == Decimal("250.00")


async def test_360_refunds_reduce_net_collected(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)

    order = await _order(db, tenant_id, customer.id, minutes=10, total="400.00")
    payment = await _payment(db, tenant_id, order.id, amount="400.00")
    db.add(
        Refund(
            tenant_id=tenant_id,
            payment_id=payment.id,
            amount=Decimal("100.00"),
            status="processed",
        )
    )
    # A rejected refund must not move the numbers.
    db.add(
        Refund(
            tenant_id=tenant_id,
            payment_id=payment.id,
            amount=Decimal("50.00"),
            status="rejected",
        )
    )
    await db.flush()

    record = await Customer360Service.build(db, tenant_id, customer.id)

    assert Decimal(record["payments"]["refunded_total"]) == Decimal("100.00")
    assert Decimal(record["payments"]["net_collected"]) == Decimal("300.00")
    assert Decimal(record["payments"]["outstanding"]) == Decimal("100.00")


async def test_360_timeline_merges_every_source_newest_first(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)

    await _order(db, tenant_id, customer.id, minutes=10)
    db.add(
        CustomerEvent(
            tenant_id=tenant_id,
            customer_id=customer.id,
            event_type="channel.message",
            payload={"body": "hi"},
            created_at=_at(20),
        )
    )
    db.add(
        Task(
            tenant_id=tenant_id,
            title="Follow up",
            related_entity_type="customer",
            related_entity_id=customer.id,
            created_at=_at(30),
        )
    )
    await db.flush()

    record = await Customer360Service.build(db, tenant_id, customer.id)
    timeline = record["timeline"]

    kinds = [entry["kind"] for entry in timeline]
    assert kinds == ["task", "event", "order"]
    timestamps = [entry["at"] for entry in timeline]
    assert timestamps == sorted(timestamps, reverse=True)


async def test_360_timeline_respects_its_limit(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)

    for minutes in range(1, 12):
        await _order(db, tenant_id, customer.id, minutes=minutes)

    record = await Customer360Service.build(
        db, tenant_id, customer.id, limit=20, timeline_limit=5
    )

    assert len(record["timeline"]) == 5
    # The newest five, not the oldest.
    assert record["timeline"][0]["at"] > record["timeline"][-1]["at"]


async def test_360_tasks_only_include_this_customer(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    mine = await _customer(db, tenant_id, "Mine")
    theirs = await _customer(db, tenant_id, "Theirs")

    db.add(
        Task(
            tenant_id=tenant_id,
            title="Mine",
            related_entity_type="customer",
            related_entity_id=mine.id,
        )
    )
    db.add(
        Task(
            tenant_id=tenant_id,
            title="Theirs",
            related_entity_type="customer",
            related_entity_id=theirs.id,
        )
    )
    # A task on an unrelated entity type must never leak into a customer view.
    db.add(
        Task(
            tenant_id=tenant_id,
            title="Not a customer",
            related_entity_type="order",
            related_entity_id=mine.id,
        )
    )
    await db.flush()

    record = await Customer360Service.build(db, tenant_id, mine.id)

    assert [t["title"] for t in record["tasks"]] == ["Mine"]


async def test_360_stats_report_open_tasks_and_unread(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)

    for title, status in (("a", "todo"), ("b", "in_progress"), ("c", "done")):
        db.add(
            Task(
                tenant_id=tenant_id,
                title=title,
                status=status,
                related_entity_type="customer",
                related_entity_id=customer.id,
            )
        )
    await db.flush()

    record = await Customer360Service.build(db, tenant_id, customer.id)

    assert record["stats"]["tasks_shown"] == 3
    assert record["stats"]["open_tasks"] == 2


# --------------------------------------------------- cross-tenant guards ---


async def test_360_cannot_read_a_customer_from_another_tenant(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)

    with pytest.raises(NotFoundError):
        await Customer360Service.build(db, uuid.uuid4(), customer.id)


async def test_360_requires_the_customer_to_exist(db: AsyncSession, tenant_ctx):
    with pytest.raises(NotFoundError):
        await Customer360Service.build(db, tenant_ctx.tenant_id, uuid.uuid4())


# ------------------------------------------------------- list filtering ----


async def test_order_list_filters_by_customer(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    mine = await _customer(db, tenant_id, "Mine")
    theirs = await _customer(db, tenant_id, "Theirs")

    await _order(db, tenant_id, mine.id, minutes=10)
    await _order(db, tenant_id, theirs.id, minutes=20)

    scoped = await OrderService.list_orders(db, tenant_id, customer_id=mine.id)
    everything = await OrderService.list_orders(db, tenant_id)

    assert len(scoped) == 1
    assert scoped[0].customer_id == mine.id
    assert len(everything) == 2


async def test_order_list_filter_composes_with_status(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)

    await _order(db, tenant_id, customer.id, minutes=10, status="confirmed")
    await _order(db, tenant_id, customer.id, minutes=20, status="cancelled")

    confirmed = await OrderService.list_orders(
        db, tenant_id, customer_id=customer.id, status="confirmed"
    )
    assert len(confirmed) == 1
    assert confirmed[0].status == "confirmed"


async def test_events_written_by_record_event_are_readable(
    db: AsyncSession, tenant_ctx
):
    """The timeline was write-only before; this is the round trip."""
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)

    await CustomerService.record_event(
        db, tenant_id, customer.id, "customer.created", {"source": "whatsapp"}
    )

    stored = (
        await db.execute(
            select(CustomerEvent).where(CustomerEvent.customer_id == customer.id)
        )
    ).scalars().all()
    assert len(stored) == 1

    events = await CustomerService.list_events(db, tenant_id, customer.id)
    assert events[0].event_type == "customer.created"
    assert events[0].payload == {"source": "whatsapp"}
