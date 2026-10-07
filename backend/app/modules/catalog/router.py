"""CATALOG routes — thin REST layer over CatalogService."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.errors import NotFoundError, StorageUnavailableError, ValidationError
from app.core.middleware import MAX_BODY_BYTES
from app.core.storage import FetchedMedia, get_storage
from app.modules.catalog.external.csv_import import CSVImportService
from app.modules.catalog.service import CatalogService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.inventory.models import Warehouse

router = APIRouter(tags=["catalog"])

WriteCtx = Annotated[TenantContext, Depends(require_permission("products:write"))]
CustomerWriteCtx = Annotated[TenantContext, Depends(require_permission("customers:write"))]


def _variant_out(variant) -> dict:
    return {
        "id": str(variant.id),
        "sku": variant.sku,
        "title": variant.title,
        "option_values": variant.option_values or {},
        "price": str(variant.price),
        "compare_at_price": (
            str(variant.compare_at_price) if variant.compare_at_price is not None else None
        ),
        "is_active": variant.is_active,
    }


def _product_out(product, variants, images=(), *, tenant_id=None) -> dict:
    return {
        "id": str(product.id),
        "title": product.title,
        "slug": product.slug,
        "description": product.description,
        "status": product.status,
        "brand_id": str(product.brand_id) if product.brand_id else None,
        "category_id": str(product.category_id) if product.category_id else None,
        "attributes": product.attributes or {},
        "variants": [_variant_out(v) for v in variants],
        "images": [_image_out(image, tenant_id=tenant_id) for image in images],
    }


class CreateProductRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    description: str | None = None
    price: Decimal | None = None  # convenience: creates the default variant
    sku: str | None = None


class UpdateProductRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    brand_id: UUID | None = None
    category_id: UUID | None = None
    attributes: dict | None = None
    status: str | None = Field(default=None, pattern="^(draft|active|archived)$")


class AddVariantRequest(BaseModel):
    price: Decimal = Field(gt=0)
    sku: str | None = Field(default=None, max_length=63)
    title: str | None = Field(default=None, max_length=255)
    option_values: dict = Field(default_factory=dict)


class UpdateVariantRequest(BaseModel):
    sku: str | None = Field(default=None, max_length=63)
    title: str | None = Field(default=None, max_length=255)
    option_values: dict | None = None
    price: Decimal | None = Field(default=None, gt=0)
    compare_at_price: Decimal | None = Field(default=None, gt=0)
    is_active: bool | None = None


class SetPriceRequest(BaseModel):
    unit_price: Decimal = Field(gt=0)
    # Absent = the tenant's own currency (§47). A named one is validated against
    # it, so the default can never silently price a shop in another money.
    currency: str | None = Field(default=None, pattern="^[A-Za-z]{3}$")
    min_quantity: int = Field(default=1, ge=1)


class AddIdentifierRequest(BaseModel):
    """§179: one closed-vocabulary scan code on one sellable unit."""

    identifier_type: str = Field(pattern="^(gtin|ean|upc|barcode|qr_token|external)$")
    value: str = Field(min_length=1, max_length=127)


class AddOptionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=63)


class AddOptionValueRequest(BaseModel):
    value: str = Field(min_length=1, max_length=127)


class SetVariantOptionsRequest(BaseModel):
    """§179/P2: replace-all — one value per option axis on the variant."""

    option_values: dict[str, str]


class CreateBrandRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class CreateCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: UUID | None = None


class AddImageRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    alt: str | None = Field(default=None, max_length=255)
    # §179/P3: bind the shot to one sellable unit; absent = product-level.
    variant_id: UUID | None = None


def _image_out(image, *, tenant_id=None) -> dict:
    url = image.url
    if tenant_id is not None:
        url = get_storage().resolve_product_image_url(url, tenant_id=tenant_id)
    return {
        "id": str(image.id),
        "product_id": str(image.product_id),
        "variant_id": str(image.variant_id) if image.variant_id else None,
        "url": url,
        "alt": image.alt,
        "position": image.position,
    }


def _option_out(option, values) -> dict:
    return {
        "id": str(option.id),
        "name": option.name,
        "values": [{"id": str(v.id), "value": v.value} for v in values],
    }


def _identifier_out(row) -> dict:
    return {
        "id": str(row.id),
        "variant_id": str(row.variant_id),
        "identifier_type": row.type,
        "value": row.value,
    }


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
    # Validate the upload before persisting its bytes.
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


# ------------------------------------------------------- §161 CSV import ----
# The one intake for the §161 pipeline. It lives in the catalog module because
# that is where ``csv_import`` sits; it owns NO rules. Each row is handed to the
# same application service a human write uses — ``CustomerService.create_from_import``
# for a customer, ``CatalogService.upsert_from_external`` for a product — so the
# import can never clone what the API refuses (§161's whole point).
#
# The report is the contract: ``ImportReport.success`` decides the status, so a
# run with a refused or failed row is never a 200-green lie, and the per-row
# ``error_details`` come back so the merchant can fix the file. The body is a
# JSON string bounded by the SAME cap the edge middleware enforces
# (``MAX_BODY_BYTES``); a CSV larger than the request cap is a 413 before this
# route ever parses it, and one larger than the field cap is a 422.


class CsvImportRequest(BaseModel):
    csv: str = Field(min_length=1, max_length=MAX_BODY_BYTES)


def _report_out(report) -> dict:
    """The ImportReport as JSON — counts stay numbers, no money crosses here."""
    return {
        "total_rows": report.total_rows,
        "imported": report.imported,
        "skipped": report.skipped,
        "errors": report.errors,
        "conflicts": report.conflicts,
        "error_details": report.error_details,
        "success": report.success,
    }


def _report_status(report) -> int:
    """The verdict as an HTTP status: green only when nothing was refused.

    A conflict (an identity clash, a foreign currency) is 409; a generic per-row
    failure (an unparseable handle, a bad price) is 422. Both are non-200 so a
    client cannot read a partial run as a success.
    """
    if report.success:
        return 200
    if report.conflicts:
        return 409
    return 422


async def _audit_import(ctx: TenantContext, action: str, resource_type: str, report) -> None:
    """One audit row per bulk import, recording the run's verdict (§66).

    The writer is the shared ``app.core.audit`` one — auditing is a core
    capability, so this route costs no cross-module edge.
    """
    from app.core.audit import write_audit_row

    await write_audit_row(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        action=action,
        resource_type=resource_type,
        resource_id="csv_import",
        after={
            "total_rows": report.total_rows,
            "imported": report.imported,
            "errors": report.errors,
            "conflicts": report.conflicts,
            "success": report.success,
        },
    )


@router.post("/imports/customers")
async def import_customers_csv(ctx: CustomerWriteCtx, body: CsvImportRequest):
    """§161: import customers from a CSV through CustomerService, never the DB."""
    from app.modules.customers.service import CustomerService

    report = await CSVImportService.import_customers(
        ctx.session,
        ctx.tenant_id,
        raw_csv=body.csv,
        customer_service=CustomerService,
    )
    await _audit_import(ctx, "customer.csv_import", "customer", report)
    return JSONResponse(status_code=_report_status(report), content=_report_out(report))


@router.post("/imports/products")
async def import_products_csv(ctx: WriteCtx, body: CsvImportRequest):
    """§161: import products from a CSV through the catalog's external upsert."""
    report = await CSVImportService.import_products(
        ctx.session,
        ctx.tenant_id,
        raw_csv=body.csv,
    )
    await _audit_import(ctx, "catalog.csv_import", "product", report)
    return JSONResponse(status_code=_report_status(report), content=_report_out(report))
