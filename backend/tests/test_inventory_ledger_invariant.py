"""The ledger's core promise: `on_hand == Σ signed physical movements`.

`inventory_movements` is the reason `inventory_balances.on_hand` is a fact and
not a guess. A capture (`InventoryReservationService.convert`) settles a hold
into a sale, and until now it wrote the FULL reservation quantity into the
ledger while clamping the column with `max(0, on_hand - qty)`. On a drifted
position — a hand-corrected row, a partial stocktake, shrinkage after the
checkout — the row and the column therefore disagreed by exactly the shortfall,
and the clamp made that permanent: the ledger then claimed more had left than
the warehouse ever held, and no reconciliation could tell which side lied.

The choice made here is to REFUSE. That is not a new rule, it is the module's
existing one: `move(direction="out")` already raises `InsufficientStockError`
rather than clamping, and so does `reserve()`. Capture was the only physical
writer that clamped instead of refusing, so the identical sale was a 409 through
`POST /inventory/movements` and a silent rewrite of history through payment
capture. See `check_physical_settlement` for why neither clamping the row nor
appending a compensating row was chosen.

Two kinds of proof, and the split matters:

* the settlement check itself is PURE, so it runs here and now
  (`tests/test_inventory_movement_contract.py` is the precedent for validating a
  guard with no session at all);
* the ledger sequences need the real database with RLS, so they skip locally and
  are proven in CI.

"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory import service as inventory_service
from app.modules.inventory.models import (
    InventoryBalance,
    InventoryMovement,
    InventoryReservation,
    Warehouse,
)
from app.modules.inventory.service import (
    InventoryReservationService,
    InventoryService,
)

# ------------------------------------------------------------- helpers ------


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    warehouse = Warehouse(
        tenant_id=tenant_id,
        name="Reconcile WH",
        code=f"RW-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    return warehouse


async def _variant(db: AsyncSession, tenant_id: uuid.UUID):
    from app.modules.catalog.service import CatalogService

    product = await CatalogService.create_product(
        db, tenant_id, title="Reconcile Product", slug=f"r-{uuid.uuid4().hex[:10]}"
    )
    # M4: only an active product sells, and these fixtures go through checkout.
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    return await CatalogService.add_variant(db, tenant_id, product.id, price="10.00")


async def _restock(
    db: AsyncSession, tenant_id: uuid.UUID, variant_id: uuid.UUID, wh_id: uuid.UUID, qty: int
) -> None:
    await InventoryService.move(
        db,
        tenant_id,
        variant_id,
        wh_id,
        direction="in",
        quantity=qty,
        reason="purchase",
    )


async def _order(
    db: AsyncSession, tenant_id: uuid.UUID, variant_id: uuid.UUID, wh_id: uuid.UUID, qty: int
):
    from app.modules.customers.service import CustomerService
    from app.modules.orders.service import OrderService

    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Buyer"
    )
    return await OrderService.create_order(
        db,
        tenant_id,
        customer.id,
        [{"variant_id": variant_id, "quantity": qty}],
        warehouse_id=wh_id,
    )


async def _rows(
    db: AsyncSession, variant_id: uuid.UUID, wh_id: uuid.UUID
) -> list[InventoryMovement]:
    return list(
        (
            await db.execute(
                select(InventoryMovement).where(
                    InventoryMovement.variant_id == variant_id,
                    InventoryMovement.warehouse_id == wh_id,
                )
            )
        )
        .scalars()
        .all()
    )


async def _balance(
    db: AsyncSession, tenant_id: uuid.UUID, variant_id: uuid.UUID, wh_id: uuid.UUID
) -> InventoryBalance:
    return await InventoryService.get_balance(db, tenant_id, variant_id, wh_id)


def _signed(rows: list[InventoryMovement], directions: dict[str, int]) -> int:
    """Σ quantity × sign over the named directions; other rows are ignored.

    `adjust` is deliberately absent from every call below: it carries an
    ABSOLUTE count (a stocktake), so it is reconciled through its own
    `balance_after` rather than added. A history containing one is not a
    history this sum describes, which is why the fixtures here move stock only
    through additive rows — that is the general case, and the drift they
    reproduce is the one capture actually hits.
    """
    return sum(m.quantity * directions[m.direction] for m in rows if m.direction in directions)


PHYSICAL = {"in": 1, "out": -1}
AVAILABILITY = {"hold": 1, "release": -1}


async def _assert_ledger_reconciles(
    db: AsyncSession, tenant_id: uuid.UUID, variant_id: uuid.UUID, wh_id: uuid.UUID
) -> None:
    """The invariant, in both of its halves.

    `on_hand` is the ledger's sum of the physical rows and `reserved` the sum of
    the availability rows — nothing else writes either column, so a divergence
    is a bug, not a rounding difference.
    """
    rows = await _rows(db, variant_id, wh_id)
    balance = await _balance(db, tenant_id, variant_id, wh_id)
    assert _signed(rows, PHYSICAL) == balance.on_hand
    assert _signed(rows, AVAILABILITY) == balance.reserved


# ----------------------------------------------- the pure settlement check --


def test_a_settlement_the_position_covers_books_in_full() -> None:
    """Nothing about a healthy capture changes: the check is the quantity."""
    assert (
        inventory_service.check_physical_settlement(
            on_hand=3, quantity=3, variant_id=uuid.uuid4(), warehouse_id=uuid.uuid4()
        )
        == 3
    )


def test_a_settlement_the_position_cannot_cover_is_refused_not_clamped() -> None:
    """THE defect, as a unit test: 3 may leave a shelf holding 2, but not
    silently. Returning `2` — the clamp's applied delta — would keep the sums
    equal while booking a sale the order line never was, which is the behaviour
    this check exists to make impossible."""
    with pytest.raises(inventory_service.InsufficientStockError):
        inventory_service.check_physical_settlement(
            on_hand=2, quantity=3, variant_id=uuid.uuid4(), warehouse_id=uuid.uuid4()
        )


def test_an_empty_shelf_refuses_rather_than_settling_at_zero() -> None:
    """`max(0, …)` read as "the clamp is harmless when the position is already
    zero"; a zero position selling nothing is the same lie at full size."""
    with pytest.raises(inventory_service.InsufficientStockError):
        inventory_service.check_physical_settlement(
            on_hand=0, quantity=1, variant_id=uuid.uuid4(), warehouse_id=uuid.uuid4()
        )


