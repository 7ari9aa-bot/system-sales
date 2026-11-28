"""Tests for Inventory Valuation: FIFO Cost Layers, COGS, and Landed Cost (§4 Phase 5).

Exit criterion:
  A receipt of 10 at 10 and 10 at 20, then a sale of 12, books 140 of cost against
  the sale (10@10 + 2@20), and the remaining layers are 8 at 20.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.applications.apparel.modules.purchasing.models  # noqa: F401
from app.core.errors import InsufficientStockError
from app.applications.apparel.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, ValidationError
from app.applications.apparel.modules.inventory.models import (
    Warehouse,
)
from app.applications.apparel.modules.inventory.service import (
    InventoryService,
    ValuationService,
)


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    wh = Warehouse(
        tenant_id=tenant_id,
        name="Valuation WH",
        code=f"VAL-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(wh)
    await db.flush()
    return wh


# ═══════════════════════════════════════════════════════════════════════════
# 5.1 Phase 5 Exit Criterion: FIFO Layer Consumption & Sale COGS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fifo_exit_criterion_layers_and_cogs(db: AsyncSession, tenant_ctx):
    """Exit criterion:
    Receipt of 10 at 10 and 10 at 20, then a sale of 12,
    books 140 of cost against the sale, and remaining layers are 8 at 20.
    """
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id
    wh = await _warehouse(db, tid)

    prod = await CatalogService.create_product(
        db, tid, title="Valuation Item", slug=f"vi-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="30.00")

    # 1. Receipt 1: 10 units at 10.00
    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=10, reason="purchase"
    )
    layer1 = await ValuationService.create_cost_layer(
        db,
        tid,
        variant_id=var.id,
        warehouse_id=wh.id,
        quantity=10,
        unit_cost="10.00",
        source_type="receipt",
    )
    assert layer1.remaining_quantity == 10
    assert layer1.unit_cost == Decimal("10.0000")

    # 2. Receipt 2: 10 units at 20.00
    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=10, reason="purchase"
    )
    layer2 = await ValuationService.create_cost_layer(
        db,
        tid,
        variant_id=var.id,
        warehouse_id=wh.id,
        quantity=10,
        unit_cost="20.00",
        source_type="receipt",
    )
    assert layer2.remaining_quantity == 10
    assert layer2.unit_cost == Decimal("20.0000")

    # Pre-sale valuation check: 20 units total = 100 + 200 = 300.00
    pre_val = await ValuationService.calculate_valuation(
        db, tid, warehouse_id=wh.id, variant_id=var.id
    )
    assert pre_val["total_quantity"] == 20
    assert pre_val["total_valuation"] == Decimal("300.0000")
    assert pre_val["average_unit_cost"] == Decimal("15.0000")

    # 3. Sale of 12 units
    sale_ref = uuid.uuid4()
    sale_result = await ValuationService.record_sale(
        db,
        tid,
        variant_id=var.id,
        warehouse_id=wh.id,
        quantity=12,
        reference_id=sale_ref,
        actor_user_id=uid,
    )

    # 10 units from layer 1 @ 10 = 100
    # 2 units from layer 2 @ 20 = 40
    # Total COGS = 140
    expected_cogs = Decimal("140.0000")
    assert sale_result["total_cogs"] == expected_cogs
    assert len(sale_result["consumed_layers"]) == 2
    assert sale_result["consumed_layers"][0]["quantity"] == 10
    assert sale_result["consumed_layers"][0]["cost"] == Decimal("100.0000")
    assert sale_result["consumed_layers"][1]["quantity"] == 2
    assert sale_result["consumed_layers"][1]["cost"] == Decimal("40.0000")

    # Verify movement record has COGS recorded in cost_value
    mov = sale_result["movement"]
    assert mov.direction == "out"
    assert mov.reason == "sale"
    assert mov.quantity == 12
    assert mov.cost_value == expected_cogs
    assert mov.balance_after == 8

    # Verify remaining cost layers: layer 1 is 0, layer 2 is 8 at 20.00!
    await db.refresh(layer1)
    await db.refresh(layer2)
    assert layer1.remaining_quantity == 0
    assert layer2.remaining_quantity == 8
    assert layer2.unit_cost == Decimal("20.0000")

    active_layers = await ValuationService.get_active_layers(
        db, tid, variant_id=var.id, warehouse_id=wh.id
    )
    assert len(active_layers) == 1
    assert active_layers[0].id == layer2.id
    assert active_layers[0].remaining_quantity == 8

    # Post-sale valuation: 8 units @ 20 = 160.00
    post_val = await ValuationService.calculate_valuation(
        db, tid, warehouse_id=wh.id, variant_id=var.id
    )
    assert post_val["total_quantity"] == 8
    assert post_val["total_valuation"] == Decimal("160.0000")
    assert post_val["average_unit_cost"] == Decimal("20.0000")


# ═══════════════════════════════════════════════════════════════════════════
# 5.2 Insufficient Stock and Validation in FIFO Layers
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fifo_layer_insufficient_stock_and_validation(db: AsyncSession, tenant_ctx):
    tid = tenant_ctx.tenant_id
    wh = await _warehouse(db, tid)

    prod = await CatalogService.create_product(
        db, tid, title="Short Item", slug=f"si-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="10.00")

    # Layer creation requires positive quantity and non-negative cost
    with pytest.raises(ValidationError, match="received_quantity must be positive"):
        await ValuationService.create_cost_layer(
            db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=0, unit_cost="5.00"
        )

    with pytest.raises(ValidationError, match="unit_cost cannot be negative"):
        await ValuationService.create_cost_layer(
            db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=5, unit_cost="-1.00"
        )

    await ValuationService.create_cost_layer(
        db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=5, unit_cost="10.00"
    )

    # Trying to consume 10 when only 5 exist raises InsufficientStockError
    with pytest.raises(InsufficientStockError, match="insufficient cost layers"):
        await ValuationService.consume_fifo(
            db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=10
        )


# ═══════════════════════════════════════════════════════════════════════════
# 5.3 Landed Cost Allocation and Posting
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_landed_cost_allocation_and_layer_adjustment(db: AsyncSession, tenant_ctx):
    """Landed cost: freight/customs allocated across received items adjusts unit costs."""
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id
    wh = await _warehouse(db, tid)

    prod1 = await CatalogService.create_product(
        db, tid, title="Import A", slug=f"ia-{uuid.uuid4().hex[:8]}"
    )
    var1 = await CatalogService.add_variant(db, tid, prod1.id, price="50.00")

    prod2 = await CatalogService.create_product(
        db, tid, title="Import B", slug=f"ib-{uuid.uuid4().hex[:8]}"
    )
    var2 = await CatalogService.add_variant(db, tid, prod2.id, price="100.00")

    # Initial cost layers:
    # Var 1: 10 units @ 10.00
    # Var 2: 20 units @ 20.00
    l1 = await ValuationService.create_cost_layer(
        db, tid, variant_id=var1.id, warehouse_id=wh.id, quantity=10, unit_cost="10.00"
    )
    l2 = await ValuationService.create_cost_layer(
        db, tid, variant_id=var2.id, warehouse_id=wh.id, quantity=20, unit_cost="20.00"
    )

    # Landed cost: 300.00 total freight
    lc = await ValuationService.create_landed_cost(
        db, tid, warehouse_id=wh.id, total="300.00", note="Ocean freight & customs", user_id=uid
    )
    assert lc.status == "draft"
    assert lc.total == Decimal("300.00")

    # Allocate by quantity:
    # Var 1: 10 units -> (10 / 30) * 300 = 100.00
    # Var 2: 20 units -> (20 / 30) * 300 = 200.00
    lines = await ValuationService.allocate_landed_cost(
        db,
        tid,
        lc.id,
        method="quantity",
        items=[
            {"variant_id": var1.id, "quantity": 10},
            {"variant_id": var2.id, "quantity": 20},
        ],
    )
    assert len(lines) == 2
    assert lines[0].amount == Decimal("100.00")
    assert lines[1].amount == Decimal("200.00")

    # Post landed cost: folds extra cost into the layers
    # Extra cost for Var 1: 100 / 10 = +10.00 -> unit_cost becomes 10 + 10 = 20.00
    # Extra cost for Var 2: 200 / 20 = +10.00 -> unit_cost becomes 20 + 10 = 30.00
    posted = await ValuationService.post_landed_cost(db, tid, lc.id, user_id=uid)
    assert posted.status == "posted"

    await db.refresh(l1)
    await db.refresh(l2)
    assert l1.unit_cost == Decimal("20.0000")
    assert l2.unit_cost == Decimal("30.0000")

    # Cannot post again
    with pytest.raises(ConflictError, match="already posted"):
        await ValuationService.post_landed_cost(db, tid, lc.id, user_id=uid)
