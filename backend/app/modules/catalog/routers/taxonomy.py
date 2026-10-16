"""Taxonomy, brands, categories, images, and warehouses endpoints for catalog router."""

from __future__ import annotations

import hashlib
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.core.errors import StorageUnavailableError, ValidationError
from app.core.storage import FetchedMedia, get_storage
from app.modules.catalog.service import CatalogService
from ._deps import (
    AddImageRequest,
    CreateBrandRequest,
    CreateCategoryRequest,
    TenantCtxDep,
    Warehouse,
    WriteCtx,
    _image_out,
)

router = APIRouter()


@router.post("/products/{product_id}/images", status_code=201)
async def add_product_image(product_id: UUID, body: AddImageRequest, ctx: WriteCtx):
    image = await CatalogService.add_image(
        ctx.session,
        ctx.tenant_id,
        product_id,
        url=body.url,
        alt=body.alt,
        variant_id=body.variant_id,
    )
    return _image_out(image, tenant_id=ctx.tenant_id)


@router.post("/products/{product_id}/images/upload", status_code=201)
async def upload_product_image(product_id: UUID, request: Request, ctx: WriteCtx):
    product = await CatalogService.get_product(ctx.session, ctx.tenant_id, product_id)
    storage = get_storage()
    if not storage.configured:
        raise StorageUnavailableError()

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    signatures = {
        "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
        "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/gif": lambda data: data.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": lambda data: (
            len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
        ),
        "image/bmp": lambda data: data.startswith(b"BM"),
    }
    signature = signatures.get(content_type)
    if signature is None:
        raise ValidationError("unsupported image type; use JPEG, PNG, GIF, WebP, or BMP")

    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 10 * 1024 * 1024:
            raise ValidationError("image exceeds the 10 MB upload limit")
    image_data = bytes(chunks)
    if not image_data or not signature(image_data):
        raise ValidationError("image content does not match its file type")

    fetched = FetchedMedia(
        data=image_data,
        content_type=content_type,
        checksum=hashlib.sha256(image_data).hexdigest(),
    )
    stored = await storage.store(
        fetched,
        prefix=f"product-images/{ctx.tenant_id}",
        original_url="",
    )
    if not stored.durable or not stored.storage_key:
        raise StorageUnavailableError()

    try:
        image = await CatalogService.add_image(
            ctx.session,
            ctx.tenant_id,
            product_id,
            url=f"s3://{stored.storage_key}",
            alt=product.title,
        )
    except Exception:
        await storage.delete_objects([stored.storage_key])
        raise
    return _image_out(image, tenant_id=ctx.tenant_id)


@router.get("/products/{product_id}/images")
async def list_product_images(ctx: TenantCtxDep, product_id: UUID):
    rows = await CatalogService.list_images(ctx.session, ctx.tenant_id, product_id)
    return [_image_out(i, tenant_id=ctx.tenant_id) for i in rows]


@router.post("/categories", status_code=201)
async def create_category(ctx: WriteCtx, body: CreateCategoryRequest):
    category = await CatalogService.create_category(
        ctx.session, ctx.tenant_id, name=body.name, parent_id=body.parent_id
    )
    return {
        "id": str(category.id),
        "name": category.name,
        "parent_id": str(category.parent_id) if category.parent_id else None,
    }


@router.get("/categories")
async def list_categories(ctx: TenantCtxDep, limit: int = 200, offset: int = 0):
    rows = await CatalogService.list_categories(
        ctx.session, ctx.tenant_id, limit=limit, offset=offset
    )
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "parent_id": str(c.parent_id) if c.parent_id else None,
        }
        for c in rows
    ]


@router.post("/brands", status_code=201)
async def create_brand(ctx: WriteCtx, body: CreateBrandRequest):
    brand = await CatalogService.create_brand(ctx.session, ctx.tenant_id, name=body.name)
    return {"id": str(brand.id), "name": brand.name}


@router.get("/brands")
async def list_brands(ctx: TenantCtxDep, limit: int = 200, offset: int = 0):
    rows = await CatalogService.list_brands(ctx.session, ctx.tenant_id, limit=limit, offset=offset)
    return [{"id": str(b.id), "name": b.name} for b in rows]


@router.get("/warehouses")
async def list_warehouses(ctx: TenantCtxDep, limit: int = 200, offset: int = 0):
    """Read-only warehouse list (the inventory module owns stock, not this)."""
    rows = (
        (
            await ctx.session.execute(
                select(Warehouse)
                .where(Warehouse.tenant_id == ctx.tenant_id)
                .order_by(Warehouse.name.asc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(w.id),
            "name": w.name,
            "code": w.code,
            "address": w.address,
            "is_active": w.is_active,
        }
        for w in rows
    ]
