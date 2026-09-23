"""M9 — a hold is a real accounting event, so it is in the ledger.

`reserve()` and `release()` used to move `inventory_balances.reserved` and write
nothing, so the ledger could not explain why available differed from on-hand:
every `sale` row was visible and the hold that preceded it was not. Both now
append one row (direction `hold`/`release`, reason
`reservation`/`reservation_release`) and those rows never touch `on_hand` —
which is exactly what makes them distinguishable from the physical rows.

Three properties are pinned, and each is the half that was missing:

1. exactly one row per hold and per release (no double bookkeeping);
2. a release states what it freed and is attributable to a durable reservation,
   so `GET /inventory/movements?reservation_id=...` answers "what reserved this,
   and was it released";
3. over-release is impossible in the LEDGER, not only on the balance: the clamp
   that already protected `reserved` now also decides the quantity recorded, so
   the sum of a reservation's releases can never exceed its hold.

The return path is the live caller that must not double-count: capture converts
a hold into `release` + `out`/`sale` (one physical decrement), and a returned
parcel restocks once. `tests/test_return_saga.py` covers that arithmetic end to
end; `test_capture_releases_the_hold_and_sells_once` pins the ledger shape here.

Database-backed, so these skip locally and run in CI.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.inventory.models import (
    InventoryMovement,
    InventoryReservation,
    Warehouse,
)
from app.modules.inventory.service import InventoryReservationService, InventoryService
from app.modules.orders.service import OrderService


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    warehouse = Warehouse(
        tenant_id=tenant_id,
        name="Ledger WH",
        code=f"LW-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    return warehouse


async def _stocked_variant(
    db: AsyncSession, tenant_id: uuid.UUID, warehouse_id: uuid.UUID, qty: int
):
    product = await CatalogService.create_product(
        db, tenant_id, title="Ledger Product", slug=f"l-{uuid.uuid4().hex[:10]}"
    )
    # M4: this fixture feeds checkout, and only an active product sells.
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(db, tenant_id, product.id, price="10.00")
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        warehouse_id,
        direction="in",
        quantity=qty,
        reason="purchase",
    )
    return variant


async def _rows(db: AsyncSession, variant_id: uuid.UUID) -> list[InventoryMovement]:
    return list(
        (
            await db.execute(
                select(InventoryMovement).where(
                    InventoryMovement.variant_id == variant_id
                )
            )
        )
        .scalars()
        .all()
    )


def _shape(rows: list[InventoryMovement], *fields: str) -> list[tuple]:
    """Rows as a sorted multiset.

    Every ledger row written inside one transaction shares a `created_at`
    (`now()` is transaction-stable), so a timestamp ORDER BY falls through to a
    random UUID. What these tests pin is that each fact appears EXACTLY ONCE —
    a multiset says that as precisely as a sequence, without betting on ids.
    """
    return sorted(tuple(getattr(m, f) for f in fields) for m in rows)


async def _held_rows(db: AsyncSession, variant_id: uuid.UUID) -> list[InventoryMovement]:
    return [m for m in await _rows(db, variant_id) if m.direction == "hold"]


async def _released_rows(db: AsyncSession, variant_id: uuid.UUID) -> list[InventoryMovement]:
    return [m for m in await _rows(db, variant_id) if m.direction == "release"]


async def _reservation(db: AsyncSession, order_id: uuid.UUID) -> InventoryReservation:
    return (
        await db.execute(
            select(InventoryReservation).where(
                InventoryReservation.order_id == order_id
            )
        )
    ).scalar_one()


async def _order_holding_stock(
    db: AsyncSession, tenant_id: uuid.UUID, *, qty: int = 3
) -> tuple[object, object, Warehouse]:
    """A real checkout: it reserves the balance AND registers the line."""
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Ledger Buyer"
    )
    warehouse = await _warehouse(db, tenant_id)
    variant = await _stocked_variant(db, tenant_id, warehouse.id, qty=10)
    order = await OrderService.create_order(
        db,
        tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": qty}],
        warehouse_id=warehouse.id,
    )
    return order, variant, warehouse


# ------------------------------------------------------- the hold row -------


async def test_a_reserve_writes_exactly_one_availability_row(
    db: AsyncSession, tenant_ctx
) -> None:
    tenant_id = tenant_ctx.tenant_id
    wh = await _warehouse(db, tenant_id)
    variant = await _stocked_variant(db, tenant_id, wh.id, qty=10)

    await InventoryService.reserve(db, tenant_id, variant.id, wh.id, 4)

    holds = await _held_rows(db, variant.id)
    assert _shape(holds, "reason", "quantity", "balance_after") == [
        ("reservation", 4, 10)
    ]
    # A hold moves availability, never the physical position.
    assert holds[0].reference_type is None
    balance = await InventoryService.get_balance(db, tenant_id, variant.id, wh.id)
    assert (balance.on_hand, balance.reserved) == (10, 4)


async def test_a_failed_reserve_writes_nothing(db: AsyncSession, tenant_ctx) -> None:
    """The guard that was already there must still fire, and a rejected hold
    must leave no trace in the ledger."""
    from app.modules.orders.errors import InsufficientStockError

    tenant_id = tenant_ctx.tenant_id
    wh = await _warehouse(db, tenant_id)
    variant = await _stocked_variant(db, tenant_id, wh.id, qty=1)

    with pytest.raises(InsufficientStockError):
        await InventoryService.reserve(db, tenant_id, variant.id, wh.id, 2)

    assert await _held_rows(db, variant.id) == []
    assert (
        await InventoryService.get_balance(db, tenant_id, variant.id, wh.id)
    ).reserved == 0


# ----------------------------------------------------- the release row ------


async def test_a_release_writes_one_row_attributed_to_what_it_released(
    db: AsyncSession, tenant_ctx
) -> None:
    tenant_id = tenant_ctx.tenant_id
    order, variant, wh = await _order_holding_stock(db, tenant_id, qty=3)

    await InventoryService.release(db, tenant_id, variant.id, wh.id, 3)

    holds = await _held_rows(db, variant.id)
    releases = await _released_rows(db, variant.id)
    assert len(holds) == 1 and len(releases) == 1
    reservation = await _reservation(db, order.id)
    # The hold is reachable from the reservation (it predates the row), and the
    # release names the reservation — the pair is checkable in both directions.
    assert holds[0].id == reservation.hold_movement_id
    assert (releases[0].reference_type, releases[0].reference_id) == (
        "inventory_reservation",
        reservation.id,
    )
    assert releases[0].quantity == 3
    assert releases[0].balance_after == 10
    balance = await InventoryService.get_balance(db, tenant_id, variant.id, wh.id)
    assert (balance.on_hand, balance.reserved) == (10, 0)


async def test_an_over_release_records_only_what_was_actually_freed(
    db: AsyncSession, tenant_ctx
) -> None:
    """The clamp on `reserved` already stopped the second release stealing
    another order's hold; recording the ACTUAL quantity is what stops the ledger
    claiming stock was freed twice."""
    tenant_id = tenant_ctx.tenant_id
    order, variant, wh = await _order_holding_stock(db, tenant_id, qty=3)
    reservation = await _reservation(db, order.id)

    await InventoryService.release(db, tenant_id, variant.id, wh.id, 3)
    again = await InventoryService.release(db, tenant_id, variant.id, wh.id, 3)

    assert again.reserved == 0
    releases = await _released_rows(db, variant.id)
    assert _shape(releases, "reason", "quantity") == [("reservation_release", 3)]
    recorded = (
        await db.execute(
            select(func.sum(InventoryMovement.quantity)).where(
                InventoryMovement.reason == "reservation_release",
                InventoryMovement.reference_id == reservation.id,
            )
        )
    ).scalar_one()
    assert recorded == reservation.quantity  # never more than what was held


async def test_a_partial_release_records_the_partial(db: AsyncSession, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    _order, variant, wh = await _order_holding_stock(db, tenant_id, qty=5)

    await InventoryService.release(db, tenant_id, variant.id, wh.id, 2)

    assert (
        await InventoryService.get_balance(db, tenant_id, variant.id, wh.id)
    ).reserved == 3
    assert [m.quantity for m in await _released_rows(db, variant.id)] == [2]


# ------------------------------------------------- the reservation filter ---


async def test_movements_can_be_read_back_per_reservation(
    db: AsyncSession, tenant_ctx
) -> None:
    """`GET /inventory/movements?reservation_id=` is only promised because the
    linkage exists: this is the pair, in one query."""
    tenant_id = tenant_ctx.tenant_id
    order, variant, wh = await _order_holding_stock(db, tenant_id, qty=3)
    reservation = await _reservation(db, order.id)

    await InventoryService.release(db, tenant_id, variant.id, wh.id, 3)

    rows = await InventoryService.list_movements(
        db, tenant_id, reservation_id=reservation.id
    )
    assert _shape(rows, "direction", "reason", "quantity") == [
        ("hold", "reservation", 3),
        ("release", "reservation_release", 3),
    ]

    # The reason filter reads the availability rows too.
    holds = await InventoryService.list_movements(db, tenant_id, reason="reservation")
    assert [m.id for m in holds] == [reservation.hold_movement_id]


async def test_the_reservation_filter_returns_that_pair_and_nothing_else(
    db: AsyncSession, tenant_ctx
) -> None:
    """Two live holds on the same variant: 'was it released?' must answer about
    the reservation named, not about every reservation-referencing row."""
    tenant_id = tenant_ctx.tenant_id
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Buyer"
    )
    warehouse = await _warehouse(db, tenant_id)
    variant = await _stocked_variant(db, tenant_id, warehouse.id, qty=10)
    orders = [
        await OrderService.create_order(
            db,
            tenant_id,
            customer.id,
            [{"variant_id": variant.id, "quantity": 3}],
            warehouse_id=warehouse.id,
        )
        for _ in range(2)
    ]
    settled = await _reservation(db, orders[0].id)
    waiting = await _reservation(db, orders[1].id)

    assert await InventoryReservationService.convert(db, tenant_id, orders[0].id) == 1

    rows = await InventoryService.list_movements(
        db, tenant_id, reservation_id=settled.id
    )
    assert _shape(rows, "direction", "quantity") == [
        ("hold", 3),
        ("release", 3),
    ]
    # The other order still holds its stock: nothing of its own is released.
    assert _shape(
        await InventoryService.list_movements(db, tenant_id, reservation_id=waiting.id),
        "direction",
        "quantity",
    ) == [("hold", 3)]


async def test_an_unknown_reason_filter_is_a_refusal_not_an_empty_200(
    db: AsyncSession, tenant_ctx
) -> None:
    from app.modules.errors import ValidationError

    with pytest.raises(ValidationError):
        await InventoryService.list_movements(
            db, tenant_ctx.tenant_id, reason="whatever-i-liked"
        )


# ------------------------------------------- the paths that settle a hold ---


async def test_capture_releases_the_hold_and_sells_once(
    db: AsyncSession, tenant_ctx
) -> None:
    """No double count: converting a reservation decrements `on_hand` exactly
    once (the `out`/sale row) and closes the hold with its own row."""
    tenant_id = tenant_ctx.tenant_id
    order, variant, wh = await _order_holding_stock(db, tenant_id, qty=3)

    assert await InventoryReservationService.convert(db, tenant_id, order.id) == 1

    balance = await InventoryService.get_balance(db, tenant_id, variant.id, wh.id)
    assert (balance.on_hand, balance.reserved) == (7, 0)
    rows = await _rows(db, variant.id)
    assert _shape(rows, "direction", "reason", "quantity") == [
        ("hold", "reservation", 3),
        ("in", "purchase", 10),
        ("out", "sale", 3),
        ("release", "reservation_release", 3),
    ]
    # Only the physical rows add up to the position; the pair nets to zero.
    physical = sum(
        m.quantity for m in rows if m.direction == "in"
    ) - sum(m.quantity for m in rows if m.direction == "out")
    assert physical == balance.on_hand
    reservation = await _reservation(db, order.id)
    assert [m.reference_id for m in rows if m.direction == "release"] == [reservation.id]


async def test_the_expiry_sweep_states_what_it_released(
    db: AsyncSession, tenant_ctx
) -> None:
    """`expire_stale` freed availability and used to write nothing, so an
    abandoned cart looked like stock that was never held."""
    tenant_id = tenant_ctx.tenant_id
    order, variant, wh = await _order_holding_stock(db, tenant_id, qty=3)
    reservation = await _reservation(db, order.id)
    reservation.expires_at = reservation.expires_at - timedelta(hours=1)
    await db.flush()

    assert await InventoryReservationService.expire_stale(db, tenant_id) == 1

    assert (await InventoryService.get_balance(db, tenant_id, variant.id, wh.id)).reserved == 0
    releases = await _released_rows(db, variant.id)
    assert [(m.quantity, m.reference_id) for m in releases] == [(3, reservation.id)]


# --------------------------------------------------------- untouched paths --


async def test_a_return_restocks_once_after_capture(db: AsyncSession, tenant_ctx) -> None:
    """The restock-on-return saga (ADR-052) must not now double-count: the
    capture's `out`/sale and the return's `in`/return are the only physical
    rows, and the hold pair nets to zero."""
    from app.modules.orders.returns import ReturnsService

    tenant_id = tenant_ctx.tenant_id
    order, variant, wh = await _order_holding_stock(db, tenant_id, qty=3)
    await OrderService.add_payment(
        db, tenant_id, order.id, method="cash", amount=Decimal("30.00")
    )
    for status in ("processing", "shipped"):
        await OrderService.change_status(db, tenant_id, order.id, status)

    await ReturnsService.process_return(db, tenant_id, order.id)

    balance = await InventoryService.get_balance(db, tenant_id, variant.id, wh.id)
    assert (balance.on_hand, balance.reserved) == (10, 0)
    rows = await _rows(db, variant.id)
    assert _shape(rows, "direction", "reason") == [
        ("hold", "reservation"),
        ("in", "purchase"),
        ("in", "return"),
        ("out", "sale"),
        ("release", "reservation_release"),
    ]


async def test_a_cancelled_order_records_one_release_for_its_hold(
    db: AsyncSession, tenant_ctx
) -> None:
    """Cancellation goes through OrderService, which releases per line and then
    flips the durable rows — one hold row, one release row, stock whole again."""
    tenant_id = tenant_ctx.tenant_id
    order, variant, wh = await _order_holding_stock(db, tenant_id, qty=3)
    reservation = await _reservation(db, order.id)

    await OrderService.cancel_order(db, tenant_id, order.id)

    balance = await InventoryService.get_balance(db, tenant_id, variant.id, wh.id)
    assert (balance.on_hand, balance.reserved) == (10, 0)
    assert [m.quantity for m in await _released_rows(db, variant.id)] == [3]
    assert [m.reference_id for m in await _released_rows(db, variant.id)] == [
        reservation.id
    ]
    assert (await _reservation(db, order.id)).status == "CANCELLED"
