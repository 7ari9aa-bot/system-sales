"""Shared dependencies, schemas, and serialization helpers for catalog routers."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel, Field

from app.core.middleware import MAX_BODY_BYTES
from app.core.storage import get_storage
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.inventory.models import Warehouse

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
    variant_id: UUID | None = None


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
    """The verdict as an HTTP status: green only when nothing was refused."""
    if report.success:
        return 200
    if report.conflicts:
        return 409
    return 422


async def _audit_import(ctx: TenantContext, action: str, resource_type: str, report) -> None:
    """One audit row per bulk import, recording the run's verdict (§66)."""
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
