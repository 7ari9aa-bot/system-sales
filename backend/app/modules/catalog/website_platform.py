"""Website Platform catalog exposure (§208 External SDK — receive side).

The external Website Platform (D:\website builder) reads this tenant's
published catalog to render ProductGrid sections. Access is key-based, NOT
user-JWT: each tenant has a per-tenant key stored in settings
(`WEBSITE_PLATFORM_TENANT_KEYS` = JSON of tenant_id → key). The platform's
`sales-os` provider adapter calls this endpoint with `X-WP-Key`.

Golden rule: this is a READ-ONLY projection — the catalog stays the single
source of truth; the website never owns product data.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import bind_tenant
from app.core.storage import get_storage
from app.modules.catalog.models import Product, ProductImage, ProductVariant
from app.modules.identity.deps import get_db

router = APIRouter()


def _resolve_tenant_key(x_wp_key: str = Header(...)) -> UUID:
    """Resolve the tenant from the per-tenant platform key."""
    mapping = get_settings().website_platform_tenant_keys or {}
    tenant_id = mapping.get(x_wp_key)
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid website-platform key")
    try:
        return UUID(tenant_id)
    except ValueError as exc:  # misconfigured mapping — fail loud, not silent
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="tenant id in mapping is not a uuid") from exc


@router.get("/website-platform/catalog/products")
async def website_platform_products(
    key_tenant: UUID = Depends(_resolve_tenant_key),
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
) -> dict:
    """Sellable catalog projection for the website platform (read-only).

        Filters on the catalog's OWN vocabulary — ``active`` is the state a
        product must hold to sell (M4), so it is the state the storefront can
        render. A ``published`` literal does not exist in the domain.
        """
    await bind_tenant(db, key_tenant)
    capped = max(1, min(limit, 500))

    product_rows = (
        (await db.execute(
            select(Product).where(Product.status == "active").order_by(Product.created_at.desc()).limit(capped)
        ))
        .scalars()
        .all()
    )
    if not product_rows:
        return {"products": []}

    product_ids = [p.id for p in product_rows]
    variant_rows = (
        (await db.execute(
            select(ProductVariant)
            .where(ProductVariant.product_id.in_(product_ids), ProductVariant.is_active.is_(True))
            .order_by(ProductVariant.price.asc())
        ))
        .scalars()
        .all()
    )
    image_rows = (
        (await db.execute(
            select(ProductImage)
            .where(ProductImage.product_id.in_(product_ids))
            .order_by(ProductImage.position.asc())
        ))
        .scalars()
        .all()
    )

    first_variant: dict[UUID, ProductVariant] = {}
    for v in variant_rows:
        first_variant.setdefault(v.product_id, v)
    first_image: dict[UUID, ProductImage] = {}
    for img in image_rows:
        first_image.setdefault(img.product_id, img)

    def _money(value: Decimal | None) -> dict:
        return {"amount": f"{value:.2f}" if value is not None else "0.00", "currency": "EGP"}

    products = []
    for p in product_rows:
        variant = first_variant.get(p.id)
        image = first_image.get(p.id)
        products.append(
            {
                "id": str(p.id),
                "slug": p.slug,
                "name": p.title,
                "description": p.description,
                "status": p.status,
                "price": _money(variant.price if variant else None),
                "compareAtPrice": (
                    {"amount": f"{variant.compare_at_price:.2f}", "currency": "EGP"}
                    if variant and variant.compare_at_price is not None
                    else None
                ),
                "image": (
                    get_storage().resolve_product_image_url(
                        image.url, tenant_id=key_tenant
                    )
                    if image else None
                ),
                "availability": {"status": "available" if variant is not None else "unavailable"},
            }
        )
    return {"products": products}
