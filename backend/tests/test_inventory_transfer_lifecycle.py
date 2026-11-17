"""Tests for Transfer Lifecycle (D6, §4 Phase 2 — Transfers).

Exit criterion:
  A transfer shipped but not received shows as `in_transit` stock,
  and the destination's `on_hand` does not include it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID, name: str = "WH") -> Warehouse:
    wh = Warehouse(
        tenant_id=tenant_id,
        name=name,
        code=f"WH-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(wh)
    await db.flush()
    return wh


# ═══════════════════════════════════════════════════════════════════════════
# 2.1 Core Transfer Lifecycle & Exit Criterion
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_transfer_lifecycle_and_in_transit_stock(db: AsyncSession, tenant_ctx):
    """Phase 2 exit criterion:
    Goods shipped leave source warehouse, do NOT appear in destination on_hand,
    and show up in in_transit_quantity until received."""
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id

    source_wh = await _warehouse(db, tid, "Cairo Central")
    dest_wh = await _warehouse(db, tid, "Alexandria Branch")

    prod = await CatalogService.create_product(
        db, tid, title="Transfer Widget", slug=f"tw-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="100.00")

    # Stock 50 units at source warehouse
    await InventoryService.move(
        db,
        tid,
        var.id,
        source_wh.id,
        direction="in",
        quantity=50,
        reason="purchase",
    )
    bal_source = await InventoryService.get_balance(db, tid, var.id, source_wh.id)
    assert bal_source.on_hand == 50

    bal_dest = await InventoryService.get_balance(db, tid, var.id, dest_wh.id)
    assert bal_dest.on_hand == 0

    # 1. Create draft transfer for 20 units
    transfer = await InventoryService.create_transfer(
        db,
        tid,
        from_warehouse_id=source_wh.id,
        to_warehouse_id=dest_wh.id,
        lines=[{"variant_id": str(var.id), "quantity": 20}],
        notes="Urgent replenishment for branch",
    )
    assert transfer.status == "draft"

    # Relational lines exist
    t_lines = await InventoryService.get_transfer_lines(db, tid, transfer.id)
    assert len(t_lines) == 1
    assert t_lines[0].quantity == 20
    assert t_lines[0].quantity_shipped == 0
    assert t_lines[0].quantity_received == 0

    # 2. Approve transfer
    await InventoryService.approve_transfer(db, tid, transfer.id, user_id=uid)
    await db.refresh(transfer)
    assert transfer.status == "approved"
    assert transfer.approved_at is not None

    # 3. Ship transfer (despatch 20 units)
    shipment = await InventoryService.ship_transfer(
        db,
        tid,
        transfer.id,
        carrier="FastCourier",
        tracking_ref="TRK-987654",
        user_id=uid,
    )
    assert shipment is not None
    await db.refresh(transfer)
    assert transfer.status == "in_transit"

    # ─── CRITICAL EXIT CRITERION ASSERTIONS ───
    # Source warehouse: stock went down from 50 to 30
    bal_source = await InventoryService.get_balance(db, tid, var.id, source_wh.id)
    assert bal_source.on_hand == 30, f"Expected source on_hand=30, got {bal_source.on_hand}"

    # Destination warehouse: stock is STILL 0 (goods are in transit!)
    bal_dest = await InventoryService.get_balance(db, tid, var.id, dest_wh.id)
    assert bal_dest.on_hand == 0, f"Destination on_hand must still be 0, got {bal_dest.on_hand}"

    # In-transit calculation: 20 units
    in_transit = await InventoryService.in_transit_quantity(db, tid, var.id)
    assert in_transit == 20, f"Expected 20 in-transit, got {in_transit}"

    # 4. Partial receipt: Alexandria receives 12 units first
    receipt1 = await InventoryService.receive_transfer(
        db,
        tid,
        transfer.id,
        lines=[{"variant_id": str(var.id), "quantity": 12, "condition": "good"}],
        user_id=uid,
    )
    assert receipt1 is not None
    await db.refresh(transfer)
    assert transfer.status == "partially_received"

    # Destination now has 12 on hand
    bal_dest = await InventoryService.get_balance(db, tid, var.id, dest_wh.id)
    assert bal_dest.on_hand == 12

    # In-transit drops to 8
    in_transit = await InventoryService.in_transit_quantity(db, tid, var.id)
    assert in_transit == 8

    # 5. Second receipt: remaining 8 units arrive
    receipt2 = await InventoryService.receive_transfer(
        db,
        tid,
        transfer.id,
        lines=[{"variant_id": str(var.id), "quantity": 8, "condition": "good"}],
        user_id=uid,
    )
    assert receipt2 is not None
    await db.refresh(transfer)
    assert transfer.status == "completed"
    assert transfer.completed_at is not None

    # Destination now has full 20 on hand
    bal_dest = await InventoryService.get_balance(db, tid, var.id, dest_wh.id)
    assert bal_dest.on_hand == 20

    # In-transit is now 0
    in_transit = await InventoryService.in_transit_quantity(db, tid, var.id)
    assert in_transit == 0


# ═══════════════════════════════════════════════════════════════════════════
# 2.2 Transfer Exception (Damaged/Shortage)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_transfer_exception_handling(db: AsyncSession, tenant_ctx):
    """When goods arrive damaged or short, transfer finishes in 'exception' status."""
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id

    source_wh = await _warehouse(db, tid, "Cairo Source")
    dest_wh = await _warehouse(db, tid, "Giza Dest")

    prod = await CatalogService.create_product(
        db, tid, title="Glass Vases", slug=f"gv-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="75.00")

    await InventoryService.move(
        db, tid, var.id, source_wh.id, direction="in", quantity=10, reason="purchase"
    )

    transfer = await InventoryService.create_transfer(
        db,
        tid,
        from_warehouse_id=source_wh.id,
        to_warehouse_id=dest_wh.id,
        lines=[{"variant_id": str(var.id), "quantity": 10}],
    )
    await InventoryService.ship_transfer(db, tid, transfer.id, user_id=uid)

    # 7 units good, 3 damaged
    await InventoryService.receive_transfer(
        db,
        tid,
        transfer.id,
        lines=[
            {"variant_id": str(var.id), "quantity": 7, "condition": "good"},
            {"variant_id": str(var.id), "quantity": 3, "condition": "damaged"},
        ],
        user_id=uid,
    )

    await db.refresh(transfer)
    assert transfer.status == "exception"
    assert "damaged" in (transfer.exception_reason or "").lower()

    # Destination gets only the 7 good items
    bal_dest = await InventoryService.get_balance(db, tid, var.id, dest_wh.id)
    assert bal_dest.on_hand == 7


# ═══════════════════════════════════════════════════════════════════════════
# 2.3 Cancel Transfer Rules
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cancel_transfer_rules(db: AsyncSession, tenant_ctx):
    """Can cancel before shipping, but NOT after goods are in transit."""
    tid = tenant_ctx.tenant_id

    source_wh = await _warehouse(db, tid, "Source W")
    dest_wh = await _warehouse(db, tid, "Dest W")

    prod = await CatalogService.create_product(
        db, tid, title="Item C", slug=f"ic-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="15.00")

    await InventoryService.move(
        db, tid, var.id, source_wh.id, direction="in", quantity=10, reason="purchase"
    )

    # 1. Cancel draft transfer: allowed
    t1 = await InventoryService.create_transfer(
        db,
        tid,
        from_warehouse_id=source_wh.id,
        to_warehouse_id=dest_wh.id,
        lines=[{"variant_id": str(var.id), "quantity": 5}],
    )
    cancelled = await InventoryService.cancel_transfer(db, tid, t1.id, reason="Customer cancelled")
    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at is not None

    # 2. Cancel in-transit transfer: REFUSED
    t2 = await InventoryService.create_transfer(
        db,
        tid,
        from_warehouse_id=source_wh.id,
        to_warehouse_id=dest_wh.id,
        lines=[{"variant_id": str(var.id), "quantity": 3}],
    )
    await InventoryService.ship_transfer(db, tid, t2.id)

    with pytest.raises(ConflictError, match="cannot be cancelled"):
        await InventoryService.cancel_transfer(db, tid, t2.id)
