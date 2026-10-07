"""CatalogService tests — uniqueness, price tiers, tenant guards."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import ProductPrice
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, NotFoundError


async def _product(db: AsyncSession, tenant_id: uuid.UUID, slug: str | None = None):
    return await CatalogService.create_product(
        db,
        tenant_id,
        title="Test Product",
        slug=slug or f"p-{uuid.uuid4().hex[:10]}",
    )


async def test_duplicate_slug_conflicts(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    slug = f"slug-{uuid.uuid4().hex[:10]}"
    await _product(db, tenant_id, slug=slug)

    with pytest.raises(ConflictError):
        await _product(db, tenant_id, slug=slug)
    await db.flush()


async def test_create_product_defaults_and_attributes(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    product = await _product(db, tenant_id)
    assert product.title == "Test Product"
    assert product.status == "draft"
    assert product.attributes == {}
    await db.flush()


async def test_add_variant_price_validation_and_sku_conflict(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    product = await _product(db, tenant_id)

    variant = await CatalogService.add_variant(
        db,
        tenant_id,
        product.id,
        sku=f"SKU-{uuid.uuid4().hex[:8].upper()}",
        title="Red / M",
        option_values={"color": "red", "size": "M"},
        price="49.99",
    )
    assert variant.price == Decimal("49.99")
    assert variant.option_values == {"color": "red", "size": "M"}

    with pytest.raises(ValueError):
        await CatalogService.add_variant(db, tenant_id, product.id, price="0")
    with pytest.raises(ValueError):
        await CatalogService.add_variant(db, tenant_id, product.id, price="-5")

    with pytest.raises(ConflictError):
        await CatalogService.add_variant(db, tenant_id, product.id, sku=variant.sku, price="10")
    await db.flush()


async def test_set_variant_price_writes_and_updates_price_row(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    product = await _product(db, tenant_id)
    variant = await CatalogService.add_variant(db, tenant_id, product.id, price="10.00")

    row = await CatalogService.set_variant_price(
        db, tenant_id, variant.id, "49.99", currency="EGP", min_quantity=1
    )
    assert row.unit_price == Decimal("49.99")
    assert row.currency == "EGP" and row.min_quantity == 1

    stored = (
        (
            await db.execute(
                select(ProductPrice).where(
                    ProductPrice.tenant_id == tenant_id,
                    ProductPrice.variant_id == variant.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(stored) == 1
    assert stored[0].unit_price == Decimal("49.99")

    # Re-pricing the same tier updates the row instead of duplicating it.
    await CatalogService.set_variant_price(db, tenant_id, variant.id, "59.99")
    stored_after = (
        (
            await db.execute(
                select(ProductPrice).where(
                    ProductPrice.tenant_id == tenant_id,
                    ProductPrice.variant_id == variant.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(stored_after) == 1
    assert stored_after[0].unit_price == Decimal("59.99")
    await db.flush()


async def test_get_variant_tenant_guard(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    product = await _product(db, tenant_id)
    variant = await CatalogService.add_variant(db, tenant_id, product.id, price="5.00")

    found = await CatalogService.get_variant(db, tenant_id, variant.id)
    assert found.id == variant.id

    with pytest.raises(NotFoundError):
        await CatalogService.get_variant(db, uuid.uuid4(), variant.id)
    with pytest.raises(NotFoundError):
        await CatalogService.get_variant(db, tenant_id, uuid.uuid4())
    await db.flush()


async def test_update_and_archive_product(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    product = await _product(db, tenant_id)

    updated = await CatalogService.update_product(
        db, tenant_id, product.id, title="Renamed", description="desc"
    )
    assert updated.title == "Renamed"
    assert updated.description == "desc"

    archived = await CatalogService.archive_product(db, tenant_id, product.id)
    assert archived.status == "archived"

    with pytest.raises(ValueError):
        await CatalogService.update_product(db, tenant_id, product.id, nope=1)
    await db.flush()


async def test_brands_and_categories(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    brand = await CatalogService.create_brand(db, tenant_id, name="Acme")
    assert brand.name == "Acme"
    with pytest.raises(ConflictError):
        await CatalogService.create_brand(db, tenant_id, name="Acme")

    parent = await CatalogService.create_category(db, tenant_id, name="Shoes")
    child = await CatalogService.create_category(db, tenant_id, name="Running", parent_id=parent.id)
    assert child.parent_id == parent.id

    with pytest.raises(NotFoundError):
        await CatalogService.create_category(db, tenant_id, name="Orphan", parent_id=uuid.uuid4())
    await db.flush()
