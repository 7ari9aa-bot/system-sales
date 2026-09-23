"""The channel sync path end to end: Shopify payload → a real catalog row.

This is the half the gap register could not have caught: the adapter's call
target existed nowhere, so a sync reported nothing while writing nothing. These
run the production ``CatalogService.upsert_from_external`` against the
transactional test schema, with Shopify itself behind ``httpx.MockTransport``
(no network, no credentials).

DB-backed: they SKIP locally without ``DATABASE_URL_APP_ADMIN`` and run in CI.
The pure mirror of these rules — refusals, currency resolution, report
accounting — is in ``tests/test_shopify_adapter.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.external.source_of_truth import SourceOfTruthService
from app.modules.catalog.models import Product, ProductVariant
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError
from tests.test_shopify_adapter import _adapter, _product


async def _external_products_channel(
    db: AsyncSession, tenant_id: uuid.UUID
) -> None:
    """§161: nothing syncs until the tenant says the store owns its products."""
    await SourceOfTruthService.upsert_policy(
        db,
        tenant_id,
        provider="shopify",
        entity_type="product",
        source_mode="external",
        sync_direction="inbound",
    )
    await db.flush()


async def _reset_version_gate(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Clear the incremental marker: this run is a full re-sync, not a poll."""
    policy = await SourceOfTruthService.get_policy(
        db, tenant_id, provider="shopify", entity_type="product"
    )
    policy.external_version = None
    await db.flush()


async def _rows(db: AsyncSession, tenant_id: uuid.UUID) -> list[Product]:
    """Every product this tenant has — the sync may not leave a second one."""
    return list(
        (
            await db.execute(select(Product).where(Product.tenant_id == tenant_id))
        ).scalars().all()
    )


async def test_sync_products_writes_a_real_product_and_variant(
    db: AsyncSession, tenant_ctx
) -> None:
    tenant_id = tenant_ctx.tenant_id
    await _external_products_channel(db, tenant_id)
    adapter, _seen = _adapter(products=[_product(price="19.99")], shop_currency="EGP")

    report = await adapter.sync_products(db, tenant_id)

    assert report["synced"] == 1 and report["errors"] == 0 and report["conflicts"] == 0
    products = await _rows(db, tenant_id)
    assert len(products) == 1
    product = products[0]
    assert product.slug == "koshari-bowl"
    assert product.status == "active"
    # provenance, so the next sync recognises its own row instead of cloning it
    assert product.attributes["_source"] == "shopify"
    assert product.attributes["_external_id"] == "111"

    variants = await CatalogService.list_variants(db, tenant_id, product.id)
    assert len(variants) == 1
    assert variants[0].sku == "KB-111"
    assert variants[0].price == Decimal("19.99")


async def test_resync_updates_the_row_it_already_owns(
    db: AsyncSession, tenant_ctx
) -> None:
    tenant_id = tenant_ctx.tenant_id
    await _external_products_channel(db, tenant_id)
    first, _seen = _adapter(products=[_product(price="19.99")], shop_currency="EGP")
    await first.sync_products(db, tenant_id)

    await _reset_version_gate(db, tenant_id)
    renamed = _product(price="17.50")
    renamed["title"] = "Koshari Bowl, large"
    second, _seen2 = _adapter(products=[renamed], shop_currency="EGP")
    report = await second.sync_products(db, tenant_id)

    assert report["synced"] == 1 and report["errors"] == 0
    products = await _rows(db, tenant_id)
    assert len(products) == 1, "a re-sync must update, not duplicate"
    assert products[0].title == "Koshari Bowl, large"
    variants = list(
        (
            await db.execute(
                select(ProductVariant).where(ProductVariant.tenant_id == tenant_id)
            )
        ).scalars().all()
    )
    assert len(variants) == 1
    assert variants[0].price == Decimal("17.50")


async def test_a_foreign_currency_price_lands_nothing(
    db: AsyncSession, tenant_ctx
) -> None:
    """Refusal at the boundary: a tenant's money is one currency (§47)."""
    tenant_id = tenant_ctx.tenant_id
    await _external_products_channel(db, tenant_id)
    adapter, _seen = _adapter(
        products=[_product(currency="USD")], shop_currency="USD"
    )

    report = await adapter.sync_products(db, tenant_id)

    assert report["conflicts"] == 1 and report["synced"] == 0
    assert await _rows(db, tenant_id) == []


async def test_upsert_from_external_refuses_a_foreign_currency(
    db: AsyncSession, tenant_ctx
) -> None:
    """The owning service — not only the adapter — gates the currency."""
    tenant_id = tenant_ctx.tenant_id

    with pytest.raises(ConflictError):
        await CatalogService.upsert_from_external(
            db,
            tenant_id,
            external_ref="111",
            data={"title": "Koshari Bowl", "slug": "koshari-bowl"},
            source="shopify",
            currency="USD",
        )
    await db.flush()

    counted = (
        await db.execute(
            select(func.count()).select_from(Product).where(
                Product.tenant_id == tenant_id
            )
        )
    ).scalar_one()
    assert counted == 0


async def test_upsert_from_external_writes_in_the_tenants_currency(
    db: AsyncSession, tenant_ctx
) -> None:
    """With no currency argument the tenant's own row answers."""
    tenant_id = tenant_ctx.tenant_id

    product = await CatalogService.upsert_from_external(
        db,
        tenant_id,
        external_ref="111",
        data={
            "title": "Koshari Bowl",
            "slug": "koshari-bowl",
            "variants": [{"title": "Default", "price": "25.00", "sku": "KB-111"}],
        },
        source="shopify",
    )
    await db.flush()

    variants = await CatalogService.list_variants(db, tenant_id, product.id)
    assert variants[0].price == Decimal("25.00")
