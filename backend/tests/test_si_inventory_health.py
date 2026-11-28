"""Tests for SI agent inventory_health read (Phase 6, 6.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import app.applications.apparel.modules.purchasing.models  # noqa: F401 - registers purchasing models in metadata
from app.applications.apparel.modules.ai.agents.sales_intelligence.permissions import asking_with
from app.applications.apparel.modules.ai.tools import TOOLS
from app.applications.apparel.modules.catalog.models import Product, ProductVariant
from app.applications.apparel.modules.inventory.models import (
    InventoryBalance,
    InventoryCostLayer,
    InventoryLot,
    InventoryPolicy,
    ReorderSuggestion,
    Warehouse,
)


@pytest.fixture(autouse=True)
def _register_tools():
    from app.applications.apparel.modules.ai.agents.sales_intelligence import tools as T

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


@pytest.mark.asyncio
async def test_si_inventory_health_dead_stock_is_reported_per_warehouse(db, tenant_ctx):
    """One variant in two warehouses is two dead-stock rows whose tied values are its own parts.

    Grouping the query without the warehouse merged the two positions into a single tied_value
    (and could emit the same sku twice), so the report under-counted the positions and told the
    owner the wrong amount was tied up where.
    """
    tid = tenant_ctx.tenant_id

    main = Warehouse(tenant_id=tid, name="Main Hub", code="WH-MAIN", is_active=True)
    overflow = Warehouse(tenant_id=tid, name="Overflow", code="WH-OVR", is_active=True)
    prod = Product(tenant_id=tid, title="Test Polo", slug="test-polo-two-wh", status="active")
    db.add_all([main, overflow, prod])
    await db.flush()

    var = ProductVariant(
        tenant_id=tid,
        product_id=prod.id,
        sku="POLO-TWO-WH",
        title="Black M",
        price=Decimal("200"),
        is_active=True,
    )
    db.add(var)
    await db.flush()

    # The same variant, held in two places, with its own cost in each. No sale movement at all,
    # so both positions are dead stock.
    db.add_all(
        [
            InventoryBalance(
                tenant_id=tid,
                warehouse_id=main.id,
                variant_id=var.id,
                on_hand=6,
                reserved=0,
                quarantined=0,
            ),
            InventoryBalance(
                tenant_id=tid,
                warehouse_id=overflow.id,
                variant_id=var.id,
                on_hand=4,
                reserved=0,
                quarantined=0,
            ),
            InventoryCostLayer(
                tenant_id=tid,
                variant_id=var.id,
                warehouse_id=main.id,
                received_quantity=6,
                remaining_quantity=6,
                unit_cost=Decimal("50.00"),
            ),
            InventoryCostLayer(
                tenant_id=tid,
                variant_id=var.id,
                warehouse_id=overflow.id,
                received_quantity=4,
                remaining_quantity=4,
                unit_cost=Decimal("55.00"),
            ),
        ]
    )
    await db.flush()

    with asking_with({"inventory:read"}):
        res = await TOOLS["si_shop"].handler(db, tid, view="inventory_health")

    dead = res["summary"]["dead_stock"]
    assert dead["count"] == 2

    by_code = {item["warehouse_code"]: item for item in dead["items"]}
    assert set(by_code) == {"WH-MAIN", "WH-OVR"}
    assert by_code["WH-MAIN"]["warehouse"] == "Main Hub"
    assert by_code["WH-OVR"]["warehouse"] == "Overflow"
    assert by_code["WH-MAIN"]["on_hand"] == 6
    assert by_code["WH-OVR"]["on_hand"] == 4
    # Each row carries only its own warehouse's capital; neither is the merged 520.
    assert Decimal(by_code["WH-MAIN"]["tied_value"]) == Decimal("300.00")
    assert Decimal(by_code["WH-OVR"]["tied_value"]) == Decimal("220.00")

    # The parts add up to the total the report states.
    parts = sum((Decimal(item["tied_value"]) for item in dead["items"]), Decimal(0))
    assert parts == Decimal("520.00")
    assert Decimal(dead["tied_value"]) == parts

    # The per-warehouse breakdown says the same thing, one line per warehouse.
    wh_lines = {line["warehouse_code"]: line for line in dead["by_warehouse"]}
    assert set(wh_lines) == {"WH-MAIN", "WH-OVR"}
    assert wh_lines["WH-MAIN"]["count"] == 1
    assert wh_lines["WH-OVR"]["count"] == 1
    assert Decimal(wh_lines["WH-MAIN"]["tied_value"]) == Decimal("300.00")
    assert Decimal(wh_lines["WH-OVR"]["tied_value"]) == Decimal("220.00")

    # Both rows are the same sku, which is the point: two positions, not one merged figure.
    assert {item["sku"] for item in dead["items"]} == {"POLO-TWO-WH"}


@pytest.mark.asyncio
async def test_si_inventory_health_expired_lot_is_not_expiring_soon(db, tenant_ctx):
    """An already expired lot is reported as expired and never counted in an upcoming window."""
    tid = tenant_ctx.tenant_id

    wh = Warehouse(tenant_id=tid, name="Main Hub", code="WH-MAIN", is_active=True)
    prod = Product(tenant_id=tid, title="Test Yogurt", slug="test-yogurt", status="active")
    db.add_all([wh, prod])
    await db.flush()

    var = ProductVariant(
        tenant_id=tid,
        product_id=prod.id,
        sku="YOG-1L",
        title="1 litre",
        price=Decimal("10"),
        is_active=True,
    )
    db.add(var)
    await db.flush()

    now = datetime.now(UTC)
    db.add_all(
        [
            InventoryLot(
                tenant_id=tid,
                variant_id=var.id,
                lot_code="LOT-EXPIRED",
                expires_at=now - timedelta(days=1),
            ),
            InventoryLot(
                tenant_id=tid,
                variant_id=var.id,
                lot_code="LOT-5D",
                expires_at=now + timedelta(days=5),
            ),
            InventoryLot(
                tenant_id=tid,
                variant_id=var.id,
                lot_code="LOT-20D",
                expires_at=now + timedelta(days=20),
            ),
            InventoryLot(
                tenant_id=tid,
                variant_id=var.id,
                lot_code="LOT-45D",
                expires_at=now + timedelta(days=45),
            ),
        ]
    )
    await db.flush()

    with asking_with({"inventory:read"}):
        res = await TOOLS["si_shop"].handler(db, tid, view="inventory_health", expiry_days=60)

    lots = res["summary"]["expiring_lots"]
    codes = {
        bucket: {item["lot_code"] for item in lots[bucket]["items"]}
        for bucket in ("expired", "within_7_days", "within_30_days", "custom_window")
    }

    # Yesterday's lot is expired, and only expired.
    assert lots["expired"]["count"] == 1
    assert codes["expired"] == {"LOT-EXPIRED"}
    assert "LOT-EXPIRED" not in codes["within_7_days"]
    assert "LOT-EXPIRED" not in codes["within_30_days"]
    assert "LOT-EXPIRED" not in codes["custom_window"]

    # The upcoming windows hold only lots that have not expired yet.
    assert lots["within_7_days"]["count"] == 1
    assert codes["within_7_days"] == {"LOT-5D"}
    assert lots["within_30_days"]["count"] == 2
    assert codes["within_30_days"] == {"LOT-5D", "LOT-20D"}
    # The 30-day list is what count/items always meant: upcoming, expired excluded.
    assert lots["count"] == 2
    assert {item["lot_code"] for item in lots["items"]} == {"LOT-5D", "LOT-20D"}

    # The caller's own window reaches past 30 days and still skips the expired lot.
    assert lots["custom_window"]["days"] == 60
    assert lots["custom_window"]["count"] == 3
    assert codes["custom_window"] == {"LOT-5D", "LOT-20D", "LOT-45D"}

    fact_values = {f["metric"]: f["value"] for f in res["facts"]}
    assert Decimal(fact_values["inventory_expired_lots"]) == Decimal(1)
    assert Decimal(fact_values["inventory_expiring_lots"]) == Decimal(2)

    # Without a custom window the fixed buckets are still there and no window is invented.
    with asking_with({"inventory:read"}):
        plain = await TOOLS["si_shop"].handler(db, tid, view="inventory_health")
    assert plain["summary"]["expiring_lots"]["custom_window"] is None
    assert plain["summary"]["expiring_lots"]["expired"]["count"] == 1
    assert plain["summary"]["expiring_lots"]["count"] == 2
