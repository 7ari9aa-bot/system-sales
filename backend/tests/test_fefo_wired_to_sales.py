"""The fefo_picking switch decides which batch a real sale and a real transfer take.

``consume_fifo`` has always known how to sell soonest-expiring first, but no caller asked, so a
pharmacy that turned ``fefo_picking`` on still sold oldest-received first. These tests go through
the paths a shop really uses (converting a paid order's reservation, shipping a transfer) and read
back which batch lost stock, so they fail if a caller stops following the shop's capability.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.purchasing.models  # noqa: F401 - registers the suppliers table
from app.core.tenancy import reset_current_scope, set_current_scope
from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.identity.models import Workspace
from app.modules.inventory.models import InventoryCostLayer, InventoryLot, Warehouse
from app.modules.inventory.service import InventoryReservationService, InventoryService
from app.modules.inventory.services.expiry import consumption_order
from app.modules.inventory.services.transfers import TransferServiceMixin
from app.modules.inventory.services.valuation import ValuationService
from app.modules.orders.service import OrderService
from app.modules.settings.service import SettingsService

pytestmark = pytest.mark.asyncio

NOW = datetime.now(UTC)


async def _shop_stock(db: AsyncSession, tenant_id: uuid.UUID):
    """A warehouse with 10 units in two batches. The batch received FIRST expires LAST."""
    wh = Warehouse(tenant_id=tenant_id, name="W", code=f"W-{uuid.uuid4().hex[:6].upper()}")
    db.add(wh)
    await db.flush()
    product = await CatalogService.create_product(
        db, tenant_id, title="Drug", slug=f"d-{uuid.uuid4().hex[:10]}"
    )
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(db, tenant_id, product.id, price="10.00")
    await InventoryService.move(
        db, tenant_id, variant.id, wh.id, direction="in", quantity=10, reason="purchase"
    )
    for code, days, received_days_ago in (("LATE-EXPIRY", 300, 10), ("SOON-EXPIRY", 30, 1)):
        lot = InventoryLot(
            tenant_id=tenant_id,
            variant_id=variant.id,
            lot_code=code,
            expires_at=NOW + timedelta(days=days),
        )
        db.add(lot)
        await db.flush()
        await ValuationService.create_cost_layer(
            db,
            tenant_id,
            variant_id=variant.id,
            warehouse_id=wh.id,
            quantity=5,
            unit_cost=Decimal("4"),
            layer_date=NOW - timedelta(days=received_days_ago),
            lot_id=lot.id,
        )
    return wh, variant


async def _left(db: AsyncSession, variant_id: uuid.UUID) -> dict[str, int]:
    """{lot_code: units still in that batch}."""
    rows = (
        await db.execute(
            select(InventoryLot.lot_code, InventoryCostLayer.remaining_quantity)
            .join(InventoryLot, InventoryLot.id == InventoryCostLayer.lot_id)
            .where(InventoryCostLayer.variant_id == variant_id)
        )
    ).all()
    return {code: qty for code, qty in rows}


async def _paid_order(db: AsyncSession, tenant_id, wh, variant, qty: int):
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Buyer"
    )
    order = await OrderService.create_order(
        db,
        tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": qty}],
        warehouse_id=wh.id,
    )
    assert await InventoryReservationService.convert(db, tenant_id, order.id) == 1


async def test_a_shop_that_picks_fefo_sells_the_soonest_expiring_batch_first(
    db: AsyncSession, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    await SettingsService(db, tid).set("capability.fefo_picking", True)
    wh, variant = await _shop_stock(db, tid)

    await _paid_order(db, tid, wh, variant, qty=3)

    assert await _left(db, variant.id) == {"LATE-EXPIRY": 5, "SOON-EXPIRY": 2}


async def test_a_shop_that_has_not_turned_it_on_still_sells_oldest_received_first(
    db: AsyncSession, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    wh, variant = await _shop_stock(db, tid)  # capability never touched

    await _paid_order(db, tid, wh, variant, qty=3)

    assert await _left(db, variant.id) == {"LATE-EXPIRY": 2, "SOON-EXPIRY": 5}


async def test_turning_it_off_again_returns_to_oldest_received_first(
    db: AsyncSession, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    s = SettingsService(db, tid)
    await s.set("capability.fefo_picking", True)
    await s.set("capability.fefo_picking", False)
    wh, variant = await _shop_stock(db, tid)

    await _paid_order(db, tid, wh, variant, qty=3)

    assert await _left(db, variant.id) == {"LATE-EXPIRY": 2, "SOON-EXPIRY": 5}


async def test_fefo_never_sells_a_batch_that_has_expired(db: AsyncSession, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await SettingsService(db, tid).set("capability.fefo_picking", True)
    wh, variant = await _shop_stock(db, tid)
    expired = InventoryLot(
        tenant_id=tid, variant_id=variant.id, lot_code="EXPIRED", expires_at=NOW - timedelta(days=1)
    )
    db.add(expired)
    await db.flush()
    await ValuationService.create_cost_layer(
        db,
        tid,
        variant_id=variant.id,
        warehouse_id=wh.id,
        quantity=5,
        unit_cost=Decimal("4"),
        layer_date=NOW - timedelta(days=40),  # the oldest layer of all
        lot_id=expired.id,
    )

    res = await ValuationService.consume_fifo(
        db, tid, variant_id=variant.id, warehouse_id=wh.id, quantity=3
    )

    assert {c["quantity"] for c in res["consumed_layers"]} == {3}
    assert (await _left(db, variant.id))["EXPIRED"] == 5  # untouched


async def test_a_direct_sale_follows_the_same_rule(db: AsyncSession, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await SettingsService(db, tid).set("capability.fefo_picking", True)
    wh, variant = await _shop_stock(db, tid)

    await ValuationService.record_sale(
        db, tid, variant_id=variant.id, warehouse_id=wh.id, quantity=3
    )

    assert await _left(db, variant.id) == {"LATE-EXPIRY": 5, "SOON-EXPIRY": 2}


async def test_the_order_is_the_shops_answer_not_the_verticals_name(
    db: AsyncSession, tenant_ctx
) -> None:
    """A pharmacy that switches it off sells FIFO; a clothes shop that switches it on sells FEFO."""
    tid = tenant_ctx.tenant_id
    s = SettingsService(db, tid)
    assert await consumption_order(db, tid) == "fifo"
    await s.set("capability.fefo_picking", True)
    assert await consumption_order(db, tid) == "fefo"
    await s.set("capability.fefo_picking", False)
    assert await consumption_order(db, tid) == "fifo"


async def test_an_explicit_order_still_wins_over_the_shops_switch(
    db: AsyncSession, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    await SettingsService(db, tid).set("capability.fefo_picking", True)
    wh, variant = await _shop_stock(db, tid)

    res = await ValuationService.consume_fifo(
        db, tid, variant_id=variant.id, warehouse_id=wh.id, quantity=3, order="fifo"
    )

    assert res["consumed_quantity"] == 3
    assert await _left(db, variant.id) == {"LATE-EXPIRY": 2, "SOON-EXPIRY": 5}


async def _ship_three(db: AsyncSession, tid, wh, variant) -> None:
    """Ship 3 units to a second warehouse; the transfer reads the same layers a sale does."""
    other = Warehouse(tenant_id=tid, name="B", code=f"B-{uuid.uuid4().hex[:6].upper()}")
    db.add(other)
    await db.flush()
    transfer = await TransferServiceMixin.create_transfer(
        db,
        tid,
        from_warehouse_id=wh.id,
        to_warehouse_id=other.id,
        lines=[{"variant_id": str(variant.id), "quantity": 3}],
    )
    await TransferServiceMixin.ship_transfer(db, tid, transfer.id)


async def test_a_transfer_ships_the_soonest_expiring_batch_first_when_fefo_is_on(
    db: AsyncSession, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    await SettingsService(db, tid).set("capability.fefo_picking", True)
    wh, variant = await _shop_stock(db, tid)

    await _ship_three(db, tid, wh, variant)

    assert await _left(db, variant.id) == {"LATE-EXPIRY": 5, "SOON-EXPIRY": 2}


async def test_a_transfer_ships_oldest_received_first_when_fefo_is_off(
    db: AsyncSession, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    wh, variant = await _shop_stock(db, tid)

    await _ship_three(db, tid, wh, variant)

    assert await _left(db, variant.id) == {"LATE-EXPIRY": 2, "SOON-EXPIRY": 5}


async def test_a_sale_follows_the_workspace_it_is_made_in(db: AsyncSession, tenant_ctx) -> None:
    """Two activities under one account: only the workspace that picks FEFO sells that way."""
    tid = tenant_ctx.tenant_id
    pharmacy = Workspace(tenant_id=tid, name="p", slug=f"p-{uuid.uuid4().hex[:6]}")
    clothes = Workspace(tenant_id=tid, name="c", slug=f"c-{uuid.uuid4().hex[:6]}")
    db.add_all([pharmacy, clothes])
    await db.flush()
    await SettingsService(db, tid).set(
        "capability.fefo_picking", True, scope="workspace", scope_id=pharmacy.id
    )

    token = set_current_scope(pharmacy.id, None)
    try:
        wh, variant = await _shop_stock(db, tid)
        await _paid_order(db, tid, wh, variant, qty=3)
        in_pharmacy = await _left(db, variant.id)
    finally:
        reset_current_scope(token)

    token = set_current_scope(clothes.id, None)
    try:
        wh2, variant2 = await _shop_stock(db, tid)
        await _paid_order(db, tid, wh2, variant2, qty=3)
        in_clothes = await _left(db, variant2.id)
    finally:
        reset_current_scope(token)

    assert in_pharmacy == {"LATE-EXPIRY": 5, "SOON-EXPIRY": 2}  # soonest-expiring first
    assert in_clothes == {"LATE-EXPIRY": 2, "SOON-EXPIRY": 5}  # oldest-received first
