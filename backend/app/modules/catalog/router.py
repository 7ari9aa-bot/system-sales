"""CATALOG routes — thin REST layer over CatalogService."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.modules.catalog.service import CatalogService
from app.modules.identity.deps import TenantCtxDep

router = APIRouter(tags=["catalog"])


class CreateProductRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    description: str | None = None
    price: Decimal | None = None  # convenience: creates the default variant
    sku: str | None = None


@router.get("/products")
async def list_products(ctx: TenantCtxDep, limit: int = 100, offset: int = 0):
    products = await CatalogService.list_products(
        ctx.session, ctx.tenant_id, limit=limit, offset=offset
    )
    result = []
    for product in products:
        variants = await CatalogService.list_variants(ctx.session, ctx.tenant_id, product.id)
        result.append(
            {
                "id": str(product.id),
                "title": product.title,
                "slug": product.slug,
                "status": product.status,
                "variants": [
                    {
                        "id": str(v.id),
                        "sku": v.sku,
                        "title": v.title,
                        "price": str(v.price),
                    }
                    for v in variants
                ],
            }
        )
    return result


@router.post("/products", status_code=201)
async def create_product(ctx: TenantCtxDep, body: CreateProductRequest):
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
