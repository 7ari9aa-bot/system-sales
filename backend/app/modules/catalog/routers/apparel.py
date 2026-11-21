"""Apparel endpoints: build a garment's size x colour matrix and read it back as a grid."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.modules.catalog.apparel.barcode_service import BarcodeService
from app.modules.catalog.apparel.label import SIZES, label_svg
from app.modules.catalog.apparel.service import ApparelMatrixService
from app.modules.errors import ConflictError, ValidationError

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


class AssignBarcodesRequest(BaseModel):
    # empty or omitted means every variant of the garment
    variant_ids: list[UUID] | None = Field(default=None, max_length=500)


class BarcodesOut(BaseModel):
    assigned: int
    already_had_one: int
    codes: dict[UUID, str]


@router.post("/products/{product_id}/barcodes", status_code=201, response_model=BarcodesOut)
async def assign_barcodes(product_id: UUID, body: AssignBarcodesRequest, ctx: WriteCtx):
    """Give every variant of the garment that has no barcode one of the shop's own."""
    rows = await BarcodeService.label_rows(
        ctx.session, ctx.tenant_id, product_id, only=body.variant_ids or None
    )
    if not rows:
        raise ValidationError("this garment has no variants to label")
    result = await BarcodeService.assign_missing(
        ctx.session, ctx.tenant_id, [r["variant_id"] for r in rows]
    )
    return BarcodesOut(
        assigned=len(result.assigned),
        already_had_one=len(result.already),
        codes={**result.already, **result.assigned},
    )


@router.get("/products/{product_id}/labels", response_class=HTMLResponse)
async def print_labels(
    product_id: UUID,
    ctx: TenantCtxDep,
    size: Annotated[str, Query()] = "medium",
    copies: Annotated[int, Query(ge=1, le=20)] = 1,
    variant_id: Annotated[list[UUID] | None, Query()] = None,
):
    """A print-ready page with one label per variant (times ``copies``), each at its real size.

    Labelling is a separate, write-protected step (POST .../barcodes): a variant without a code
    makes this refuse rather than print a label nobody can scan.
    """
    rows = await BarcodeService.label_rows(ctx.session, ctx.tenant_id, product_id, only=variant_id)
    if not rows:
        raise ValidationError("this garment has no variants to print")
    unlabelled = [r for r in rows if r["code"] is None]
    if unlabelled:
        raise ConflictError(
            f"{len(unlabelled)} variant(s) have no barcode yet: assign barcodes first"
        )
    width, height = SIZES.get(size, (None, None))
    if width is None:
        raise ValidationError(f"label size must be one of {sorted(SIZES)}")
    one_each = [
        label_svg(
            code=r["code"],
            title=r["title"],
            variant_text=r["variant_text"],
            price=r["price"],
            size=size,
        )
        for r in rows
    ]
    labels = "".join(f'<div class="l">{svg}</div>' for svg in one_each for _ in range(copies))
    page = (
        '<!doctype html><html dir="rtl" lang="ar"><meta charset="utf-8"><title>ملصقات</title>'
        f"<style>@page{{size:{width}mm {height}mm;margin:0}}body{{margin:0}}"
        f".l{{width:{width}mm;height:{height}mm;page-break-after:always;overflow:hidden}}"
        f".l svg{{display:block}}</style>{labels}"
    )
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})
