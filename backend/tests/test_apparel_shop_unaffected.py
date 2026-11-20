"""An apparel shop, and a shop that never chose a vertical, behave exactly as they always did.

Pharmacy and restaurant abilities are inert until a shop is that vertical or its owner switches
them on. These tests pin that down on the real stock path, so a later change for another
vertical cannot quietly reach a clothing shop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import app.modules.purchasing.models  # noqa: F401 - registers the suppliers table
from app.modules.catalog.models import Product, ProductVariant
from app.modules.inventory.models import InventoryLot, Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.inventory.services.valuation import ValuationService
from app.modules.settings.capabilities import CAPABILITIES, DEFAULT_VERTICAL, VERTICALS
from app.modules.settings.service import SettingsService

pytestmark = pytest.mark.asyncio

NOT_CLOTHING = {"pharmacy", "restaurant"}


def test_no_other_verticals_ability_is_on_for_apparel_or_general() -> None:
    """The only abilities a clothing shop starts with are the clothing ones."""
    for cap in CAPABILITIES.values():
        for vertical in ("apparel", DEFAULT_VERTICAL):
            if vertical in cap.on_for:
                assert vertical == "apparel" and cap.name == "variant_matrix", (
                    f"{cap.name} is on for {vertical}"
                )


def test_apparel_is_a_known_vertical_and_general_is_the_default() -> None:
    assert "apparel" in VERTICALS
    assert DEFAULT_VERTICAL == "general"


async def _stock_with_a_dated_batch(db, tid, *, days):
    wh = Warehouse(tenant_id=tid, name="Main", code="WH-A", is_active=True)
    prod = Product(tenant_id=tid, title="Shirt", slug="shirt", status="active")
    db.add_all([wh, prod])
    await db.flush()
    var = ProductVariant(
        tenant_id=tid,
        product_id=prod.id,
        sku="SH-M",
        title="M",
        price=Decimal("300"),
        is_active=True,
    )
    db.add(var)
    await db.flush()
    lot = InventoryLot(
        tenant_id=tid,
        variant_id=var.id,
        lot_code="SPRING",
        expires_at=datetime.now(UTC) + timedelta(days=days),
    )
    db.add(lot)
    await db.flush()
    await ValuationService.create_cost_layer(
        db,
        tid,
        variant_id=var.id,
        warehouse_id=wh.id,
        quantity=10,
        unit_cost=Decimal("100"),
        lot_id=lot.id,
    )
    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=10, reason="opening_stock"
    )
    return wh, var


@pytest.mark.parametrize("vertical", [None, "general", "apparel"])
async def test_a_clothing_shop_can_reserve_all_its_stock_even_if_a_batch_is_dated_in_the_past(
    db, tenant_ctx, vertical
) -> None:
    """A date on a batch must never stop a clothing shop selling: it does not track expiry."""
    tid = tenant_ctx.tenant_id
    if vertical:
        await SettingsService(db, tid).set("business.vertical", vertical)
    wh, var = await _stock_with_a_dated_batch(db, tid, days=-30)
    bal = await InventoryService.reserve(db, tid, var.id, wh.id, quantity=10)
    assert bal.reserved == 10


@pytest.mark.parametrize("vertical", [None, "general", "apparel"])
async def test_a_clothing_shop_still_sells_oldest_received_first(db, tenant_ctx, vertical) -> None:
    tid = tenant_ctx.tenant_id
    if vertical:
        await SettingsService(db, tid).set("business.vertical", vertical)
    wh, var = await _stock_with_a_dated_batch(db, tid, days=-30)
    res = await ValuationService.consume_fifo(
        db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=4
    )
    assert res["consumed_quantity"] == 4
    assert res["total_cogs"] == Decimal("400.0000")
