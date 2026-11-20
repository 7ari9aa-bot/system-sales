"""Apparel endpoints: build a garment's size x colour matrix and read it back as a grid."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.modules.catalog.apparel.service import ApparelMatrixService

from ._deps import TenantCtxDep, WriteCtx

router = APIRouter()


class GenerateMatrixRequest(BaseModel):
    sizes: list[str] = Field(min_length=1, max_length=40)
    colors: list[str] = Field(min_length=1, max_length=40)
    price: Decimal = Field(gt=0)
    sku_prefix: str = Field(min_length=1, max_length=30)
    # optional short code per colour, for names that would otherwise clash (two "Navy ...")
    color_codes: dict[str, str] | None = None


class MatrixCreatedOut(BaseModel):
    created: int
    skipped: int
    variant_ids: list[UUID]
    skipped_skus: list[str]


@router.post("/products/{product_id}/matrix", status_code=201, response_model=MatrixCreatedOut)
async def generate_matrix(product_id: UUID, body: GenerateMatrixRequest, ctx: WriteCtx):
    """Add every missing size x colour variant of a garment, all or none."""
    result = await ApparelMatrixService.generate(
        ctx.session,
        ctx.tenant_id,
        product_id,
        sizes=list(body.sizes),
        colors=list(body.colors),
        price=body.price,
        sku_prefix=body.sku_prefix,
        color_codes=body.color_codes,
    )
    return MatrixCreatedOut(
        created=len(result.created),
        skipped=len(result.skipped),
        variant_ids=[v.id for v in result.created],
        skipped_skus=result.skipped,
    )


@router.get("/products/{product_id}/matrix")
async def read_matrix(product_id: UUID, ctx: TenantCtxDep):
    """The garment as a grid: colours down, sizes across, sellable stock in each cell."""
    return await ApparelMatrixService.view(ctx.session, ctx.tenant_id, product_id)
