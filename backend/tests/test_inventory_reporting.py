"""Tests for Inventory Reporting Centre and Analytics (§4 Phase 6, 6.3)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.service import CatalogService
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import (
    InventoryReportingService,
    InventoryService,
    ReplenishmentService,
    ValuationService,
)
from app.modules.inventory.stock_view import StockLevelService


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    wh = Warehouse(
        tenant_id=tenant_id,
        name="Report WH",
        code=f"RPT-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(wh)
    await db.flush()
    return wh


# ═══════════════════════════════════════════════════════════════════════════
# 6.6 Stock Summary Across Positions & Valuation
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_inventory_reporting_stock_summary(db: AsyncSession, tenant_ctx):
    tid = tenant_ctx.tenant_id
    wh = await _warehouse(db, tid)

    prod = await CatalogService.create_product(
        db, tid, title="Report Prod", slug=f"rp-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="25.00")

    # Inward move: 20 units
    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=20, reason="purchase"
    )
    await ValuationService.create_cost_layer(
        db, tid, variant_id=var.id, warehouse_id=wh.id, quantity=20, unit_cost="10.00"
    )

    # Reserve 5 units
    await InventoryService.reserve(db, tid, var.id, wh.id, 5)

    # Quarantine 3 units
    bal = await InventoryService.get_balance(db, tid, var.id, wh.id)
    bal.quarantined = 3
    await db.flush()

    summary = await InventoryReportingService.stock_summary(db, tid, warehouse_id=wh.id)
    assert summary["on_hand"] == 20
    assert summary["reserved"] == 5
    assert summary["quarantined"] == 3
    # sellable = on_hand - quarantined = 20 - 3 = 17
    assert summary["sellable"] == 17
    # available = on_hand - quarantined - reserved = 20 - 3 - 5 = 12
    assert summary["available"] == 12
    # valuation = 20 * 10 = 200.00
    assert summary["total_valuation"] == pytest.approx(200.00)


# ═══════════════════════════════════════════════════════════════════════════
# 6.7 Low Stock Alerts and Dead Stock Detection
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_low_stock_and_dead_stock_reports(db: AsyncSession, tenant_ctx):
    tid = tenant_ctx.tenant_id
    wh = await _warehouse(db, tid)

    prod = await CatalogService.create_product(
        db, tid, title="Alert Prod", slug=f"ap-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="15.00")

    # Set min_stock=15
    await ReplenishmentService.set_policy(
        db, tid, variant_id=var.id, warehouse_id=wh.id, min_stock=15, max_stock=30
    )

    # Stock only 8 units (< 15 -> triggers low stock alert)
    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=8, reason="purchase"
    )

    alerts = await InventoryReportingService.low_stock_alerts(db, tid, warehouse_id=wh.id)
    assert len(alerts) == 1
    assert alerts[0]["variant_id"] == str(var.id)
    assert alerts[0]["available"] == 8
    assert alerts[0]["min_stock"] == 15
    assert alerts[0]["deficit"] == 7
    assert alerts[0]["reorder_quantity"] == 22  # target_stock 30 - available 8

    # Dead stock check: variant with stock on hand and 0 sales in past 30 days
    dead = await InventoryReportingService.dead_stock(db, tid, days_inactive=30, warehouse_id=wh.id)
    assert len(dead) == 1
    assert dead[0]["variant_id"] == str(var.id)
    assert dead[0]["on_hand"] == 8


# ═══════════════════════════════════════════════════════════════════════════
# 6.8 Apparel Insights: Velocity, Stockout Risk & Branch Rebalancing
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_apparel_insights_report(db: AsyncSession, tenant_ctx):
    tid = tenant_ctx.tenant_id
    wh1 = await _warehouse(db, tid)
    wh2 = await _warehouse(db, tid)

    prod = await CatalogService.create_product(
        db, tid, title="T-Shirt Apparel", slug=f"ts-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="30.00")

    # WH1 has initial stock of 7 units, then 5 sales -> leaves 2 starved units
    await InventoryService.move(
        db, tid, var.id, wh1.id, direction="in", quantity=7, reason="purchase"
    )
    # WH2 has surplus stock: 20 units
    await InventoryService.move(
        db, tid, var.id, wh2.id, direction="in", quantity=20, reason="purchase"
    )

    # Record 5 sales on WH1 -> on_hand becomes 2
    await InventoryService.move(db, tid, var.id, wh1.id, direction="out", quantity=5, reason="sale")

    insights = await InventoryReportingService.apparel_insights(db, tid)
    # 1. Top selling contains var
    assert any(item["variant_id"] == str(var.id) for item in insights["top_selling_variants"])
    # Nobody has set a level for this piece, so it is NOT called low - the response says so
    # instead, and no transfer is invented out of a threshold the shop never chose.
    assert insights["stockout_risk_variants"] == []
    assert insights["stockout_risk_unconfigured"] == 2
    assert insights["branch_rebalance_opportunities"] == []

    # The shop's own level: 3 pieces. WH1 holds 2, so it is short by 1 and WH2 can spare it.
    await StockLevelService.set_reorder_level(db, tid, var.id, 3)
    insights = await InventoryReportingService.apparel_insights(db, tid)
    risks = [r for r in insights["stockout_risk_variants"] if r["variant_id"] == str(var.id)]
    assert [
        (r["warehouse_id"], r["available"], r["reorder_level"], r["shortfall"]) for r in risks
    ] == [(str(wh1.id), 2, 3, 1)]
    # 2. Rebalancing suggested from WH2 (above its level) to WH1 (below its level)
    rebalances = [
        r
        for r in insights["branch_rebalance_opportunities"]
        if r["variant_id"] == str(var.id)
        and r["from_warehouse_id"] == str(wh2.id)
        and r["to_warehouse_id"] == str(wh1.id)
    ]
    assert len(rebalances) == 1
    assert rebalances[0]["source_available"] == 20
    # Topped up to its own level (3 - 2), never more, and the source stays above its level.
    assert rebalances[0]["suggested_transfer_quantity"] == 1
    assert rebalances[0]["reorder_level"] == 3
