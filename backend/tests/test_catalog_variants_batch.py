"""Listing products must not cost one variant query per product.

`GET /products?limit=500` loaded each product's variants in its own query: 501 round trips for one
screen, which is a second or more against a database that is not on the same machine. The batch
loader answers for the whole page in one query and must return exactly what the per-product
one does.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import event

from app.modules.catalog.service import CatalogService


async def _product_with_variants(db, tenant_id, n_variants):
    product = await CatalogService.create_product(
        db, tenant_id, title="منتج", slug=f"p-{uuid.uuid4().hex[:10]}"
    )
    for i in range(n_variants):
        variant = await CatalogService.add_variant(
            db, tenant_id, product.id, sku=f"S-{uuid.uuid4().hex[:8]}", price=f"{10 + i}.00"
        )
        # One transaction shares one `now()`; in production each variant is its own request, so
        # give them the distinct timestamps that make "oldest first" a defined order.
        variant.created_at = variant.created_at + timedelta(seconds=i)
    await db.flush()
    return product


@pytest.mark.asyncio
async def test_the_batch_returns_what_the_per_product_loader_returns(db, tenant_ctx):
    tid = tenant_ctx.tenant_id
    products = [await _product_with_variants(db, tid, n) for n in (3, 1, 0, 2)]

    batch = await CatalogService.list_variants_for_products(db, tid, [p.id for p in products])

    for product in products:
        single = await CatalogService.list_variants(db, tid, product.id)
        assert [v.id for v in batch.get(product.id, [])] == [v.id for v in single]
    assert products[2].id not in batch  # a product with no variants maps to nothing


@pytest.mark.asyncio
async def test_an_empty_page_asks_nothing(db, tenant_ctx):
    assert await CatalogService.list_variants_for_products(db, tenant_ctx.tenant_id, []) == {}


@pytest.mark.asyncio
async def test_a_variant_of_another_tenant_never_appears(db, tenant_ctx):
    tid = tenant_ctx.tenant_id
    product = await _product_with_variants(db, tid, 2)
    other_tenant = uuid.uuid4()
    assert await CatalogService.list_variants_for_products(db, other_tenant, [product.id]) == {}


@pytest.mark.asyncio
async def test_the_query_count_does_not_grow_with_the_number_of_products(db, tenant_ctx):
    tid = tenant_ctx.tenant_id
    products = [await _product_with_variants(db, tid, 1) for _ in range(12)]
    statements: list[str] = []

    def count(_conn, _cursor, statement, *_a):
        if "product_variants" in statement:
            statements.append(statement)

    sync_engine = (
        db.get_bind().sync_engine if hasattr(db.get_bind(), "sync_engine") else db.get_bind()
    )
    event.listen(sync_engine, "before_cursor_execute", count)
    try:
        await CatalogService.list_variants_for_products(db, tid, [p.id for p in products])
    finally:
        event.remove(sync_engine, "before_cursor_execute", count)

    assert len(statements) == 1, f"{len(statements)} variant queries for 12 products"


@pytest.mark.asyncio
async def test_the_products_route_issues_one_variant_query_for_the_whole_page(db, tenant_ctx):
    from app.modules.catalog.routers.products import list_products

    tid = tenant_ctx.tenant_id
    for _ in range(15):
        await _product_with_variants(db, tid, 2)
    seen: list[str] = []

    def spy(_conn, _cursor, statement, *_a):
        if "FROM product_variants" in statement:
            seen.append(statement)

    class Ctx:  # the two attributes the route reads from its tenant context
        session = db
        tenant_id = tid

    bind = db.get_bind()
    engine = getattr(bind, "sync_engine", bind)
    event.listen(engine, "before_cursor_execute", spy)
    try:
        out = await list_products(Ctx(), limit=100, offset=0)
    finally:
        event.remove(engine, "before_cursor_execute", spy)

    assert len(out) >= 15
    assert len(seen) == 1, f"{len(seen)} variant queries for {len(out)} products"
