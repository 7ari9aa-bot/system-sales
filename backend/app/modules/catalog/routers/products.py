"""Product endpoints for the catalog router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.core.errors import ValidationError
from app.modules.catalog.service import CatalogService
from ._deps import (
    CreateProductRequest,
    TenantCtxDep,
    UpdateProductRequest,
    WriteCtx,
    _product_out,
)

router = APIRouter()


@router.get("/products")
async def list_products(ctx: TenantCtxDep, limit: int = 100, offset: int = 0):
    products = await CatalogService.list_products(
        ctx.session, ctx.tenant_id, limit=limit, offset=offset
    )
    images_by_product = await CatalogService.list_images_for_products(
        ctx.session, ctx.tenant_id, [product.id for product in products]
    )
    result = []
    for product in products:
        variants = await CatalogService.list_variants(ctx.session, ctx.tenant_id, product.id)
        result.append(
            _product_out(
                product,
                variants,
                images_by_product.get(product.id, []),
                tenant_id=ctx.tenant_id,
            )
        )
    return result


@router.post("/products", status_code=201)
async def create_product(ctx: WriteCtx, body: CreateProductRequest):
    product = await CatalogService.create_product(
        ctx.session,
        ctx.tenant_id,
        title=body.title,
        slug=body.slug,
        description=body.description,
    )
    variant = None
    if body.price is not None:
        variant = await CatalogService.add_variant(
            ctx.session,
            ctx.tenant_id,
            product.id,
            sku=body.sku,
            title=body.title,
            price=body.price,
        )
    return {
        "id": str(product.id),
        "title": product.title,
        "slug": product.slug,
        "status": product.status,
        "variant_id": str(variant.id) if variant else None,
    }


@router.get("/products/{product_id}")
async def get_product(ctx: TenantCtxDep, product_id: UUID):
    product = await CatalogService.get_product(ctx.session, ctx.tenant_id, product_id)
    variants = await CatalogService.list_variants(ctx.session, ctx.tenant_id, product_id)
    images = await CatalogService.list_images(ctx.session, ctx.tenant_id, product_id)
    return _product_out(product, variants, images, tenant_id=ctx.tenant_id)


@router.patch("/products/{product_id}")
async def update_product(product_id: UUID, body: UpdateProductRequest, ctx: WriteCtx):
    fields = body.model_dump(exclude_unset=True)
    try:
        product = await CatalogService.update_product(
            ctx.session, ctx.tenant_id, product_id, **fields
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    variants = await CatalogService.list_variants(ctx.session, ctx.tenant_id, product_id)
    images = await CatalogService.list_images(ctx.session, ctx.tenant_id, product_id)
    return _product_out(product, variants, images, tenant_id=ctx.tenant_id)


@router.post("/products/{product_id}/archive")
async def archive_product(product_id: UUID, ctx: WriteCtx):
    product = await CatalogService.archive_product(ctx.session, ctx.tenant_id, product_id)
    return {"id": str(product.id), "status": product.status}
