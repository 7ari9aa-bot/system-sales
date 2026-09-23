"""InventoryService tests — movements, reservations, transfers."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import ProductVariant
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, NotFoundError
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders.errors import InsufficientStockError


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    warehouse = Warehouse(
        tenant_id=tenant_id,
        name="Test WH",
        code=f"WH-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    return warehouse


async def _stocked_variant(
    db: AsyncSession, tenant_id: uuid.UUID, warehouse_id: uuid.UUID, qty: int
) -> ProductVariant:
    product = await CatalogService.create_product(
        db, tenant_id, title="Stocked Product", slug=f"s-{uuid.uuid4().hex[:10]}"
    )
    variant = await CatalogService.add_variant(
        db, tenant_id, product.id, price="10.00"
    )
    if qty:
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


async def test_move_in_out_and_adjust(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    wh = await _warehouse(db, tenant_id)
    variant = await _stocked_variant(db, tenant_id, wh.id, qty=10)

    balance = await InventoryService.get_balance(db, tenant_id, variant.id, wh.id)
    assert balance.on_hand == 10
    assert balance.reserved == 0

    await InventoryService.move(
        db, tenant_id, variant.id, wh.id, direction="out", quantity=3, reason="sale"
    )
    assert (
        await InventoryService.get_balance(db, tenant_id, variant.id, wh.id)
    ).on_hand == 7

    moved = await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        wh.id,
        direction="adjust",
        quantity=5,
        reason="adjustment",
    )
    assert moved.balance_after == 5
    assert (
        await InventoryService.get_balance(db, tenant_id, variant.id, wh.id)
    ).on_hand == 5

    movements = await InventoryService.list_movements(db, tenant_id, variant.id)
    assert len(movements) == 3
    assert {m.direction for m in movements} == {"in", "out", "adjust"}
    assert {m.balance_after for m in movements} == {10, 7, 5}
    await db.flush()


async def test_list_movements_without_a_variant_is_the_tenant_ledger(
    db: AsyncSession, tenant_ctx
):
    """The route's `variant_id` is an OPTIONAL filter, so the service must be
    able to say "no filter". It compared `variant_id == NULL` instead, which
    matches no row — the ledger endpoint returned [] on its default call.
    """
    tenant_id = tenant_ctx.tenant_id
    wh = await _warehouse(db, tenant_id)
    first = await _stocked_variant(db, tenant_id, wh.id, qty=10)
    second = await _stocked_variant(db, tenant_id, wh.id, qty=4)

    rows = await InventoryService.list_movements(db, tenant_id, None)
    assert len(rows) == 2
    assert {r.variant_id for r in rows} == {first.id, second.id}

    scoped = await InventoryService.list_movements(db, tenant_id, first.id)
    assert [r.variant_id for r in scoped] == [first.id]


async def test_move_rejects_bad_input(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    wh = await _warehouse(db, tenant_id)
    variant = await _stocked_variant(db, tenant_id, wh.id, qty=1)

    with pytest.raises(ValueError):
        await InventoryService.move(
            db,
            tenant_id,
            variant.id,
            wh.id,
            direction="sideways",
            quantity=1,
            reason="adjustment",
        )
    with pytest.raises(ValueError):
        await InventoryService.move(
            db, tenant_id, variant.id, wh.id, direction="in", quantity=0, reason="purchase"
        )
    with pytest.raises(ValueError):
        await InventoryService.move(
            db, tenant_id, variant.id, wh.id, direction="in", quantity=-2, reason="purchase"
        )
    await db.flush()


async def test_out_below_zero_raises(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    wh = await _warehouse(db, tenant_id)
    variant = await _stocked_variant(db, tenant_id, wh.id, qty=0)

    with pytest.raises(InsufficientStockError):
        await InventoryService.move(
            db, tenant_id, variant.id, wh.id, direction="out", quantity=1, reason="sale"
        )
    # The failure must not corrupt state: balance stays a clean zero row.
    balance = await InventoryService.get_balance(db, tenant_id, variant.id, wh.id)
    assert balance.on_hand == 0
    await db.flush()


async def test_reserve_and_release(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    wh = await _warehouse(db, tenant_id)
    variant = await _stocked_variant(db, tenant_id, wh.id, qty=10)

    reserved = await InventoryService.reserve(db, tenant_id, variant.id, wh.id, 4)
    assert reserved.reserved == 4
    assert reserved.on_hand == 10

    released = await InventoryService.release(db, tenant_id, variant.id, wh.id, 2)
    assert released.reserved == 2

    # Releasing more than reserved clamps at zero.
    clamped = await InventoryService.release(db, tenant_id, variant.id, wh.id, 99)
    assert clamped.reserved == 0
    await db.flush()


async def test_reserve_beyond_availability_raises(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    wh = await _warehouse(db, tenant_id)
    variant = await _stocked_variant(db, tenant_id, wh.id, qty=5)

    with pytest.raises(InsufficientStockError):
        await InventoryService.reserve(db, tenant_id, variant.id, wh.id, 6)

    await InventoryService.reserve(db, tenant_id, variant.id, wh.id, 5)
    with pytest.raises(InsufficientStockError):
        await InventoryService.reserve(db, tenant_id, variant.id, wh.id, 1)
    await db.flush()


async def test_transfer_moves_stock_between_warehouses(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    source = await _warehouse(db, tenant_id)
    destination = await _warehouse(db, tenant_id)
    variant = await _stocked_variant(db, tenant_id, source.id, qty=10)

    transfer = await InventoryService.create_transfer(
        db,
        tenant_id,
        from_warehouse_id=source.id,
        to_warehouse_id=destination.id,
        lines=[{"variant_id": variant.id, "quantity": 4}],
    )

    completed = await InventoryService.complete_transfer(db, tenant_id, transfer.id)
    assert completed.status == "completed"
    assert completed.completed_at is not None

    source_balance = await InventoryService.get_balance(
        db, tenant_id, variant.id, source.id
    )
    destination_balance = await InventoryService.get_balance(
        db, tenant_id, variant.id, destination.id
    )
    assert source_balance.on_hand == 6
    assert destination_balance.on_hand == 4

    movements = await InventoryService.list_movements(db, tenant_id, variant.id)
    reasons = {m.reason for m in movements}
    assert {"purchase", "transfer_out", "transfer_in"} <= reasons

    # Completing twice conflicts.
    with pytest.raises(ConflictError):
        await InventoryService.complete_transfer(db, tenant_id, transfer.id)
    await db.flush()


async def test_wrong_tenant_variant_raises(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    wh = await _warehouse(db, tenant_id)
    variant = await _stocked_variant(db, tenant_id, wh.id, qty=1)

    with pytest.raises(NotFoundError):
        await InventoryService.move(
            db,
            uuid.uuid4(),
            variant.id,
            wh.id,
            direction="in",
            quantity=1,
            reason="purchase",
        )
    await db.flush()
