"""Variant endpoints for the catalog router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.core.errors import ValidationError
from app.modules.catalog.service import CatalogService
from ._deps import (
    AddVariantRequest,
    SetPriceRequest,
    TenantCtxDep,
    UpdateVariantRequest,
    WriteCtx,
    _variant_out,
)

router = APIRouter()


@router.get("/products/{product_id}/variants")
async def list_product_variants(ctx: TenantCtxDep, product_id: UUID):
    await CatalogService.get_product(ctx.session, ctx.tenant_id, product_id)
    variants = await CatalogService.list_variants(ctx.session, ctx.tenant_id, product_id)
    return [_variant_out(v) for v in variants]


@router.post("/products/{product_id}/variants", status_code=201)
async def add_product_variant(product_id: UUID, body: AddVariantRequest, ctx: WriteCtx):
    variant = await CatalogService.add_variant(
        ctx.session,
        ctx.tenant_id,
        product_id,
        sku=body.sku,
        title=body.title,
        option_values=body.option_values,
        price=body.price,
    )
    return _variant_out(variant)


@router.post("/variants/{variant_id}/prices", status_code=201)
async def set_variant_price(variant_id: UUID, body: SetPriceRequest, ctx: WriteCtx):
    """One quantity tier for one variant (`PATCH /variants/{id}` is the base price).

    The tier rows are what a wholesale price list means: same variant, different
    price from N units up, in a named currency.
    """
    try:
        row = await CatalogService.set_variant_price(
            ctx.session,
            ctx.tenant_id,
            variant_id,
            body.unit_price,
            currency=body.currency,
            min_quantity=body.min_quantity,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return {
        "id": str(row.id),
        "variant_id": str(row.variant_id),
        "currency": row.currency,
        "unit_price": str(row.unit_price),
        "min_quantity": row.min_quantity,
    }


@router.patch("/variants/{variant_id}")
async def update_variant(variant_id: UUID, body: UpdateVariantRequest, ctx: WriteCtx):
    fields = body.model_dump(exclude_unset=True)
    variant = await CatalogService.update_variant(ctx.session, ctx.tenant_id, variant_id, **fields)
    return _variant_out(variant)