def test_the_refusal_names_the_shortfall_a_must_fix() -> None:
    """A refusal that only says "insufficient stock" gets retried. The message
    has to carry on_hand, the requested quantity and the position, so whoever
    sees it knows the shelf is short by N and restocks through the ledger."""
    variant_id = uuid.uuid4()
    warehouse_id = uuid.uuid4()
    with pytest.raises(inventory_service.InsufficientStockError) as exc:
        inventory_service.check_physical_settlement(
            on_hand=2, quantity=5, variant_id=variant_id, warehouse_id=warehouse_id
        )
    message = str(exc.value)
    assert "on_hand=2" in message
    assert "sale=5" in message
    assert str(variant_id) in message and str(warehouse_id) in message


# ------------------------------------------------- the invariant, for real --


async def test_the_ledger_reconciles_across_reserve_capture_and_release(
    db: AsyncSession, tenant_ctx
) -> None:
    """The normal path first, so the invariant is proven before it is defended.

    One variant, one warehouse, and every settling path in the module: a hold, a
    capture that converts a hold into a sale, a cancellation that hands stock
    back, and a physical shrinkage. After all of them the two columns still mean
    what the rows say.
    """
    tenant_id = tenant_ctx.tenant_id
    wh = await _warehouse(db, tenant_id)
    variant = await _variant(db, tenant_id)
    await _restock(db, tenant_id, variant.id, wh.id, 10)
    await _assert_ledger_reconciles(db, tenant_id, variant.id, wh.id)

    sold = await _order(db, tenant_id, variant.id, wh.id, 3)
    await _assert_ledger_reconciles(db, tenant_id, variant.id, wh.id)
    assert await InventoryReservationService.convert(db, tenant_id, sold.id) == 1
    await _assert_ledger_reconciles(db, tenant_id, variant.id, wh.id)

    cancelled = await _order(db, tenant_id, variant.id, wh.id, 2)
    from app.modules.orders.service import OrderService

    await OrderService.cancel_order(db, tenant_id, cancelled.id)
    await _assert_ledger_reconciles(db, tenant_id, variant.id, wh.id)

    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        wh.id,
        direction="out",
        quantity=1,
        reason="damage",
    )
    await _assert_ledger_reconciles(db, tenant_id, variant.id, wh.id)

    balance = await _balance(db, tenant_id, variant.id, wh.id)
    assert (balance.on_hand, balance.reserved) == (6, 0)
    # And the sums are the columns, not a hand-tuned pair: 10 in, 3 sold, 1
    # shrunk; two holds and two releases that net to nothing.
    rows = await _rows(db, variant.id, wh.id)
    assert _signed(rows, PHYSICAL) == 10 - 3 - 1
    assert _signed(rows, AVAILABILITY) == 0


