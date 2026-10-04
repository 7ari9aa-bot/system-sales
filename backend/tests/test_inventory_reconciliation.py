"""§188 inventory reconciliation — DB-backed behaviour (P4).

Runs wherever a database URL is configured; conftest skips otherwise.
Discipline note: the drift simulations write through explicit ``UPDATE`` /
``INSERT`` statements (that is the defect being detected), and every
assertion reads plain values back with a ``SELECT`` — no expired attributes.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, update

from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, NotFoundError
from app.modules.inventory.models import (
    InventoryBalance,
    InventoryMovement,
)
from app.modules.inventory.reconciliation import InventoryReconciliationService
from app.modules.inventory.service import InventoryService


async def _variant_and_balance(db, tenant_ctx):
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="كوباية", slug=f"c-{uuid.uuid4().hex[:10]}"
    )
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="سعة كبيرة", price="25.00"
    )
    warehouse = await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)
    await InventoryService.move(
        db,
        tenant_ctx.tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=5,
        reason="purchase",
    )
    await InventoryService.move(
        db,
        tenant_ctx.tenant_id,
        variant.id,
        warehouse.id,
        direction="adjust",
        quantity=3,
        reason="adjustment",
    )
    return variant, warehouse


async def test_clean_ledger_creates_no_findings(db, tenant_ctx):
    await _variant_and_balance(db, tenant_ctx)
    summary = await InventoryReconciliationService.reconcile_tenant(
        db, tenant_ctx.tenant_id
    )
    assert summary["findings_created"] == 0


async def test_projection_drift_becomes_a_finding(db, tenant_ctx):
    variant, warehouse = await _variant_and_balance(db, tenant_ctx)
    await db.execute(
        update(InventoryBalance)
        .where(
            InventoryBalance.tenant_id == tenant_ctx.tenant_id,
            InventoryBalance.variant_id == variant.id,
            InventoryBalance.warehouse_id == warehouse.id,
        )
        .values(on_hand=8)
    )
    summary = await InventoryReconciliationService.reconcile_tenant(
        db, tenant_ctx.tenant_id
    )
    assert summary["projection_mismatches"] == 1
    assert summary["findings_created"] == 1
    rows = await InventoryReconciliationService.list_findings(
        db, tenant_ctx.tenant_id, status="OPEN"
    )
    assert len(rows) == 1
    assert rows[0].check_kind == "projection"
    assert rows[0].expected == 3
    assert rows[0].actual == 8
    # Idempotent per run: the same open discrepancy is not re-recorded.
    again = await InventoryReconciliationService.reconcile_tenant(
        db, tenant_ctx.tenant_id
    )
    assert again["findings_created"] == 0


async def test_forged_chain_row_becomes_a_finding(db, tenant_ctx):
    variant, warehouse = await _variant_and_balance(db, tenant_ctx)
    db.add(
        InventoryMovement(
            tenant_id=tenant_ctx.tenant_id,
            variant_id=variant.id,
            warehouse_id=warehouse.id,
            direction="out",
            quantity=1,
            reason="damage",
            balance_after=3,
        )
    )
    await db.flush()
    summary = await InventoryReconciliationService.reconcile_tenant(
        db, tenant_ctx.tenant_id
    )
    assert summary["chain_mismatches"] == 1
    rows = await InventoryReconciliationService.list_findings(
        db, tenant_ctx.tenant_id, status="OPEN"
    )
    chain = [r for r in rows if r.check_kind == "chain"]
    assert len(chain) == 1
    assert chain[0].expected == 2
    assert chain[0].actual == 3
    assert chain[0].movement_id is not None


async def test_resolve_is_once_and_records_who(db, tenant_ctx):
    variant, warehouse = await _variant_and_balance(db, tenant_ctx)
    await db.execute(
        update(InventoryBalance)
        .where(
            InventoryBalance.tenant_id == tenant_ctx.tenant_id,
            InventoryBalance.variant_id == variant.id,
            InventoryBalance.warehouse_id == warehouse.id,
        )
        .values(on_hand=99)
    )
    await InventoryReconciliationService.reconcile_tenant(db, tenant_ctx.tenant_id)
    (finding,) = await InventoryReconciliationService.list_findings(
        db, tenant_ctx.tenant_id, status="OPEN"
    )
    resolved = await InventoryReconciliationService.resolve_finding(
        db,
        tenant_ctx.tenant_id,
        finding.id,
        resolved_by=tenant_ctx.user.id,
        note="stocktake correction scheduled",
    )
    assert resolved.status == "RESOLVED"
    assert resolved.resolved_by == tenant_ctx.user.id
    with pytest.raises(ConflictError):
        await InventoryReconciliationService.resolve_finding(
            db, tenant_ctx.tenant_id, finding.id, resolved_by=tenant_ctx.user.id
        )
    with pytest.raises(NotFoundError):
        await InventoryReconciliationService.resolve_finding(
            db, tenant_ctx.tenant_id, uuid.uuid4(), resolved_by=tenant_ctx.user.id
        )


async def test_replayed_ledger_matches_the_projection_order_independently(db, tenant_ctx):
    """The replay order is (created_at, ledger_seq) — rows written in one
    transaction must not reorder into phantom discrepancies."""
    variant, warehouse = await _variant_and_balance(db, tenant_ctx)
    # One more sale in the same transaction as the rows above: created_at is
    # identical, only ledger_seq separates them.
    await InventoryService.move(
        db,
        tenant_ctx.tenant_id,
        variant.id,
        warehouse.id,
        direction="out",
        quantity=1,
        reason="sale",
    )
    summary = await InventoryReconciliationService.reconcile_tenant(
        db, tenant_ctx.tenant_id
    )
    assert summary["chain_mismatches"] == 0
    assert summary["findings_created"] == 0
    balance = (
        await db.execute(
            select(InventoryBalance.on_hand).where(
                InventoryBalance.tenant_id == tenant_ctx.tenant_id,
                InventoryBalance.variant_id == variant.id,
            )
        )
    ).scalar_one()
    assert balance == 2
