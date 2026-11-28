"""Tests for Warehouse Locations and Relocation (D4, §4 Phase 3 — Warehousing).

Exit criterion:
  Quarantined stock is excluded from availability, excluded from the sale path,
  and visible as its own figure.
  Location balances track physical bins/shelves without altering warehouse on_hand.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.apparel.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError
from app.applications.apparel.modules.inventory.models import Warehouse
from app.applications.apparel.modules.inventory.service import (
    InventoryService,
    WarehouseLocationService,
)
from app.platform.settings.service import SettingsService


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    wh = Warehouse(
        tenant_id=tenant_id,
        name="Main Fulfillment Hub",
        code=f"MFH-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(wh)
    await db.flush()
    # Location tracking is a setting now: create_location refuses to run until the
    # tenant has turned it on, so the fixture turns it on like an owner would.
    await SettingsService(db, tenant_id).set("inventory.track_locations", True, scope="tenant")
    await db.flush()
    return wh


# ═══════════════════════════════════════════════════════════════════════════
# 3.1 Location Hierarchy and Functional Kinds
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_location_hierarchy_and_functional_kinds(db: AsyncSession, tenant_ctx):
    """Create a hierarchy: Zone -> Rack -> Shelf -> Bin, plus functional areas."""
    tid = tenant_ctx.tenant_id
    wh = await _warehouse(db, tid)

    # 1. Zone
    zone_a = await WarehouseLocationService.create_location(
        db, tid, warehouse_id=wh.id, code="ZONE-A", name="Apparel Zone", kind="zone"
    )
    assert zone_a.code == "ZONE-A"
    assert zone_a.parent_id is None

    # 2. Rack under Zone
    rack_01 = await WarehouseLocationService.create_location(
        db,
        tid,
        warehouse_id=wh.id,
        code="RACK-01",
        name="Rack 1",
        kind="rack",
        parent_id=zone_a.id,
    )
    assert rack_01.parent_id == zone_a.id

    # 3. Shelf under Rack
    shelf_01 = await WarehouseLocationService.create_location(
        db,
        tid,
        warehouse_id=wh.id,
        code="SHELF-01",
        name="Shelf 1",
        kind="shelf",
        parent_id=rack_01.id,
    )

    # 4. Bin under Shelf with capacity
    bin_a1 = await WarehouseLocationService.create_location(
        db,
        tid,
        warehouse_id=wh.id,
        code="BIN-A01-01",
        name="Bin A-01-01",
        kind="bin",
        parent_id=shelf_01.id,
        capacity=50,
    )
    assert bin_a1.capacity == 50

    # 5. Functional areas
    qc_area = await WarehouseLocationService.create_location(
        db, tid, warehouse_id=wh.id, code="AREA-QC", name="Quality Control", kind="qc"
    )
    assert qc_area.kind == "qc"

    # Duplicate code in same warehouse rejected
    with pytest.raises(ConflictError, match="already exists"):
        await WarehouseLocationService.create_location(
            db, tid, warehouse_id=wh.id, code="ZONE-A", name="Duplicate Zone", kind="zone"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3.2 Putaway and Relocation (D4)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_putaway_and_relocation_maintains_warehouse_on_hand(db: AsyncSession, tenant_ctx):
    """Stock putaway and relocation updates location balances and writes
    location movements, but NEVER changes warehouse on_hand."""
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id
    wh = await _warehouse(db, tid)

    prod = await CatalogService.create_product(
        db, tid, title="Bin Widget", slug=f"bw-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="20.00")

    # 100 units enter the warehouse
    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=100, reason="purchase"
    )
    wh_bal = await InventoryService.get_balance(db, tid, var.id, wh.id)
    assert wh_bal.on_hand == 100

    # Create two bins
    bin1 = await WarehouseLocationService.create_location(
        db, tid, warehouse_id=wh.id, code="BIN-01", name="Bin 1", kind="bin"
    )
    bin2 = await WarehouseLocationService.create_location(
        db, tid, warehouse_id=wh.id, code="BIN-02", name="Bin 2", kind="bin"
    )

    # 1. Putaway 60 units into Bin 1
    m1 = await WarehouseLocationService.putaway(
        db,
        tid,
        warehouse_id=wh.id,
        variant_id=var.id,
        to_location_id=bin1.id,
        quantity=60,
        user_id=uid,
    )
    assert m1.reason == "putaway"
    assert m1.quantity == 60

    # Bin 1 has 60
    b1_bal = await WarehouseLocationService.get_location_balance(
        db, tid, warehouse_id=wh.id, location_id=bin1.id, variant_id=var.id
    )
    assert b1_bal.on_hand == 60

    # Warehouse on_hand is STILL 100 (unchanged!)
    wh_bal = await InventoryService.get_balance(db, tid, var.id, wh.id)
    assert wh_bal.on_hand == 100

    # 2. Relocate 25 units from Bin 1 to Bin 2
    m2 = await WarehouseLocationService.relocate(
        db,
        tid,
        warehouse_id=wh.id,
        variant_id=var.id,
        from_location_id=bin1.id,
        to_location_id=bin2.id,
        quantity=25,
        reason="relocation",
        user_id=uid,
    )
    assert m2.quantity == 25

    # Check location balances
    b1_bal = await WarehouseLocationService.get_location_balance(
        db, tid, warehouse_id=wh.id, location_id=bin1.id, variant_id=var.id
    )
    b2_bal = await WarehouseLocationService.get_location_balance(
        db, tid, warehouse_id=wh.id, location_id=bin2.id, variant_id=var.id
    )
    assert b1_bal.on_hand == 35  # 60 - 25 = 35
    assert b2_bal.on_hand == 25  # 0 + 25 = 25

    # Warehouse on_hand is STILL 100
    wh_bal = await InventoryService.get_balance(db, tid, var.id, wh.id)
    assert wh_bal.on_hand == 100

    # 3. Query variant locations
    locs = await WarehouseLocationService.list_variant_locations(
        db, tid, warehouse_id=wh.id, variant_id=var.id
    )
    assert len(locs) == 2
    loc_dict = {loc["code"]: loc["on_hand"] for loc in locs}
    assert loc_dict == {"BIN-01": 35, "BIN-02": 25}


# ═══════════════════════════════════════════════════════════════════════════
# 3.3 Limits and Invariant Enforcement
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_relocation_limits_and_capacity_enforcement(db: AsyncSession, tenant_ctx):
    """Enforce location capacity, source balance sufficiency, and total on_hand invariant."""
    tid = tenant_ctx.tenant_id
    wh = await _warehouse(db, tid)

    prod = await CatalogService.create_product(
        db, tid, title="Heavy Box", slug=f"hb-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="50.00")

    # 20 units in warehouse
    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=20, reason="purchase"
    )

    # Bin with capacity = 15
    bin_capped = await WarehouseLocationService.create_location(
        db,
        tid,
        warehouse_id=wh.id,
        code="BIN-CAP",
        name="Small Bin",
        kind="bin",
        capacity=15,
    )

    # Putaway 10 units: succeeds (10 <= 15)
    await WarehouseLocationService.putaway(
        db,
        tid,
        warehouse_id=wh.id,
        variant_id=var.id,
        to_location_id=bin_capped.id,
        quantity=10,
    )

    # Putaway 10 more units: fails because 10 + 10 = 20 > capacity (15)
    with pytest.raises(ConflictError, match="capacity exceeded"):
        await WarehouseLocationService.putaway(
            db,
            tid,
            warehouse_id=wh.id,
            variant_id=var.id,
            to_location_id=bin_capped.id,
            quantity=10,
        )

    # Relocating more than source location on_hand fails
    bin_empty = await WarehouseLocationService.create_location(
        db, tid, warehouse_id=wh.id, code="BIN-EMPTY", name="Empty Bin", kind="bin"
    )
    with pytest.raises(ConflictError, match="insufficient stock at source"):
        await WarehouseLocationService.relocate(
            db,
            tid,
            warehouse_id=wh.id,
            variant_id=var.id,
            from_location_id=bin_capped.id,
            to_location_id=bin_empty.id,
            quantity=50,  # only 10 in bin_capped
        )
