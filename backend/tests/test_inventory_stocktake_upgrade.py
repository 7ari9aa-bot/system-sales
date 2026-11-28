"""Tests for Stocktake Upgrades (§4 Phase 2.2 — Kinds, Blind Counts, Recounts, Assignments).

Covers:
  - 2.2.1 Kinds: full, cycle, blind, spot, abc.
  - 2.2.2 Blind counts: counters cannot see expected_qty or current_qty.
  - 2.2.3 Scoped counts (spot / cycle): only variants in scope receive lines.
  - 2.2.4 Variance threshold and recount tracking.
  - 2.2.5 Counter assignment and progress tracking.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.apparel.modules.catalog.service import CatalogService
from app.applications.apparel.modules.inventory.models import Warehouse
from app.applications.apparel.modules.inventory.service import InventoryService, StocktakeService


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    wh = Warehouse(
        tenant_id=tenant_id,
        name="Stocktake WH",
        code=f"ST-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(wh)
    await db.flush()
    return wh


# ═══════════════════════════════════════════════════════════════════════════
# 2.2.1 Blind Counts
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_blind_stocktake_hides_book_quantities_from_counters(db: AsyncSession, tenant_ctx):
    """In a blind count, counters must not see expected_qty or current_qty."""
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id

    wh = await _warehouse(db, tid)
    prod = await CatalogService.create_product(
        db, tid, title="Secret Stock", slug=f"ss-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="10.00")

    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=42, reason="purchase"
    )

    # Open blind stocktake
    st = await StocktakeService.open(
        db,
        tid,
        wh.id,
        kind="blind",
        user_id=uid,
        note="Annual blind audit",
    )
    assert st.blind is True
    assert st.kind == "blind"

    # Counter view: expected_qty and current_qty are hidden (None)
    counter_view = await StocktakeService.detail(db, tid, st.id, for_counter=True)
    assert counter_view["blind"] is True
    line_c = counter_view["lines"][0]
    assert line_c["expected_qty"] is None, "Counter must not see expected_qty in blind count"
    assert line_c["current_qty"] is None, "Counter must not see current_qty in blind count"

    # Manager view: expected_qty and current_qty are revealed
    manager_view = await StocktakeService.detail(db, tid, st.id, for_counter=False)
    line_m = manager_view["lines"][0]
    assert line_m["expected_qty"] == 42
    assert line_m["current_qty"] == 42


# ═══════════════════════════════════════════════════════════════════════════
# 2.2.2 Scoped Counts (Spot / Cycle)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scoped_spot_stocktake(db: AsyncSession, tenant_ctx):
    """A spot count only creates lines for variants explicitly in scope."""
    tid = tenant_ctx.tenant_id
    wh = await _warehouse(db, tid)

    prod1 = await CatalogService.create_product(
        db, tid, title="Spot Widget 1", slug=f"sw1-{uuid.uuid4().hex[:8]}"
    )
    var1 = await CatalogService.add_variant(db, tid, prod1.id, price="10.00")

    prod2 = await CatalogService.create_product(
        db, tid, title="Spot Widget 2", slug=f"sw2-{uuid.uuid4().hex[:8]}"
    )
    var2 = await CatalogService.add_variant(db, tid, prod2.id, price="20.00")

    await InventoryService.move(
        db, tid, var1.id, wh.id, direction="in", quantity=10, reason="purchase"
    )
    await InventoryService.move(
        db, tid, var2.id, wh.id, direction="in", quantity=20, reason="purchase"
    )

    # Spot count for ONLY var1
    st = await StocktakeService.open(
        db,
        tid,
        wh.id,
        kind="spot",
        scope=[{"variant_id": str(var1.id)}],
        note="Spot check on Widget 1",
    )
    assert st.kind == "spot"

    detail = await StocktakeService.detail(db, tid, st.id)
    assert len(detail["lines"]) == 1
    assert detail["lines"][0]["variant_id"] == str(var1.id)


# ═══════════════════════════════════════════════════════════════════════════
# 2.2.3 Variance Threshold & Recounts
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_recount_threshold_and_recount_tracking(db: AsyncSession, tenant_ctx):
    """Variance exceeding recount_threshold_pct flags needs_recount.
    Submitting an updated count increments recount_count."""
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id
    wh = await _warehouse(db, tid)

    prod = await CatalogService.create_product(
        db, tid, title="Recount Part", slug=f"rp-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="10.00")

    # 100 units expected
    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=100, reason="purchase"
    )

    # 10% threshold
    st = await StocktakeService.open(
        db,
        tid,
        wh.id,
        recount_threshold_pct=10,
    )

    # Count 85 (15% variance > 10% threshold)
    await StocktakeService.record_counts(
        db,
        tid,
        st.id,
        [{"variant_id": str(var.id), "counted_qty": 85}],
        user_id=uid,
    )

    detail = await StocktakeService.detail(db, tid, st.id)
    line = detail["lines"][0]
    assert line["counted_qty"] == 85
    assert line["needs_recount"] is True, "15% variance must flag needs_recount"
    assert line["recount_count"] == 0

    # Recount: second count submitted with 98 (2% variance < 10% threshold)
    await StocktakeService.record_counts(
        db,
        tid,
        st.id,
        [{"variant_id": str(var.id), "counted_qty": 98}],
        user_id=uid,
    )

    detail = await StocktakeService.detail(db, tid, st.id)
    line = detail["lines"][0]
    assert line["counted_qty"] == 98
    assert line["needs_recount"] is False, "2% variance is within 10% threshold"
    assert line["recount_count"] == 1, "recount_count must increment"


# ═══════════════════════════════════════════════════════════════════════════
# 2.2.4 Counter Assignment
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_stocktake_counter_assignment(db: AsyncSession, tenant_ctx):
    """Assigning counters records assignment and tracks progress on record_counts."""
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id
    wh = await _warehouse(db, tid)

    prod = await CatalogService.create_product(
        db, tid, title="Assign Part", slug=f"ap-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="10.00")
    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=10, reason="purchase"
    )

    st = await StocktakeService.open(db, tid, wh.id)

    # Assign user
    asgn = await StocktakeService.assign_counter(db, tid, st.id, user_id=uid)
    assert asgn.status == "assigned"
    assert asgn.counted_lines == 0

    # User records count
    await StocktakeService.record_counts(
        db,
        tid,
        st.id,
        [{"variant_id": str(var.id), "counted_qty": 10}],
        user_id=uid,
    )

    detail = await StocktakeService.detail(db, tid, st.id)
    assert len(detail["assignments"]) == 1
    assert detail["assignments"][0]["user_id"] == str(uid)
    assert detail["assignments"][0]["status"] == "counted"
    assert detail["assignments"][0]["counted_lines"] == 1
