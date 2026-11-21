"""Selling the batch that expires soonest, and never one that has expired.

A cost layer may now name the batch (lot) it came from. A shop that tracks expiry sells the layer
whose batch expires first (FEFO); every other shop keeps selling oldest-received first (FIFO), so
turning the capability on is the only thing that changes behaviour. A batch with no expiry date
sells after the dated ones, and an expired batch is never sold.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import app.modules.purchasing.models  # noqa: F401 - registers the suppliers table
from app.core.errors import InsufficientStockError
from app.modules.catalog.models import Product, ProductVariant
from app.modules.inventory.models import InventoryLot, Warehouse
from app.modules.inventory.services.valuation import ValuationService

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


async def _setup(db, tid):
    wh = Warehouse(tenant_id=tid, name="Main", code="WH-F", is_active=True)
    prod = Product(tenant_id=tid, title="Amoxil", slug="amoxil", status="active")
    db.add_all([wh, prod])
    await db.flush()
    var = ProductVariant(
        tenant_id=tid,
        product_id=prod.id,
        sku="AMX-1",
        title="500",
        price=Decimal("30"),
        is_active=True,
    )
    db.add(var)
    await db.flush()
    return wh, var


async def _batch(db, tid, wh, var, code, days, qty, received_days_ago):
    lot = InventoryLot(
        tenant_id=tid,
        variant_id=var.id,
        lot_code=code,
        expires_at=None if days is None else NOW + timedelta(days=days),
    )
    db.add(lot)
    await db.flush()
    layer = await ValuationService.create_cost_layer(
        db,
        tid,
        variant_id=var.id,
        warehouse_id=wh.id,
        quantity=qty,
        unit_cost=Decimal("10"),
        layer_date=NOW - timedelta(days=received_days_ago),
        lot_id=lot.id,
    )
    return lot, layer


async def _taken(db, res):
    """{lot_code: quantity} for what the sale took; None stands for stock with no batch."""
    from sqlalchemy import select

    out: dict[str | None, int] = {}
    for c in res["consumed_layers"]:
        code = None
        if c["lot_id"]:
            code = (
                await db.execute(
                    select(InventoryLot.lot_code).where(InventoryLot.id == c["lot_id"])
                )
            ).scalar_one()
        out[code] = out.get(code, 0) + c["quantity"]
    return out


async def test_fifo_is_still_the_default_so_existing_shops_do_not_change(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await _batch(db, tid, wh, var, "OLDEST-RECEIVED", 200, 5, received_days_ago=10)
    await _batch(db, tid, wh, var, "SOONEST-EXPIRY", 20, 5, received_days_ago=1)
    res = await ValuationService.consume_fifo(
        db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=3
    )
    assert await _taken(db, res) == {"OLDEST-RECEIVED": 3}


async def test_fefo_takes_the_soonest_expiring_batch_first(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await _batch(db, tid, wh, var, "OLDEST-RECEIVED", 200, 5, received_days_ago=10)
    await _batch(db, tid, wh, var, "SOONEST-EXPIRY", 20, 5, received_days_ago=1)
    res = await ValuationService.consume_fifo(
        db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=3, order="fefo", now=NOW
    )
    assert await _taken(db, res) == {"SOONEST-EXPIRY": 3}


async def test_fefo_spills_into_the_next_batch_when_the_first_runs_out(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await _batch(db, tid, wh, var, "A", 10, 2, 5)
    await _batch(db, tid, wh, var, "B", 40, 5, 5)
    res = await ValuationService.consume_fifo(
        db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=4, order="fefo", now=NOW
    )
    assert await _taken(db, res) == {"A": 2, "B": 2}


async def test_an_expired_batch_is_never_sold_even_when_it_is_all_that_is_left(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await _batch(db, tid, wh, var, "EXPIRED", -1, 9, 30)
    await _batch(db, tid, wh, var, "GOOD", 60, 2, 1)
    res = await ValuationService.consume_fifo(
        db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=2, order="fefo", now=NOW
    )
    assert await _taken(db, res) == {"GOOD": 2}
    with pytest.raises(InsufficientStockError):
        await ValuationService.consume_fifo(
            db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=1, order="fefo", now=NOW
        )


async def test_a_batch_expiring_this_instant_is_expired(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await _batch(db, tid, wh, var, "NOW", 0, 5, 3)
    with pytest.raises(InsufficientStockError):
        await ValuationService.consume_fifo(
            db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=1, order="fefo", now=NOW
        )


async def test_a_batch_with_no_expiry_date_sells_after_the_dated_ones(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await _batch(db, tid, wh, var, "UNDATED", None, 5, received_days_ago=20)
    await _batch(db, tid, wh, var, "DATED", 90, 5, received_days_ago=1)
    res = await ValuationService.consume_fifo(
        db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=6, order="fefo", now=NOW
    )
    assert await _taken(db, res) == {"DATED": 5, "UNDATED": 1}


async def test_layers_with_no_batch_still_sell_under_fefo_after_the_dated_ones(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await ValuationService.create_cost_layer(
        db,
        tid,
        variant_id=var.id,
        warehouse_id=wh.id,
        quantity=4,
        unit_cost=Decimal("10"),
        layer_date=NOW - timedelta(days=50),
    )
    await _batch(db, tid, wh, var, "DATED", 30, 2, 1)
    res = await ValuationService.consume_fifo(
        db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=4, order="fefo", now=NOW
    )
    assert await _taken(db, res) == {"DATED": 2, None: 2}


async def test_equal_expiry_falls_back_to_oldest_received(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await _batch(db, tid, wh, var, "NEWER", 30, 5, received_days_ago=1)
    await _batch(db, tid, wh, var, "OLDER", 30, 5, received_days_ago=9)
    res = await ValuationService.consume_fifo(
        db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=2, order="fefo", now=NOW
    )
    assert await _taken(db, res) == {"OLDER": 2}


async def test_an_unknown_order_is_refused_not_guessed(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await _batch(db, tid, wh, var, "A", 30, 5, 1)
    with pytest.raises(ValueError):
        await ValuationService.consume_fifo(
            db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=1, order="lifo"
        )
