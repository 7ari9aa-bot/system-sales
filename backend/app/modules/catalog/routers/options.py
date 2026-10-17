"""Product and variant option endpoints for the catalog router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.modules.catalog.service import CatalogService

from ._deps import (
    AddOptionRequest,
    AddOptionValueRequest,
    SetVariantOptionsRequest,
    TenantCtxDep,
    WriteCtx,
    _option_out,
    _variant_out,
)

router = APIRouter()


@router.post("/products/{product_id}/options", status_code=201)
async def add_product_option(product_id: UUID, body: AddOptionRequest, ctx: WriteCtx):
    """§179/P2: one option axis on a product ("size", "color", ...)."""
    option = await CatalogService.add_option(ctx.session, ctx.tenant_id, product_id, body.name)
    return _option_out(option, [])


@router.get("/products/{product_id}/options")
async def list_product_options(product_id: UUID, ctx: TenantCtxDep):
    pairs = await CatalogService.list_product_options(ctx.session, ctx.tenant_id, product_id)
    return [_option_out(o, vs) for o, vs in pairs]


@router.post("/options/{option_id}/values", status_code=201)
async def add_option_value(option_id: UUID, body: AddOptionValueRequest, ctx: WriteCtx):
    value = await CatalogService.add_option_value(ctx.session, ctx.tenant_id, option_id, body.value)
    return {"id": str(value.id), "option_id": str(value.option_id), "value": value.value}


@router.post("/variants/{variant_id}/options")
async def set_variant_options(variant_id: UUID, body: SetVariantOptionsRequest, ctx: WriteCtx):
    """§179/P2: replace-all option graph for one variant.

    Missing option/value rows are created; the JSONB read model and the
    relational graph are written by the same service call in the same
    transaction, so the storefront dict and the queryable graph agree.
    """
    variant = await CatalogService.set_variant_options(
        ctx.session, ctx.tenant_id, variant_id, body.option_values
    )
    return _variant_out(variant)
