"""Tests for Replenishment Engine and Reorder Suggestions (D9, §4 Phase 4).

Exit criterion:
  A variant whose projected stock drops below the reorder point produces a suggestion
  for the exact reorder quantity, and approving it produces a valid draft purchase order.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.apparel.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError
from app.applications.apparel.modules.inventory.models import Warehouse
from app.applications.apparel.modules.inventory.service import (
    InventoryService,
    ReplenishmentService,
)
from app.applications.apparel.modules.purchasing.models import PurchaseOrder, PurchaseOrderLine
from app.applications.apparel.modules.purchasing.service import PurchaseService, SupplierService
from app.modules.settings.registry import Scope
from app.modules.settings.service import SettingsService


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    wh = Warehouse(
        tenant_id=tenant_id,
        name="Replenish WH",
        code=f"REP-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(wh)
    await db.flush()
    return wh


# ═══════════════════════════════════════════════════════════════════════════
# 4.1 Phase 4 Exit Criterion Test
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_reorder_suggestion_arithmetic_and_approval_creates_po(db: AsyncSession, tenant_ctx):
    """Phase 4 exit criterion:
    Projected stock drops below min_stock -> suggestion for exact reorder quantity
    considering max_stock, MOQ, and pack multiple -> approving it produces a valid
    draft purchase order."""
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id

    # Approving a suggestion CREATES the PO; whether it starts as a draft is decided by
    # purchasing.approval_required (under the threshold a PO is auto-approved otherwise).
    # This test is about the draft that still needs a human, so it asks for that path.
    await SettingsService(db, tid).set("purchasing.approval_required", True, scope=Scope.TENANT)

    wh = await _warehouse(db, tid)
    prod = await CatalogService.create_product(
        db, tid, title="Replenish Item", slug=f"ri-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="15.00")

    supplier = await SupplierService.create(db, tid, name=f"Direct-Dist-{uuid.uuid4().hex[:4]}")

    # Set replenishment policy:
    # min_stock=20 (reorder point), max_stock=50, moq=10, pack multiple=6
    policy = await ReplenishmentService.set_policy(
        db,
        tid,
        variant_id=var.id,
        warehouse_id=wh.id,
        min_stock=20,
        max_stock=50,
        safety_stock=5,
        moq=10,
        order_multiple=6,
        preferred_supplier_id=supplier.id,
    )
    assert policy.min_stock == 20
    assert policy.max_stock == 50
    assert policy.order_multiple == 6

    # Stock 15 units (< 20 min_stock -> triggers reorder!)
    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=15, reason="purchase"
    )

    # Arithmetic breakdown:
    # projected_stock = 15
    # target_stock = 50 (max_stock)
    # gross_req = 50 - 15 = 35
    # moq = 10 (35 >= 10 -> 35)
    # order_multiple = 6 -> ceil(35 / 6) * 6 = 36!

    suggestions = await ReplenishmentService.generate_suggestions(db, tid, warehouse_id=wh.id)
    assert len(suggestions) == 1
    sugg = suggestions[0]
    assert sugg.suggested_quantity == 36, f"Expected 36, got {sugg.suggested_quantity}"
    assert sugg.source == "purchase"
    assert sugg.status == "open"
    assert sugg.reason["projected_stock"] == 15
    assert sugg.reason["target_stock"] == 50
    assert sugg.reason["order_multiple"] == 6

    # Approving suggestion creates a valid draft PurchaseOrder!
    po = await PurchaseService.create_from_reorder_suggestion(
        db, tid, sugg.id, user_id=uid, unit_cost="8.50"
    )
    assert sugg.status == "accepted"
    po_id = po.id

    # Verify the created PurchaseOrder
    po = (
        await db.execute(
            select(PurchaseOrder).where(PurchaseOrder.tenant_id == tid, PurchaseOrder.id == po_id)
        )
    ).scalar_one()
    assert po.status == "draft"
    assert po.supplier_id == supplier.id
    assert po.warehouse_id == wh.id

    po_lines = list(
        (
            await db.execute(
                select(PurchaseOrderLine).where(
                    PurchaseOrderLine.tenant_id == tid,
                    PurchaseOrderLine.purchase_order_id == po.id,
                )
            )
        ).scalars()
    )
    assert len(po_lines) == 1
    assert po_lines[0].variant_id == var.id
    assert po_lines[0].quantity == 36
    assert po_lines[0].unit_cost == pytest.approx(8.50)


# ═══════════════════════════════════════════════════════════════════════════
# 4.2 Dismissing Suggestions and Status Conflicts
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dismiss_and_conflict_handling(db: AsyncSession, tenant_ctx):
    tid = tenant_ctx.tenant_id
    wh = await _warehouse(db, tid)

    prod = await CatalogService.create_product(
        db, tid, title="Dismiss Item", slug=f"di-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="5.00")

    supplier = await SupplierService.create(db, tid, name=f"Dismiss-Sup-{uuid.uuid4().hex[:4]}")

    await ReplenishmentService.set_policy(
        db,
        tid,
        variant_id=var.id,
        warehouse_id=wh.id,
        min_stock=10,
        preferred_supplier_id=supplier.id,
    )

    # 0 on hand < 10
    sugg = await ReplenishmentService.evaluate_variant(
        db, tid, variant_id=var.id, warehouse_id=wh.id
    )
    assert sugg is not None
    assert sugg.status == "open"

    # Dismiss
    dismissed = await ReplenishmentService.dismiss_suggestion(
        db, tid, sugg.id, reason="Season ended"
    )
    assert dismissed.status == "dismissed"
    assert dismissed.reason["dismiss_reason"] == "Season ended"

    # Cannot approve dismissed suggestion
    with pytest.raises(ConflictError, match="already dismissed"):
        await ReplenishmentService.approve_suggestion(db, tid, sugg.id)
