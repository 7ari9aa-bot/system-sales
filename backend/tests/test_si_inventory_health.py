"""Tests for SI agent inventory_health read (Phase 6, 6.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import app.modules.purchasing.models  # noqa: F401 - registers purchasing models in metadata
from app.modules.ai.agents.sales_intelligence.permissions import asking_with
from app.modules.ai.tools import TOOLS
from app.modules.catalog.models import Product, ProductVariant
from app.modules.inventory.models import (
    InventoryBalance,
    InventoryCostLayer,
    InventoryLot,
    InventoryPolicy,
    ReorderSuggestion,
    Warehouse,
)


@pytest.fixture(autouse=True)
def _register_tools():
    from app.modules.ai.agents.sales_intelligence import tools as T

    TOOLS.pop("si_shop", None)
    T.register_si_tools()


@pytest.mark.asyncio
async def test_si_inventory_health_empty(db, tenant_ctx):
    """An empty shop returns zero valuation and empty collections without failing."""
    with asking_with({"inventory:read"}):
        res = await TOOLS["si_shop"].handler(db, tenant_ctx.tenant_id, view="inventory_health")

    assert res["status"] == "ok"
    assert res["capability"] == "inventory_health"
    summary = res["summary"]
    assert summary["valuation"]["total_units"] == 0
    assert Decimal(summary["valuation"]["total_value"]) == Decimal(0)
    assert summary["dead_stock"]["count"] == 0
    assert summary["low_stock"]["count"] == 0
    assert summary["expiring_lots"]["count"] == 0
    assert summary["pending_reorders"]["count"] == 0


@pytest.mark.asyncio
async def test_si_inventory_health_populated(db, tenant_ctx):
    """Reports valuation, low stock alerts, expiring lots, and pending reorders."""
    tid = tenant_ctx.tenant_id

    # 1. Warehouse & Product/Variant
    wh = Warehouse(tenant_id=tid, name="Main Hub", code="WH-MAIN", is_active=True)
    prod = Product(tenant_id=tid, title="Test Polo", slug="test-polo", status="active")
    db.add_all([wh, prod])
    await db.flush()

    var = ProductVariant(
        tenant_id=tid,
        product_id=prod.id,
        sku="POLO-BLK-M",
        title="Black M",
        price=Decimal("200"),
        is_active=True,
    )
    db.add(var)
    await db.flush()

    # 2. Balance: 10 on hand, 0 reserved, 0 quarantined -> available = 10
    bal = InventoryBalance(
        tenant_id=tid,
        warehouse_id=wh.id,
        variant_id=var.id,
        on_hand=10,
        reserved=0,
        quarantined=0,
    )
    db.add(bal)

    # 3. Cost layer: 10 units @ 50.00 -> total valuation = 500.00
    cl = InventoryCostLayer(
        tenant_id=tid,
        variant_id=var.id,
        warehouse_id=wh.id,
        received_quantity=10,
        remaining_quantity=10,
        unit_cost=Decimal("50.00"),
    )
    db.add(cl)

    # 4. Replenishment policy: min_stock=15 (available=10 <= 15 -> alert!)
    pol = InventoryPolicy(
        tenant_id=tid,
        variant_id=var.id,
        warehouse_id=wh.id,
        min_stock=15,
        max_stock=30,
    )
    db.add(pol)

    # 5. Lot expiring in 10 days
    lot = InventoryLot(
        tenant_id=tid,
        variant_id=var.id,
        lot_code="LOT-EXP-1",
        expires_at=datetime.now(UTC) + timedelta(days=10),
    )
    db.add(lot)

    # 6. Reorder suggestion
    sug = ReorderSuggestion(
        tenant_id=tid,
        variant_id=var.id,
        warehouse_id=wh.id,
        suggested_quantity=20,
        source="purchase",
        reason={"arithmetic": "deficit 5 + moq"},
        status="open",
    )
    db.add(sug)
    await db.flush()

    # Query via SI tool
    with asking_with({"inventory:read"}):
        res = await TOOLS["si_shop"].handler(db, tid, view="inventory_health")

    assert res["status"] == "ok"
    summary = res["summary"]

    # Check valuation
    assert summary["valuation"]["total_units"] == 10
    assert Decimal(summary["valuation"]["total_value"]) == Decimal("500.00")
    assert len(summary["valuation"]["by_warehouse"]) == 1
    assert summary["valuation"]["by_warehouse"][0]["warehouse"] == "Main Hub"

    # Check low stock
    assert summary["low_stock"]["count"] == 1
    low_item = summary["low_stock"]["items"][0]
    assert low_item["sku"] == "POLO-BLK-M"
    assert low_item["available"] == 10
    assert low_item["min_stock"] == 15
    assert low_item["deficit"] == 5

    # Check expiring lots
    assert summary["expiring_lots"]["count"] == 1
    assert summary["expiring_lots"]["items"][0]["lot_code"] == "LOT-EXP-1"

    # Check pending reorders
    assert summary["pending_reorders"]["count"] == 1
    assert summary["pending_reorders"]["items"][0]["quantity"] == 20
    assert summary["pending_reorders"]["items"][0]["source"] == "purchase"

    # Check typed facts
    facts = res["facts"]
    fact_metrics = {f["metric"] for f in facts}
    assert "inventory_total_value" in fact_metrics
    assert "inventory_low_stock_count" in fact_metrics
    assert "inventory_expiring_lots" in fact_metrics
