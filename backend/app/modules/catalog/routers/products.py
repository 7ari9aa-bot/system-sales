"""Product endpoints for the catalog router."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

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
async def list_products(
    ctx: TenantCtxDep,
    limit: int = 100,
    offset: int = 0,
    season: str | None = None,
    material: str | None = None,
):
    products = await CatalogService.list_products(
        ctx.session, ctx.tenant_id, limit=limit, offset=offset, season=season, material=material
    )
    images_by_product = await CatalogService.list_images_for_products(
        ctx.session, ctx.tenant_id, [product.id for product in products]
    )
    variants_by_product = await CatalogService.list_variants_for_products(
        ctx.session, ctx.tenant_id, [product.id for product in products]
    )
    result = []
    for product in products:
        result.append(
            _product_out(
                product,
                variants_by_product.get(product.id, []),
                images_by_product.get(product.id, []),
                tenant_id=ctx.tenant_id,
            )
        )
    return result


# ---------------------------------------------------------------------------
# إدخال منتج كامل بطلب واحد.
#
# الشاشة كانت بتحفظ المنتج كسلسلة: طلب للمنتج، وطلب لكل تركيبة، وطلب لكل باركود
# مكتوب، وطلب لكل رصيد افتتاحي، وطلب للتفعيل. منتج بـ30 تركيبة = عشرات الطلبات
# المتتابعة، والبطء كان في الشبكة مش في قاعدة البيانات. هنا كل ده في معاملة واحدة:
# إما المنتج كامل (تركيبات + باركود + رصيد + تصنيف + تفعيل) أو ولا حاجة.
# ---------------------------------------------------------------------------
class IntakeVariant(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    price: Decimal = Field(gt=0)
    option_values: dict[str, str] = Field(default_factory=dict)
    barcode: str | None = Field(default=None, max_length=64)
    # 0 = بلا رصيد افتتاحي؛ أي رقم موجب بيتسجل كحركة إدخال في المخزن المطلوب
    stock: int = Field(default=0, ge=0)
    # اطلب من عدّاد المحل رقمًا (EAN-13) لو التركيبة مش معاها باركود
    auto_barcode: bool = False


class ProductIntakeRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category_id: UUID | None = None
    brand_id: UUID | None = None
    season: str | None = Field(default=None, max_length=40)
    material: str | None = Field(default=None, max_length=80)
    # الحالة الافتراضية "active": المنتج اللي اتسجل لازم يظهر في الكاشير فورًا
    status: str = "active"
    warehouse_id: UUID | None = None
    variants: list[IntakeVariant] = Field(min_length=1, max_length=500)


@router.post("/products/intake", status_code=201)
async def intake_product(body: ProductIntakeRequest, ctx: WriteCtx):
    """Create a sellable product with all its variants in ONE transaction."""
    from app.modules.catalog.apparel.barcode_service import BarcodeService
    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.service import InventoryService

    wanted_stock = sum(v.stock for v in body.variants)
    if wanted_stock and body.warehouse_id is None:
        raise ValidationError("رصيد افتتاحي بدون مخزن: لازم warehouse_id مع أي كمية أكبر من صفر")

    product = await CatalogService.create_product(
        ctx.session,
        ctx.tenant_id,
        title=body.title,
        slug=body.slug,
        description=body.description,
        season=body.season,
        material=body.material,
    )

    made = []
    for v in body.variants:
        variant = await CatalogService.add_variant(
            ctx.session,
            ctx.tenant_id,
            product.id,
            sku=v.sku,
            title=body.title,
            option_values=v.option_values or None,
            price=v.price,
        )
        code = (v.barcode or "").strip()
        if code:
            await CatalogService.add_identifier(
                ctx.session, ctx.tenant_id, variant.id, "barcode", code
            )
        if v.stock:
            await InventoryService.move(
                ctx.session,
                ctx.tenant_id,
                variant.id,
                body.warehouse_id,
                direction="in",
                quantity=v.stock,
                reason="adjustment",
                actor_user_id=ctx.user.id,
            )
        made.append((variant, code))

    # أرقام المحل (EAN-13 صحيح من العدّاد) للتركيبات اللي طلبت رقم تلقائي وبلا باركود
    auto_requested = [
        variant.id
        for (variant, code), wanted in zip(made, body.variants, strict=True)
        if not code and wanted.auto_barcode
    ]
    codes: dict[str, str] = {}
    if auto_requested:
        result = await BarcodeService.assign_missing(ctx.session, ctx.tenant_id, auto_requested)
        codes = {**result.already, **result.assigned}

    # التصنيف والتفعيل في نفس المعاملة، زي ما كان PATCH التفعيل بيعمل في الآخر
    classify: dict[str, object] = {"status": body.status}
    if body.category_id is not None:
        classify["category_id"] = body.category_id
    if body.brand_id is not None:
        classify["brand_id"] = body.brand_id
    product = await CatalogService.update_product(
        ctx.session, ctx.tenant_id, product.id, **classify
    )

    return {
        "id": str(product.id),
        "title": product.title,
        "slug": product.slug,
        "status": product.status,
        "variants": [
            {
                "id": str(variant.id),
                "sku": variant.sku,
                "option_values": variant.option_values or {},
                "price": str(variant.price),
                "barcode": codes.get(variant.id) or (code or None),
            }
            for (variant, code) in made
        ],
        "barcodes_assigned": len(codes),
    }


@router.post("/products", status_code=201)
async def create_product(ctx: WriteCtx, body: CreateProductRequest):
    product = await CatalogService.create_product(
        ctx.session,
        ctx.tenant_id,
        title=body.title,
        slug=body.slug,
        description=body.description,
        season=body.season,
        material=body.material,
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
        "season": product.season,
        "material": product.material,
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
