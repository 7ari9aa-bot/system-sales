"""عدد صور الصنف رقم واحد في كل المسارات: الرفع اليدوي والـZIP وورقة الصور.

الفورم اليدوي كان بيسمح 4 صور ومسار الـZIP 10، فالحد كان بيتغير حسب الباب اللي دخلت منه.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.applications.apparel.modules.catalog.limits import MAX_IMAGES_PER_SKU
from app.applications.apparel.modules.catalog.models import Product, ProductVariant
from app.applications.apparel.modules.catalog.service import CatalogService
from app.modules.errors import ValidationError
from app.platform.imports.image_zip import MAX_IMAGES_PER_SKU as ZIP_LIMIT
from app.platform.imports.validation import MAX_IMAGES_PER_SKU as SHEET_LIMIT

pytestmark = pytest.mark.asyncio


async def test_the_zip_and_the_sheet_use_the_same_number_as_the_catalog(db, tenant_ctx):
    assert ZIP_LIMIT == SHEET_LIMIT == MAX_IMAGES_PER_SKU


async def test_a_gallery_stops_at_the_shared_limit(db, tenant_ctx):
    product = Product(
        tenant_id=tenant_ctx.tenant_id,
        title="تيشيرت بصور",
        slug=f"img-{uuid.uuid4().hex[:10]}",
        status="active",
    )
    db.add(product)
    await db.flush()
    variant = ProductVariant(
        tenant_id=tenant_ctx.tenant_id,
        product_id=product.id,
        sku=f"IMG-{uuid.uuid4().hex[:8]}",
        price="250.00",
        is_active=True,
    )
    db.add(variant)
    await db.flush()

    for i in range(MAX_IMAGES_PER_SKU):
        await CatalogService.add_image(
            db,
            tenant_ctx.tenant_id,
            product.id,
            url=f"s3://product-images/{product.id}/{i}.jpg",
            variant_id=variant.id,
        )
    with pytest.raises(ValidationError):
        await CatalogService.add_image(
            db,
            tenant_ctx.tenant_id,
            product.id,
            url=f"s3://product-images/{product.id}/extra.jpg",
            variant_id=variant.id,
        )

    from app.applications.apparel.modules.catalog.models import ProductImage

    count = (
        await db.execute(
            select(ProductImage).where(
                ProductImage.tenant_id == tenant_ctx.tenant_id,
                ProductImage.product_id == product.id,
            )
        )
    ).all()
    assert len(count) == MAX_IMAGES_PER_SKU
