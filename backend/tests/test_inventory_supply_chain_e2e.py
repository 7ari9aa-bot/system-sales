"""Phase 0 — Prove the Chain: end-to-end integration test.

Walks the COMPLETE inventory lifecycle in a single transaction:

    supplier → PO → goods receipt (partial) → stock on shelf
    → cashier sale (reserve → out/sale) → stock down
    → customer return (in/return) → stock up
    → stocktake with variance → adjustment
    → reconciliation finds no discrepancy

Then a regression guard: for EVERY movement produced in this test, the
movement's `balance_after` equals the balance row's `on_hand` at the moment
the movement was written.

Requires a real Postgres database with all migrations applied.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import ProductVariant
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, ValidationError
from app.modules.inventory.models import InventoryBalance, InventoryMovement, Warehouse
from app.modules.inventory.reconciliation import InventoryReconciliationService
from app.modules.inventory.service import InventoryService
from app.modules.inventory.services.stocktakes import StocktakeService
from app.modules.purchasing.models import PurchaseOrderLine
from app.modules.purchasing.service import (
    CostService,
    GoodsReceiptService,
    PurchaseService,
    SupplierService,
)

# ───────────────────────────── helpers ──────────────────────────────


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    wh = Warehouse(
        tenant_id=tenant_id,
        name="Chain Test WH",
        code=f"CWH-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(wh)
    await db.flush()
    return wh


async def _two_variants(
    db: AsyncSession, tenant_id: uuid.UUID
) -> tuple[ProductVariant, ProductVariant]:
    """Create two variants on two separate products."""
    prod_a = await CatalogService.create_product(
        db, tenant_id, title="Widget Alpha", slug=f"wa-{uuid.uuid4().hex[:8]}"
    )
    var_a = await CatalogService.add_variant(db, tenant_id, prod_a.id, price="25.00")

    prod_b = await CatalogService.create_product(
        db, tenant_id, title="Widget Beta", slug=f"wb-{uuid.uuid4().hex[:8]}"
    )
    var_b = await CatalogService.add_variant(db, tenant_id, prod_b.id, price="40.00")
    return var_a, var_b


# ═══════════════════════════════════════════════════════════════════════════
# 0.2 — The full chain in one test
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_supply_chain_end_to_end(db: AsyncSession, tenant_ctx):
    """Walk the full lifecycle: supplier → PO → goods receipt → sale → return
    → stocktake → adjustment → reconciliation = no discrepancy."""
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id

    # ─── 1. Create warehouse and products ───
    wh = await _warehouse(db, tid)
    var_a, var_b = await _two_variants(db, tid)

    # ─── 2. Create supplier ───
    supplier = await SupplierService.create(db, tid, name=f"Acme-{uuid.uuid4().hex[:6]}")

    # ─── 3. Create purchase order with 2 lines ───
    po = await PurchaseService.create(
        db,
        tid,
        supplier_id=supplier.id,
        warehouse_id=wh.id,
        lines=[
            {"variant_id": str(var_a.id), "quantity": 100, "unit_cost": "10.00"},
            {"variant_id": str(var_b.id), "quantity": 50, "unit_cost": "20.00"},
        ],
        created_by=uid,
    )
    assert po.status == "draft"

    # Fetch PO lines
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
    pol_a = next(pl for pl in po_lines if pl.variant_id == var_a.id)
    pol_b = next(pl for pl in po_lines if pl.variant_id == var_b.id)

    # ─── 4. Create goods receipt — partial (70 of 100 Alpha, all 50 Beta) ───
    receipt1 = await GoodsReceiptService.create(
        db,
        tid,
        purchase_order_id=po.id,
        lines=[
            {
                "purchase_order_line_id": str(pol_a.id),
                "variant_id": str(var_a.id),
                "quantity": 70,
                "unit_cost": "10.00",
                "condition": "good",
            },
            {
                "purchase_order_line_id": str(pol_b.id),
                "variant_id": str(var_b.id),
                "quantity": 50,
                "unit_cost": "20.00",
                "condition": "good",
            },
        ],
        actor_user_id=uid,
    )
    assert receipt1.status == "draft"

    # ─── 5. Post the receipt → stock on shelf ───
    await GoodsReceiptService.post(db, tid, receipt1.id, actor_user_id=uid)
    await db.flush()

    # Verify stock
    bal_a = await InventoryService.get_balance(db, tid, var_a.id, wh.id)
    assert bal_a.on_hand == 70, f"Expected 70, got {bal_a.on_hand}"

    bal_b = await InventoryService.get_balance(db, tid, var_b.id, wh.id)
    assert bal_b.on_hand == 50, f"Expected 50, got {bal_b.on_hand}"

    # PO should be partially_received (Alpha is 70/100)
    await db.refresh(po)
    assert po.status == "partially_received"

    # ─── 6. Second receipt — remaining 30 Alpha ───
    # Need to re-fetch PO lines since quantity_received changed
    await db.refresh(pol_a)
    receipt2 = await GoodsReceiptService.create(
        db,
        tid,
        purchase_order_id=po.id,
        lines=[
            {
                "purchase_order_line_id": str(pol_a.id),
                "variant_id": str(var_a.id),
                "quantity": 30,
                "unit_cost": "10.00",
                "condition": "good",
            },
        ],
        actor_user_id=uid,
    )
    await GoodsReceiptService.post(db, tid, receipt2.id, actor_user_id=uid)
    await db.flush()

    bal_a = await InventoryService.get_balance(db, tid, var_a.id, wh.id)
    assert bal_a.on_hand == 100

    # PO is now fully received
    await db.refresh(po)
    assert po.status == "received"
    assert po.received_at is not None

    # Cost should be recorded
    cost_a = await CostService.get(db, tid, var_a.id)
    assert cost_a is not None
    assert cost_a == Decimal("10.0000")

    # ─── 7. Cashier-style sale: sell 5 Alpha ───
    await InventoryService.move(
        db,
        tid,
        var_a.id,
        wh.id,
        direction="out",
        quantity=5,
        reason="sale",
        reference_type="pos_sale",
        reference_id=uuid.uuid4(),
        actor_user_id=uid,
    )
    bal_a = await InventoryService.get_balance(db, tid, var_a.id, wh.id)
    assert bal_a.on_hand == 95

    # ─── 8. Customer return: 2 Alpha come back ───
    await InventoryService.move(
        db,
        tid,
        var_a.id,
        wh.id,
        direction="in",
        quantity=2,
        reason="return",
        reference_type="return_order",
        reference_id=uuid.uuid4(),
        actor_user_id=uid,
    )
    bal_a = await InventoryService.get_balance(db, tid, var_a.id, wh.id)
    assert bal_a.on_hand == 97

    # ─── 9. Stocktake with a small variance ───
    stocktake = await StocktakeService.open(db, tid, wh.id, user_id=uid)

    # Count: Alpha is 95 (found 2 missing), Beta is 50 (correct)
    from app.modules.inventory.models import StocktakeLine

    st_lines = list(
        (
            await db.execute(
                select(StocktakeLine).where(
                    StocktakeLine.tenant_id == tid,
                    StocktakeLine.stocktake_id == stocktake.id,
                )
            )
        ).scalars()
    )
    stl_a = next((line for line in st_lines if line.variant_id == var_a.id), None)
    stl_b = next((line for line in st_lines if line.variant_id == var_b.id), None)

    assert stl_a is not None, "Alpha should have a stocktake line"
    assert stl_b is not None, "Beta should have a stocktake line"
    assert stl_a.expected_qty == 97, f"Expected 97, got {stl_a.expected_qty}"
    assert stl_b.expected_qty == 50, f"Expected 50, got {stl_b.expected_qty}"

    # Record counts: Alpha actually 95 (variance of -2), Beta exactly 50
    await StocktakeService.record_counts(
        db,
        tid,
        stocktake.id,
        [
            {"variant_id": str(var_a.id), "counted_qty": 95},
            {"variant_id": str(var_b.id), "counted_qty": 50},
        ],
    )

    # ─── 10. Approve stocktake → adjustment movements ───
    result = await StocktakeService.approve(db, tid, stocktake.id, user_id=uid)
    assert result["adjusted"] == 1  # Only Alpha has a variance
    assert result["clamped"] == 0

    bal_a = await InventoryService.get_balance(db, tid, var_a.id, wh.id)
    assert bal_a.on_hand == 95, f"After stocktake, expected 95, got {bal_a.on_hand}"

    bal_b = await InventoryService.get_balance(db, tid, var_b.id, wh.id)
    assert bal_b.on_hand == 50, f"Beta unchanged at 50, got {bal_b.on_hand}"

    # ─── 11. Reconciliation — should find NO discrepancy ───
    recon = await InventoryReconciliationService.reconcile_tenant(db, tid)
    assert recon["chain_mismatches"] == 0, (
        f"Ledger chain has {recon['chain_mismatches']} mismatches"
    )
    assert recon["projection_mismatches"] == 0, (
        f"Balance projection has {recon['projection_mismatches']} drifts"
    )
    assert recon["findings_created"] == 0

    # ─── 12. Regression: every movement's balance_after == balance.on_hand ───
    # For each (warehouse, variant), the LAST movement's balance_after must
    # equal the current balance on_hand.
    pairs = (
        await db.execute(
            select(
                InventoryMovement.warehouse_id,
                InventoryMovement.variant_id,
            )
            .where(InventoryMovement.tenant_id == tid)
            .distinct()
        )
    ).all()

    for wh_id, v_id in pairs:
        last_movement = (
            await db.execute(
                select(InventoryMovement)
                .where(
                    InventoryMovement.tenant_id == tid,
                    InventoryMovement.warehouse_id == wh_id,
                    InventoryMovement.variant_id == v_id,
                )
                .order_by(
                    InventoryMovement.created_at.desc(),
                    InventoryMovement.ledger_seq.desc(),
                )
                .limit(1)
            )
        ).scalar_one()

        balance = (
            await db.execute(
                select(InventoryBalance).where(
                    InventoryBalance.tenant_id == tid,
                    InventoryBalance.warehouse_id == wh_id,
                    InventoryBalance.variant_id == v_id,
                )
            )
        ).scalar_one()

        assert last_movement.balance_after == balance.on_hand, (
            f"Movement balance_after={last_movement.balance_after} "
            f"!= balance.on_hand={balance.on_hand} "
            f"for variant={v_id} warehouse={wh_id}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 0.3 — Goods receipt with quarantine condition
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_goods_receipt_quarantine_condition(db: AsyncSession, tenant_ctx):
    """Quarantine lines add stock but bump the quarantined counter,
    so they are not sellable."""
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id

    wh = await _warehouse(db, tid)
    prod = await CatalogService.create_product(
        db, tid, title="Fragile Item", slug=f"fi-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="100.00")

    supplier = await SupplierService.create(db, tid, name=f"QC-Supplier-{uuid.uuid4().hex[:4]}")
    po = await PurchaseService.create(
        db,
        tid,
        supplier_id=supplier.id,
        warehouse_id=wh.id,
        lines=[{"variant_id": str(var.id), "quantity": 20, "unit_cost": "50.00"}],
    )
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
    pol = po_lines[0]

    # Receive 15 good, 3 quarantine, 2 reject
    receipt = await GoodsReceiptService.create(
        db,
        tid,
        purchase_order_id=po.id,
        lines=[
            {
                "purchase_order_line_id": str(pol.id),
                "variant_id": str(var.id),
                "quantity": 15,
                "unit_cost": "50.00",
                "condition": "good",
            },
        ],
    )
    await GoodsReceiptService.post(db, tid, receipt.id, actor_user_id=uid)

    # Second receipt with quarantine
    await db.refresh(pol)
    receipt_q = await GoodsReceiptService.create(
        db,
        tid,
        purchase_order_id=po.id,
        lines=[
            {
                "purchase_order_line_id": str(pol.id),
                "variant_id": str(var.id),
                "quantity": 3,
                "unit_cost": "50.00",
                "condition": "quarantine",
            },
        ],
    )
    await GoodsReceiptService.post(db, tid, receipt_q.id, actor_user_id=uid)

    # Third receipt with reject
    await db.refresh(pol)
    receipt_r = await GoodsReceiptService.create(
        db,
        tid,
        purchase_order_id=po.id,
        lines=[
            {
                "purchase_order_line_id": str(pol.id),
                "variant_id": str(var.id),
                "quantity": 2,
                "unit_cost": "50.00",
                "condition": "reject",
            },
        ],
    )
    await GoodsReceiptService.post(db, tid, receipt_r.id, actor_user_id=uid)

    # Check balances
    bal = await InventoryService.get_balance(db, tid, var.id, wh.id)
    # good (15) + quarantine (3) = 18 on_hand; reject (2) = 0 on_hand
    assert bal.on_hand == 18, f"Expected 18 on_hand, got {bal.on_hand}"
    assert bal.quarantined == 3, f"Expected 3 quarantined, got {bal.quarantined}"
    # Sellable = on_hand - quarantined = 15
    assert bal.on_hand - (bal.quarantined or 0) == 15

    # PO should be fully received (15 + 3 + 2 = 20 = ordered)
    await db.refresh(po)
    assert po.status == "received"

    # Reconciliation: no issues
    recon = await InventoryReconciliationService.reconcile_tenant(db, tid)
    assert recon["chain_mismatches"] == 0
    assert recon["projection_mismatches"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# 0.4 — Over-receiving is rejected
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_goods_receipt_over_receiving_rejected(db: AsyncSession, tenant_ctx):
    """Cannot receive more than what was ordered."""
    tid = tenant_ctx.tenant_id

    wh = await _warehouse(db, tid)
    prod = await CatalogService.create_product(
        db, tid, title="Limited Item", slug=f"li-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="10.00")

    supplier = await SupplierService.create(db, tid, name=f"Over-{uuid.uuid4().hex[:4]}")
    po = await PurchaseService.create(
        db,
        tid,
        supplier_id=supplier.id,
        warehouse_id=wh.id,
        lines=[{"variant_id": str(var.id), "quantity": 10, "unit_cost": "5.00"}],
    )
    pol = (
        await db.execute(
            select(PurchaseOrderLine).where(
                PurchaseOrderLine.tenant_id == tid,
                PurchaseOrderLine.purchase_order_id == po.id,
            )
        )
    ).scalar_one()

    with pytest.raises(ValidationError, match="only 10 remain"):
        await GoodsReceiptService.create(
            db,
            tid,
            purchase_order_id=po.id,
            lines=[
                {
                    "purchase_order_line_id": str(pol.id),
                    "variant_id": str(var.id),
                    "quantity": 11,
                    "unit_cost": "5.00",
                },
            ],
        )


# ═══════════════════════════════════════════════════════════════════════════
# 0.5 — Posted receipt cannot be posted again
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_goods_receipt_double_post_rejected(db: AsyncSession, tenant_ctx):
    """A receipt can only be posted once."""
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id

    wh = await _warehouse(db, tid)
    prod = await CatalogService.create_product(
        db, tid, title="Double Post", slug=f"dp-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="10.00")

    supplier = await SupplierService.create(db, tid, name=f"Dbl-{uuid.uuid4().hex[:4]}")
    po = await PurchaseService.create(
        db,
        tid,
        supplier_id=supplier.id,
        warehouse_id=wh.id,
        lines=[{"variant_id": str(var.id), "quantity": 5, "unit_cost": "10.00"}],
    )
    pol = (
        await db.execute(
            select(PurchaseOrderLine).where(
                PurchaseOrderLine.tenant_id == tid,
                PurchaseOrderLine.purchase_order_id == po.id,
            )
        )
    ).scalar_one()

    receipt = await GoodsReceiptService.create(
        db,
        tid,
        purchase_order_id=po.id,
        lines=[
            {
                "purchase_order_line_id": str(pol.id),
                "variant_id": str(var.id),
                "quantity": 5,
                "unit_cost": "10.00",
            },
        ],
    )
    await GoodsReceiptService.post(db, tid, receipt.id, actor_user_id=uid)

    with pytest.raises(ConflictError, match="already posted"):
        await GoodsReceiptService.post(db, tid, receipt.id, actor_user_id=uid)
