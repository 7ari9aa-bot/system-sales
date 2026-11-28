"""How many units can really be sold: stock minus what has expired.

The balance is one number per product. A pharmacy may hold ten units of which four sit in a batch
that has expired; the till must not offer those four, even though ten are physically on the shelf.
Only a shop that tracks expiry subtracts them: for every other shop the answer is the balance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import app.applications.apparel.modules.purchasing.models  # noqa: F401 - registers the suppliers table
from app.applications.apparel.modules.catalog.models import Product, ProductVariant
from app.applications.apparel.modules.inventory.models import InventoryLot, Warehouse
from app.applications.apparel.modules.inventory.services.expiry import expired_quantity, sellable_quantity
from app.applications.apparel.modules.inventory.services.valuation import ValuationService
from app.modules.settings.service import SettingsService

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


async def _setup(db, tid):
    wh = Warehouse(tenant_id=tid, name="Main", code="WH-S", is_active=True)
    prod = Product(tenant_id=tid, title="Brufen", slug="brufen", status="active")
    db.add_all([wh, prod])
    await db.flush()
    var = ProductVariant(
        tenant_id=tid,
        product_id=prod.id,
        sku="BRU-1",
        title="400",
        price=Decimal("25"),
        is_active=True,
    )
    db.add(var)
    await db.flush()
    return wh, var


async def _layer(db, tid, wh, var, qty, days=None, consumed=0):
    lot_id = None
    if days is not None:
        lot = InventoryLot(
            tenant_id=tid,
            variant_id=var.id,
            lot_code=f"L{days}-{qty}",
            expires_at=NOW + timedelta(days=days),
        )
        db.add(lot)
        await db.flush()
        lot_id = lot.id
    layer = await ValuationService.create_cost_layer(
        db,
        tid,
        variant_id=var.id,
        warehouse_id=wh.id,
        quantity=qty,
        unit_cost=Decimal("5"),
        lot_id=lot_id,
    )
    layer.remaining_quantity = qty - consumed
    await db.flush()
    return layer


async def test_expired_units_are_the_remaining_quantity_of_expired_batches(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await _layer(db, tid, wh, var, 4, days=-2)
    await _layer(db, tid, wh, var, 6, days=30)
    assert await expired_quantity(db, tid, var.id, wh.id, now=NOW) == 4


async def test_units_already_sold_out_of_an_expired_batch_are_not_counted(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await _layer(db, tid, wh, var, 10, days=-1, consumed=7)
    assert await expired_quantity(db, tid, var.id, wh.id, now=NOW) == 3


async def test_a_batch_expiring_this_instant_counts_as_expired(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await _layer(db, tid, wh, var, 5, days=0)
    assert await expired_quantity(db, tid, var.id, wh.id, now=NOW) == 5


async def test_stock_with_no_batch_never_counts_as_expired(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await _layer(db, tid, wh, var, 8)
    assert await expired_quantity(db, tid, var.id, wh.id, now=NOW) == 0


async def test_a_shop_that_tracks_expiry_sells_the_balance_minus_the_expired(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    await SettingsService(db, tid).set("business.vertical", "pharmacy")
    wh, var = await _setup(db, tid)
    await _layer(db, tid, wh, var, 4, days=-2)
    await _layer(db, tid, wh, var, 6, days=30)
    assert await sellable_quantity(db, tid, var.id, wh.id, on_hand=10, now=NOW) == 6


async def test_a_shop_that_does_not_track_expiry_sells_the_whole_balance(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    await _layer(db, tid, wh, var, 4, days=-2)
    await _layer(db, tid, wh, var, 6, days=30)
    assert await sellable_quantity(db, tid, var.id, wh.id, on_hand=10, now=NOW) == 10


async def test_the_sellable_quantity_is_never_negative(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await SettingsService(db, tid).set("business.vertical", "pharmacy")
    wh, var = await _setup(db, tid)
    await _layer(db, tid, wh, var, 9, days=-3)
    assert await sellable_quantity(db, tid, var.id, wh.id, on_hand=5, now=NOW) == 0


async def test_the_owner_can_turn_expiry_off_on_a_pharmacy(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    s = SettingsService(db, tid)
    await s.set("business.vertical", "pharmacy")
    await s.set("capability.lot_expiry", False)
    wh, var = await _setup(db, tid)
    await _layer(db, tid, wh, var, 4, days=-2)
    assert await sellable_quantity(db, tid, var.id, wh.id, on_hand=10, now=NOW) == 10


async def test_expired_stock_in_one_warehouse_does_not_reduce_another_warehouses_stock(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    other = Warehouse(tenant_id=tid, name="Branch", code="WH-B", is_active=True)
    db.add(other)
    await db.flush()
    await _layer(db, tid, wh, var, 4, days=-2)
    assert await expired_quantity(db, tid, var.id, wh.id, now=NOW) == 4
    assert await expired_quantity(db, tid, var.id, other.id, now=NOW) == 0


async def test_one_products_expired_stock_does_not_reduce_another_products_stock(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _setup(db, tid)
    prod2 = Product(tenant_id=tid, title="Other", slug="other-p", status="active")
    db.add(prod2)
    await db.flush()
    var2 = ProductVariant(
        tenant_id=tid,
        product_id=prod2.id,
        sku="OTH-1",
        title="x",
        price=Decimal("5"),
        is_active=True,
    )
    db.add(var2)
    await db.flush()
    await _layer(db, tid, wh, var, 4, days=-2)
    assert await expired_quantity(db, tid, var.id, wh.id, now=NOW) == 4
    assert await expired_quantity(db, tid, var2.id, wh.id, now=NOW) == 0