async def test_a_drifted_position_refuses_the_capture_instead_of_hiding_it(
    db: AsyncSession, tenant_ctx
) -> None:
    """on_hand(2) < reservation.quantity(3): the clamp wrote an `out` row of 3
    AND zeroed the column, so the ledger ended up claiming one more unit left
    the warehouse than the shelf ever held. Refusing leaves both sums exactly as
    they were — that is the assertion that separates the fix from the clamp.

    The drift is seeded the way it arises in production and entirely through the
    ledger: stock is held, and a shrinkage the warehouse discovers afterwards
    takes the shelf down below the hold. `move(out)` guards `on_hand`, not
    availability, so this state is reachable today with a legitimate row.
    """
    tenant_id = tenant_ctx.tenant_id
    wh = await _warehouse(db, tenant_id)
    variant = await _variant(db, tenant_id)
    await _restock(db, tenant_id, variant.id, wh.id, 10)
    order = await _order(db, tenant_id, variant.id, wh.id, 3)

    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        wh.id,
        direction="out",
        quantity=8,
        reason="damage",
    )
    balance = await _balance(db, tenant_id, variant.id, wh.id)
    assert (balance.on_hand, balance.reserved) == (2, 3)
    await _assert_ledger_reconciles(db, tenant_id, variant.id, wh.id)

    before = await _rows(db, variant.id, wh.id)
    from app.modules.orders.errors import InsufficientStockError

    with pytest.raises(InsufficientStockError, match="on_hand=2"):
        await InventoryReservationService.convert(db, tenant_id, order.id)

    # Nothing was written: no `out`/sale, no `release`, and the hold it would
    # have closed is still an ACTIVE reservation.
    after = await _rows(db, variant.id, wh.id)
    assert len(after) == len(before)
    reservation = (
        await db.execute(
            select(InventoryReservation).where(InventoryReservation.order_id == order.id)
        )
    ).scalar_one()
    assert reservation.status == "ACTIVE"
    assert reservation.converted_at is None
    balance = await _balance(db, tenant_id, variant.id, wh.id)
    assert (balance.on_hand, balance.reserved) == (2, 3)
    # The sums still mean the columns — the drift is visible as a hold larger
    # than the shelf, which is the state a human can act on.
    await _assert_ledger_reconciles(db, tenant_id, variant.id, wh.id)


async def test_restocking_the_drift_lets_the_same_capture_settle(
    db: AsyncSession, tenant_ctx
) -> None:
    """A refusal has to be recoverable through the LEDGER, not by editing a row.

    The reason `adjust` (or a purchase) is the fix: it carries its own movement
    and its own `balance_after`, so the drift's story stays in the ledger. Once
    the shelf covers the hold again, the capture proceeds and every sum agrees.
    """
    tenant_id = tenant_ctx.tenant_id
    wh = await _warehouse(db, tenant_id)
    variant = await _variant(db, tenant_id)
    await _restock(db, tenant_id, variant.id, wh.id, 10)
    order = await _order(db, tenant_id, variant.id, wh.id, 3)
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        wh.id,
        direction="out",
        quantity=8,
        reason="damage",
    )

    await _restock(db, tenant_id, variant.id, wh.id, 3)

    assert await InventoryReservationService.convert(db, tenant_id, order.id) == 1

    balance = await _balance(db, tenant_id, variant.id, wh.id)
    assert (balance.on_hand, balance.reserved) == (2, 0)
    await _assert_ledger_reconciles(db, tenant_id, variant.id, wh.id)
    rows = await _rows(db, variant.id, wh.id)
    assert _signed(rows, PHYSICAL) == 10 - 8 + 3 - 3
    assert sorted(m.reason for m in rows if m.direction == "out") == ["damage", "sale"]
    reservation = (
        await db.execute(
            select(InventoryReservation).where(InventoryReservation.order_id == order.id)
        )
    ).scalar_one()
    assert reservation.status == "CONVERTED"
