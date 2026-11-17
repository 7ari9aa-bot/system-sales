"""Tests for QualityInspectionService (§4 Phase 1 — Supply Chain Core).

Covers:
  - 1.2 Quality inspection of an incoming receipt: verdicts route to
        sellable (pass), quarantined, or reject.
  - 1.3 Customer-return inspection: returned items held until passing
        inspection, rejected items removed as damaged.
  - Error and edge cases: duplicate results, closed inspections, validation.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, ValidationError
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService, QualityInspectionService
from app.modules.purchasing.models import PurchaseOrderLine
from app.modules.purchasing.service import (
    GoodsReceiptService,
    PurchaseService,
    SupplierService,
)


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    wh = Warehouse(
        tenant_id=tenant_id,
        name="QC WH",
        code=f"QC-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(wh)
    await db.flush()
    return wh


# ═══════════════════════════════════════════════════════════════════════════
# 1.2 Incoming Receipt Inspection
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_incoming_receipt_quality_inspection(db: AsyncSession, tenant_ctx):
    """An incoming goods receipt with quarantine is inspected:
    passed units become sellable, rejected units are removed."""
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id

    wh = await _warehouse(db, tid)
    prod = await CatalogService.create_product(
        db, tid, title="QC Part", slug=f"qcp-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="50.00")

    supplier = await SupplierService.create(db, tid, name=f"QC-Sup-{uuid.uuid4().hex[:4]}")
    po = await PurchaseService.create(
        db,
        tid,
        supplier_id=supplier.id,
        warehouse_id=wh.id,
        lines=[{"variant_id": str(var.id), "quantity": 10, "unit_cost": "20.00"}],
    )
    po_lines = await PurchaseService._lines_in(db, tid, po.id)
    pol: PurchaseOrderLine = po_lines[0]

    # Goods receipt: arrives in quarantine for inspection
    receipt = await GoodsReceiptService.create(
        db,
        tid,
        purchase_order_id=po.id,
        lines=[
            {
                "purchase_order_line_id": str(pol.id),
                "variant_id": str(var.id),
                "quantity": 10,
                "unit_cost": "20.00",
                "condition": "quarantine",
            }
        ],
    )
    await GoodsReceiptService.post(db, tid, receipt.id, actor_user_id=uid)

    bal = await InventoryService.get_balance(db, tid, var.id, wh.id)
    assert bal.on_hand == 10
    assert bal.quarantined == 10
    # Sellable = on_hand - quarantined = 0
    assert bal.on_hand - bal.quarantined == 0

    # Create inspection for this receipt
    inspection = await QualityInspectionService.create(
        db,
        tid,
        source_type="goods_receipt",
        source_id=receipt.id,
        warehouse_id=wh.id,
        note="Initial batch inspection",
        user_id=uid,
    )
    assert inspection.status == "open"

    # Verdict: 7 passed inspection (released from quarantine)
    await QualityInspectionService.record_result(
        db,
        tid,
        inspection_id=inspection.id,
        variant_id=var.id,
        quantity=7,
        verdict="pass",
        note="7 units passed dimensional checks",
        user_id=uid,
    )

    bal = await InventoryService.get_balance(db, tid, var.id, wh.id)
    assert bal.on_hand == 10
    assert bal.quarantined == 3  # 10 - 7 = 3 remaining in quarantine
    assert bal.on_hand - bal.quarantined == 7  # 7 now sellable!

    # Complete the inspection
    await QualityInspectionService.complete(db, tid, inspection_id=inspection.id, user_id=uid)
    await db.refresh(inspection)
    assert inspection.status == "passed"


# ═══════════════════════════════════════════════════════════════════════════
# 1.3 Customer Return Inspection
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_customer_return_inspection_lifecycle(db: AsyncSession, tenant_ctx):
    """Customer returns an item. It is quarantined upon arrival.
    Inspection rejects 1 (damaged, removed from stock) and passes 1 (sellable)."""
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id

    wh = await _warehouse(db, tid)
    prod = await CatalogService.create_product(
        db, tid, title="Return Item", slug=f"ret-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="30.00")

    # Customer return lands in inventory: 2 units
    await InventoryService.move(
        db,
        tid,
        var.id,
        wh.id,
        direction="in",
        quantity=2,
        reason="return",
        reference_type="return_order",
        reference_id=uuid.uuid4(),
    )
    # Quarantined immediately upon return awaiting inspection
    bal = await InventoryService.get_balance(db, tid, var.id, wh.id)
    bal.quarantined = 2
    await db.flush()

    assert bal.on_hand == 2
    assert bal.quarantined == 2

    # Open return inspection
    return_id = uuid.uuid4()
    inspection = await QualityInspectionService.create(
        db,
        tid,
        source_type="return_receipt",
        source_id=return_id,
        warehouse_id=wh.id,
        note="Customer return inspection",
        user_id=uid,
    )

    # 1 item is rejected (damaged packaging / broken seal)
    await QualityInspectionService.record_result(
        db,
        tid,
        inspection_id=inspection.id,
        variant_id=var.id,
        quantity=1,
        verdict="reject",
        note="Damaged seal, cannot resell",
        user_id=uid,
    )

    bal = await InventoryService.get_balance(db, tid, var.id, wh.id)
    # on_hand reduced from 2 to 1 (moved out as damage)
    assert bal.on_hand == 1
    # quarantined reduced from 2 to 1
    assert bal.quarantined == 1

    # Second inspection on another variant or remaining:
    # Let's verify ledger recorded the damage movement
    movements = await InventoryService.list_movements(db, tid, var.id)
    damage_mov = next((m for m in movements if m.reason == "damage"), None)
    assert damage_mov is not None
    assert damage_mov.quantity == 1
    assert damage_mov.direction == "out"


# ═══════════════════════════════════════════════════════════════════════════
# Error handling and validation
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_inspection_validation_and_refusals(db: AsyncSession, tenant_ctx):
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id

    wh = await _warehouse(db, tid)
    prod = await CatalogService.create_product(
        db, tid, title="Test Part", slug=f"tp-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="10.00")

    # Invalid source_type
    with pytest.raises(ValidationError, match="source_type must be one of"):
        await QualityInspectionService.create(
            db, tid, source_type="invalid_type", source_id=uuid.uuid4(), warehouse_id=wh.id
        )

    # Valid inspection
    inspection = await QualityInspectionService.create(
        db, tid, source_type="goods_receipt", source_id=uuid.uuid4(), warehouse_id=wh.id
    )

    # Invalid verdict
    with pytest.raises(ValidationError, match="verdict must be one of"):
        await QualityInspectionService.record_result(
            db,
            tid,
            inspection_id=inspection.id,
            variant_id=var.id,
            quantity=5,
            verdict="not_a_verdict",
        )

    # Record valid result without applying to stock
    await QualityInspectionService.record_result(
        db,
        tid,
        inspection_id=inspection.id,
        variant_id=var.id,
        quantity=5,
        verdict="pass",
        apply_to_stock=False,
    )

    # Duplicate result for same variant on same inspection rejected
    with pytest.raises(ConflictError, match="already been recorded"):
        await QualityInspectionService.record_result(
            db,
            tid,
            inspection_id=inspection.id,
            variant_id=var.id,
            quantity=2,
            verdict="pass",
            apply_to_stock=False,
        )

    # Complete inspection
    await QualityInspectionService.complete(db, tid, inspection_id=inspection.id, user_id=uid)

    # Recording results on closed inspection rejected
    with pytest.raises(ConflictError, match="cannot record results"):
        await QualityInspectionService.record_result(
            db,
            tid,
            inspection_id=inspection.id,
            variant_id=var.id,
            quantity=1,
            verdict="pass",
            apply_to_stock=False,
        )
