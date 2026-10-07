"""§179 option graph + media variant binding — DB-backed (P2/P3).

Runs wherever a database URL is configured; conftest skips otherwise. The
wire guards live in ``test_catalog_options_spec.py``.

Discipline note: every read is an explicit ``SELECT`` returning plain values
(no expired-attribute access), and scalar comparisons bind ids while the
objects are still loaded.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.catalog.models import (
    ProductOption,
    ProductOptionValue,
    ProductVariant,
    ProductVariantOptionValue,
)
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, ValidationError


async def _product(db, tenant_ctx):
    return await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="تيشيرت", slug=f"t-{uuid.uuid4().hex[:10]}"
    )


async def _variant_graph(db, tenant_ctx, variant_id):
    """The variant's linked (option, value) pairs as a plain dict."""
    stmt = (
        select(ProductOption.name, ProductOptionValue.value)
        .select_from(ProductVariantOptionValue)
        .join(
            ProductOption,
            ProductOption.id == ProductVariantOptionValue.option_id,
        )
        .join(
            ProductOptionValue,
            ProductOptionValue.id == ProductVariantOptionValue.option_value_id,
        )
        .where(
            ProductVariantOptionValue.tenant_id == tenant_ctx.tenant_id,
            ProductVariantOptionValue.variant_id == variant_id,
        )
    )
    return dict((await db.execute(stmt)).all())


async def test_add_variant_populates_the_option_graph(db, tenant_ctx):
    product = await _product(db, tenant_ctx)
    variant = await CatalogService.add_variant(
        db,
        tenant_ctx.tenant_id,
        product.id,
        title="أسود / L",
        price="150.00",
        option_values={"size": "L", "color": "أسود"},
    )
    graph = await _variant_graph(db, tenant_ctx, variant.id)
    assert graph == {"size": "L", "color": "أسود"}
    pairs = await CatalogService.list_product_options(db, tenant_ctx.tenant_id, product.id)
    by_name = {o.name: sorted(v.value for v in vs) for o, vs in pairs}
    assert by_name == {"color": ["أسود"], "size": ["L"]}


async def test_set_variant_options_replaces_all_links(db, tenant_ctx):
    product = await _product(db, tenant_ctx)
    variant = await CatalogService.add_variant(
        db,
        tenant_ctx.tenant_id,
        product.id,
        title="أبيض / M",
        price="150.00",
        option_values={"size": "L"},
    )
    await CatalogService.set_variant_options(
        db, tenant_ctx.tenant_id, variant.id, {"size": "M", "color": "أبيض"}
    )
    graph = await _variant_graph(db, tenant_ctx, variant.id)
    assert graph == {"size": "M", "color": "أبيض"}
    assert variant.option_values == {"size": "M", "color": "أبيض"}


async def test_duplicate_option_name_on_product_conflicts(db, tenant_ctx):
    product = await _product(db, tenant_ctx)
    await CatalogService.add_option(db, tenant_ctx.tenant_id, product.id, "size")
    with pytest.raises(ConflictError):
        await CatalogService.add_option(db, tenant_ctx.tenant_id, product.id, " size ")


async def test_duplicate_option_value_conflicts(db, tenant_ctx):
    product = await _product(db, tenant_ctx)
    option = await CatalogService.add_option(db, tenant_ctx.tenant_id, product.id, "size")
    await CatalogService.add_option_value(db, tenant_ctx.tenant_id, option.id, "L")
    with pytest.raises(ConflictError):
        await CatalogService.add_option_value(db, tenant_ctx.tenant_id, option.id, " L ")


async def test_empty_option_parts_are_refused(db, tenant_ctx):
    product = await _product(db, tenant_ctx)
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="x", price="10.00"
    )
    with pytest.raises(ValidationError):
        await CatalogService.set_variant_options(db, tenant_ctx.tenant_id, variant.id, {"  ": "M"})


async def test_image_binds_to_variant_of_same_product_only(db, tenant_ctx):
    product_a = await _product(db, tenant_ctx)
    product_b = await _product(db, tenant_ctx)
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product_a.id, title="أسود", price="100.00"
    )
    with pytest.raises(ValidationError):
        await CatalogService.add_image(
            db,
            tenant_ctx.tenant_id,
            product_b.id,
            url="https://cdn.example.com/x.jpg",
            variant_id=variant.id,
        )
    image = await CatalogService.add_image(
        db,
        tenant_ctx.tenant_id,
        product_a.id,
        url="https://cdn.example.com/x.jpg",
        variant_id=variant.id,
    )
    bound = (
        await db.execute(select(ProductVariant.id).where(ProductVariant.id == image.variant_id))
    ).scalar_one()
    assert bound == variant.id
