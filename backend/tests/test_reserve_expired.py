"""A shop that tracks expiry cannot reserve stock that has expired.

The balance is one number per product, so a pharmacy can hold ten units of which four are in an
expired batch. Reserving (the step every sale passes through, on the till and online) must refuse
the expired four, exactly as it already refuses units held in quarantine. A shop that does not
track expiry reserves against the whole balance, as it always has.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import app.applications.apparel.modules.purchasing.models  # noqa: F401 - registers the suppliers table
from app.core.errors import InsufficientStockError
from app.applications.apparel.modules.catalog.models import Product, ProductVariant
from app.applications.apparel.modules.inventory.models import InventoryLot, Warehouse
from app.applications.apparel.modules.inventory.service import InventoryService
from app.applications.apparel.modules.inventory.services.valuation import ValuationService
from app.platform.settings.service import SettingsService

pytestmark = pytest.mark.asyncio


async def _stock(db, tid, *, expired, fresh):
    wh = Warehouse(tenant_id=tid, name="Main", code="WH-R", is_active=True)
    prod = Product(tenant_id=tid, title="Augmentin", slug="augmentin", status="active")
    db.add_all([wh, prod])
    await db.flush()
    var = ProductVariant(
        tenant_id=tid,
        product_id=prod.id,
        sku="AUG-1",
        title="1g",
        price=Decimal("90"),
        is_active=True,
    )
    db.add(var)
    await db.flush()
    now = datetime.now(UTC)
    for qty, days, code in ((expired, -3, "OLD"), (fresh, 60, "NEW")):
        if not qty:
            continue
        lot = InventoryLot(
            tenant_id=tid, variant_id=var.id, lot_code=code, expires_at=now + timedelta(days=days)
        )
        db.add(lot)
        await db.flush()
        await ValuationService.create_cost_layer(
            db,
            tid,
            variant_id=var.id,
            warehouse_id=wh.id,
            quantity=qty,
            unit_cost=Decimal("40"),
            lot_id=lot.id,
        )
    if expired + fresh:
        await InventoryService.move(
            db, tid, var.id, wh.id, direction="in", quantity=expired + fresh, reason="opening_stock"
        )
    return wh, var


async def test_a_pharmacy_cannot_reserve_the_expired_units(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await SettingsService(db, tid).set("business.vertical", "pharmacy")
    wh, var = await _stock(db, tid, expired=4, fresh=6)
    await InventoryService.reserve(db, tid, var.id, wh.id, quantity=6)  # all the fresh ones
    with pytest.raises(InsufficientStockError):
        await InventoryService.reserve(db, tid, var.id, wh.id, quantity=1)  # only expired remain


async def test_a_pharmacy_can_reserve_up_to_the_fresh_units(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await SettingsService(db, tid).set("business.vertical", "pharmacy")
    wh, var = await _stock(db, tid, expired=4, fresh=6)
    bal = await InventoryService.reserve(db, tid, var.id, wh.id, quantity=6)
    assert bal.reserved == 6


async def test_the_refusal_says_how_many_are_expired(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await SettingsService(db, tid).set("business.vertical", "pharmacy")
    wh, var = await _stock(db, tid, expired=4, fresh=1)
    with pytest.raises(InsufficientStockError, match="expired=4"):
        await InventoryService.reserve(db, tid, var.id, wh.id, quantity=2)


async def test_a_shop_without_the_capability_reserves_the_whole_balance(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh, var = await _stock(db, tid, expired=4, fresh=6)
    bal = await InventoryService.reserve(db, tid, var.id, wh.id, quantity=10)
    assert bal.reserved == 10


async def test_stock_with_no_batch_is_always_reservable(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await SettingsService(db, tid).set("business.vertical", "pharmacy")
    wh, var = await _stock(db, tid, expired=0, fresh=0)
    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=5, reason="opening_stock"
    )
    bal = await InventoryService.reserve(db, tid, var.id, wh.id, quantity=5)
    assert bal.reserved == 5
