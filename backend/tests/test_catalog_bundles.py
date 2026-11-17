"""Tests for Product Bundles and Kits (§4 Phase 6, 6.2).

Exit criterion:
  Selling a bundle decrements each component exactly once and never lets the bundle
  sell past its components' availability.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InsufficientStockError
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, ValidationError
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import (
    InventoryBundleService,
    InventoryService,
)


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    wh = Warehouse(
        tenant_id=tenant_id,
        name="Bundle WH",
        code=f"BND-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(wh)
    await db.flush()
    return wh


# ═══════════════════════════════════════════════════════════════════════════
# 6.1 Phase 6 Exit Criterion Test: Bundle Availability & Component Decrement
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bundle_exit_criterion_decrements_components_and_caps_availability(
    db: AsyncSession, tenant_ctx
):
    """Exit criterion:
    Selling a bundle decrements each component exactly once and never lets the bundle
    sell past its components' availability.
    """
    tid = tenant_ctx.tenant_id
    uid = tenant_ctx.user.id
    wh = await _warehouse(db, tid)

    # Base products for components
    prod_a = await CatalogService.create_product(
        db, tid, title="Component A", slug=f"ca-{uuid.uuid4().hex[:8]}"
    )
    var_a = await CatalogService.add_variant(db, tid, prod_a.id, price="10.00")

    prod_b = await CatalogService.create_product(
        db, tid, title="Component B", slug=f"cb-{uuid.uuid4().hex[:8]}"
    )
    var_b = await CatalogService.add_variant(db, tid, prod_b.id, price="20.00")

    # Bundle product
    prod_bundle = await CatalogService.create_product(
        db, tid, title="Gift Set Bundle", slug=f"gs-{uuid.uuid4().hex[:8]}"
    )

    # Bundle definition: 1 Gift Set = 2x Component A + 1x Component B
    bundle = await CatalogService.create_bundle(
        db,
        tid,
        product_id=prod_bundle.id,
        name="Holiday Gift Set",
        bundle_type="bundle",
        lines=[
            {"variant_id": var_a.id, "quantity": 2},
            {"variant_id": var_b.id, "quantity": 1},
        ],
    )
    assert bundle.name == "Holiday Gift Set"
    assert bundle.bundle_type == "bundle"
    assert bundle.is_active is True

    # Initial stock:
    # Component A: 10 units (can make 10 // 2 = 5 bundles)
    # Component B: 3 units (can make 3 // 1 = 3 bundles)
    # Maximum bundle availability must be min(5, 3) = 3!
    await InventoryService.move(
        db, tid, var_a.id, wh.id, direction="in", quantity=10, reason="purchase"
    )
    await InventoryService.move(
        db, tid, var_b.id, wh.id, direction="in", quantity=3, reason="purchase"
    )

    avail = await InventoryBundleService.get_bundle_availability(
        db, tid, bundle_id=bundle.id, warehouse_id=wh.id
    )
    assert avail == 3, f"Expected 3 bundles available, got {avail}"

    # Selling 4 bundles MUST BE REFUSED (would exceed Component B's stock)
    with pytest.raises(InsufficientStockError, match="insufficient stock for component variant"):
        await InventoryBundleService.sell_bundle(
            db, tid, bundle_id=bundle.id, warehouse_id=wh.id, quantity=4, actor_user_id=uid
        )

    # Verify component stock was NOT decremented on failed sale
    bal_a = await InventoryService.get_balance(db, tid, var_a.id, wh.id)
    bal_b = await InventoryService.get_balance(db, tid, var_b.id, wh.id)
    assert bal_a.on_hand == 10
    assert bal_b.on_hand == 3

    # Sell 2 bundles:
    # Component A must be decremented by 2 * 2 = 4 units -> 10 - 4 = 6
    # Component B must be decremented by 2 * 1 = 2 units -> 3 - 2 = 1
    # Each component is decremented exactly once!
    movements = await InventoryBundleService.sell_bundle(
        db, tid, bundle_id=bundle.id, warehouse_id=wh.id, quantity=2, actor_user_id=uid
    )
    assert len(movements) == 2

    mov_a = next(m for m in movements if m.variant_id == var_a.id)
    mov_b = next(m for m in movements if m.variant_id == var_b.id)
    assert mov_a.direction == "out"
    assert mov_a.quantity == 4
    assert mov_a.reason == "sale"
    assert mov_a.balance_after == 6

    assert mov_b.direction == "out"
    assert mov_b.quantity == 2
    assert mov_b.reason == "sale"
    assert mov_b.balance_after == 1

    bal_a = await InventoryService.get_balance(db, tid, var_a.id, wh.id)
    bal_b = await InventoryService.get_balance(db, tid, var_b.id, wh.id)
    assert bal_a.on_hand == 6
    assert bal_b.on_hand == 1

    # Remaining bundle availability is now min(6 // 2, 1 // 1) = 1
    avail_after = await InventoryBundleService.get_bundle_availability(
        db, tid, bundle_id=bundle.id, warehouse_id=wh.id
    )
    assert avail_after == 1


# ═══════════════════════════════════════════════════════════════════════════
# 6.2 Bundle Validation and Invariant Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bundle_creation_validations(db: AsyncSession, tenant_ctx):
    tid = tenant_ctx.tenant_id
    prod = await CatalogService.create_product(
        db, tid, title="Test Prod", slug=f"tp-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="10.00")

    # Invalid bundle type
    with pytest.raises(ValidationError, match="invalid bundle_type"):
        await CatalogService.create_bundle(
            db,
            tid,
            product_id=prod.id,
            name="Bad Type",
            bundle_type="invalid",
            lines=[{"variant_id": var.id, "quantity": 1}],
        )

    # Empty lines
    with pytest.raises(ValidationError, match="at least one component line"):
        await CatalogService.create_bundle(
            db, tid, product_id=prod.id, name="Empty", bundle_type="bundle", lines=[]
        )

    # Duplicate variant in component lines
    with pytest.raises(ConflictError, match="specified more than once"):
        await CatalogService.create_bundle(
            db,
            tid,
            product_id=prod.id,
            name="Dup Lines",
            bundle_type="bundle",
            lines=[
                {"variant_id": var.id, "quantity": 1},
                {"variant_id": var.id, "quantity": 2},
            ],
        )
