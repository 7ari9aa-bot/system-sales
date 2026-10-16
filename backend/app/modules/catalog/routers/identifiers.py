"""Identifier endpoints for the catalog router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.core.errors import NotFoundError
from app.modules.catalog.service import CatalogService
from ._deps import (
    AddIdentifierRequest,
    TenantCtxDep,
    WriteCtx,
    _identifier_out,
    _variant_out,
)

router = APIRouter()


@router.post("/variants/{variant_id}/identifiers", status_code=201)
async def add_variant_identifier(variant_id: UUID, body: AddIdentifierRequest, ctx: WriteCtx):
    """§179: register a scan code on one sellable unit.

    (tenant, type, value) is unique, so the §179 resolver can promise exactly
    one variant per scan. POS (§189) resolves through this surface.
    """
    row = await CatalogService.add_identifier(
        ctx.session, ctx.tenant_id, variant_id, body.identifier_type, body.value
    )
    return _identifier_out(row)


@router.get("/variants/{variant_id}/identifiers")
async def list_variant_identifiers(variant_id: UUID, ctx: TenantCtxDep):
    rows = await CatalogService.list_identifiers(ctx.session, ctx.tenant_id, variant_id)
    return [_identifier_out(r) for r in rows]


@router.get("/identifiers/{identifier_type}/{value}")
async def resolve_identifier(identifier_type: str, value: str, ctx: TenantCtxDep):
    """§179: the only scan-entry point — one active variant or 404.

    Sellability of the variant's product stays the caller's check, exactly as
    with price_for.
    """
    variant = await CatalogService.resolve_identifier(
        ctx.session, ctx.tenant_id, identifier_type, value
    )
    if variant is None:
        raise NotFoundError("no active variant for identifier")
    return _variant_out(variant)
