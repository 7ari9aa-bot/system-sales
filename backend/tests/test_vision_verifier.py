"""Vision verifier tests (spec §12.4) — real catalog rows, no mocks.

The verifier is the sell-gate's mirror: draft/archived never verify, only
active variants count, and "available" means on_hand minus reserved across
warehouses. These run against real PostgreSQL with RLS on.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.modules.ai.agents.customer.vision.verifier import verify_products
from app.modules.catalog.models import Product, ProductVariant
from app.modules.inventory.models import InventoryBalance, Warehouse


async def _seed_product(db, tenant_id, *, title: str, status: str = "active") -> Product:
    product = Product(
        tenant_id=tenant_id,
        title=title,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}",
        status=status,
    )
    db.add(product)
    await db.flush()
    return product


async def _seed_variant(db, tenant_id, product: Product, *, is_active: bool = True):
    variant = ProductVariant(
        tenant_id=tenant_id,
        product_id=product.id,
        sku=f"{product.slug[:8]}-{uuid.uuid4().hex[:4].upper()}",
        title=f"{product.title} M",
        price=Decimal("25.00"),
        is_active=is_active,
    )
    db.add(variant)
    await db.flush()
    return variant


async def _seed_stock(
    db, tenant_id, warehouse: Warehouse, variant: ProductVariant, *, on_hand: int, reserved: int = 0
):
    db.add(
        InventoryBalance(
            tenant_id=tenant_id,
            warehouse_id=warehouse.id,
            variant_id=variant.id,
            on_hand=on_hand,
            reserved=reserved,
        )
    )
    await db.flush()


async def test_sellable_counts_only_active_stocked_variants(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    warehouse = Warehouse(
        tenant_id=tenant_id, name="Main", code=f"WH-{uuid.uuid4().hex[:6].upper()}"
    )
    db.add(warehouse)
    await db.flush()

    product = await _seed_product(db, tenant_id, title="Blue Abaya")
    stocked = await _seed_variant(db, tenant_id, product)
    unstocked = await _seed_variant(db, tenant_id, product)
    inactive = await _seed_variant(db, tenant_id, product, is_active=False)
    await _seed_stock(db, tenant_id, warehouse, stocked, on_hand=5, reserved=2)
    await _seed_stock(db, tenant_id, warehouse, unstocked, on_hand=0)
    await _seed_stock(db, tenant_id, warehouse, inactive, on_hand=9)

    result = await verify_products(db, tenant_id, [product.id])
    assert result[product.id] == {"verified": True, "available_variants": 1}


async def test_draft_product_never_verifies_even_with_stock(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    warehouse = Warehouse(
        tenant_id=tenant_id, name="Main", code=f"WH-{uuid.uuid4().hex[:6].upper()}"
    )
    db.add(warehouse)
    await db.flush()

    draft = await _seed_product(db, tenant_id, title="Draft Thing", status="draft")
    variant = await _seed_variant(db, tenant_id, draft)
    await _seed_stock(db, tenant_id, warehouse, variant, on_hand=4)

    result = await verify_products(db, tenant_id, [draft.id])
    assert result[draft.id]["verified"] is False
    assert result[draft.id]["available_variants"] == 1


async def test_variantless_product_verifies_with_zero_variants(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    product = await _seed_product(db, tenant_id, title="No Variants")

    result = await verify_products(db, tenant_id, [product.id])
    assert result[product.id] == {"verified": True, "available_variants": 0}


async def test_stock_sums_across_warehouses_and_shortage_negates(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    wh_a = Warehouse(tenant_id=tenant_id, name="A", code=f"WA-{uuid.uuid4().hex[:6].upper()}")
    wh_b = Warehouse(tenant_id=tenant_id, name="B", code=f"WB-{uuid.uuid4().hex[:6].upper()}")
    db.add_all([wh_a, wh_b])
    await db.flush()

    product = await _seed_product(db, tenant_id, title="Split Stock")
    variant = await _seed_variant(db, tenant_id, product)
    # 2 + 3 on hand, 6 reserved overall: net -1, so the variant is OUT.
    await _seed_stock(db, tenant_id, wh_a, variant, on_hand=2, reserved=1)
    await _seed_stock(db, tenant_id, wh_b, variant, on_hand=3, reserved=5)

    result = await verify_products(db, tenant_id, [product.id])
    assert result[product.id]["available_variants"] == 0


async def test_empty_batch_and_unknown_products(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    assert await verify_products(db, tenant_id, []) == {}
    result = await verify_products(db, tenant_id, [uuid.uuid4()])
    assert result == {}
