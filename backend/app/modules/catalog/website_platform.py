r"""Website Platform catalog exposure (§208 External SDK — receive side).

The external Website Platform (D:\website builder) reads this tenant's
published catalog to render ProductGrid sections. Access is key-based, NOT
user-JWT: each tenant has a per-tenant key stored in settings
(`WEBSITE_PLATFORM_TENANT_KEYS` = JSON of tenant_id → key). The platform's
`sales-os` provider adapter calls this endpoint with `X-WP-Key`.

Golden rule: this is a READ-ONLY projection — the catalog stays the single
source of truth; the website never owns product data.

Fields added for the website's own checkout (all ADDITIVE, nothing existing changed):

* ``stock`` — units a customer could buy now: sum over warehouses of
  ``max(on_hand - reserved, 0)``, over the product's active variants. ``null``
  means "no inventory record exists", NOT zero: a product nobody has counted yet
  must not be advertised as sold out.
* ``sizes`` / ``colors`` — the distinct ``size`` / ``color`` values of the active
  variants' ``option_values`` (the catalog's own option vocabulary).
* ``category`` — the category name, or ``null``.

Stock is read with one grouped SQL statement instead of importing the inventory
module: catalog -> inventory at module scope would add a cross-module edge (and
risk a cycle), and ``tests/test_module_boundaries.py`` is a ratchet. Same approach
as ``inventory.stock_view``, which also reads across tables with ``text()``.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import bind_tenant
from app.core.storage import get_storage
from app.modules.catalog.models import Category, Product, ProductImage, ProductVariant
from app.modules.identity.deps import get_db

router = APIRouter()

# Option names the catalog may use for a size / a colour (English or Arabic labels).
_SIZE_KEYS = ("size", "مقاس", "المقاس")
_COLOR_KEYS = ("color", "colour", "لون", "اللون")


def _resolve_tenant_key(x_wp_key: str = Header(...)) -> UUID:
    """Resolve the tenant from the per-tenant platform key."""
    mapping = get_settings().website_platform_tenant_keys or {}
    tenant_id = mapping.get(x_wp_key)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid website-platform key"
        )
    try:
        return UUID(tenant_id)
    except ValueError as exc:  # misconfigured mapping — fail loud, not silent
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="tenant id in mapping is not a uuid",
        ) from exc


def _distinct_option(variants: list[ProductVariant], *names: str) -> list[str]:
    """Distinct, trimmed values of one option across active variants, in first-seen order."""
    seen: dict[str, None] = {}
    for v in variants:
        values = v.option_values if isinstance(v.option_values, dict) else {}
        for name in names:
            raw = values.get(name)
            if isinstance(raw, str) and raw.strip():
                seen.setdefault(raw.strip()[:40], None)
                break
    return list(seen)[:30]


async def _available_stock(db: AsyncSession, product_ids: list[UUID]) -> dict[UUID, int]:
    """Sellable units per product.

    Sum over warehouses and ACTIVE variants of ``max(on_hand - reserved, 0)``.

    A product with no balance row at all is simply absent from the result (the caller maps that to
    ``null`` = unknown), which is different from a product whose balances add up to zero (sold out).
    Tenant isolation is the session's RLS binding (``bind_tenant``), not a filter written here.
    """
    rows = await db.execute(
        text(
            "SELECT v.product_id AS product_id, "
            "COALESCE(SUM(GREATEST(b.on_hand - b.reserved, 0)), 0) AS available "
            "FROM inventory_balances b "
            "JOIN product_variants v ON v.id = b.variant_id AND v.is_active "
            "WHERE v.product_id = ANY(:ids) "
            "GROUP BY v.product_id"
        ),
        {"ids": product_ids},
    )
    return {r.product_id: int(r.available) for r in rows}


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
        (
            await db.execute(
                select(Product)
                .where(Product.status == "active")
                .order_by(Product.created_at.desc())
                .limit(capped)
            )
        )
        .scalars()
        .all()
    )
    if not product_rows:
        return {"products": []}

    product_ids = [p.id for p in product_rows]
    variant_rows = (
        (
            await db.execute(
                select(ProductVariant)
                .where(
                    ProductVariant.product_id.in_(product_ids), ProductVariant.is_active.is_(True)
                )
                .order_by(ProductVariant.price.asc())
            )
        )
        .scalars()
        .all()
    )
    image_rows = (
        (
            await db.execute(
                select(ProductImage)
                .where(ProductImage.product_id.in_(product_ids))
                .order_by(ProductImage.position.asc())
            )
        )
        .scalars()
        .all()
    )

    category_ids = {p.category_id for p in product_rows if p.category_id}
    category_names: dict[UUID, str] = {}
    if category_ids:
        category_names = {
            c.id: c.name
            for c in (await db.execute(select(Category).where(Category.id.in_(category_ids))))
            .scalars()
            .all()
        }
    available = await _available_stock(db, product_ids)

    first_variant: dict[UUID, ProductVariant] = {}
    variants_by_product: dict[UUID, list[ProductVariant]] = {}
    for v in variant_rows:
        first_variant.setdefault(v.product_id, v)
        variants_by_product.setdefault(v.product_id, []).append(v)
    first_image: dict[UUID, ProductImage] = {}
    for img in image_rows:
        first_image.setdefault(img.product_id, img)

    def _money(value: Decimal | None) -> dict:
        return {"amount": f"{value:.2f}" if value is not None else "0.00", "currency": "EGP"}

    products = []
    for p in product_rows:
        variant = first_variant.get(p.id)
        image = first_image.get(p.id)
        variants = variants_by_product.get(p.id, [])
        # The website prices a product with ONE price. If the variants are priced differently,
        # offering sizes would let a customer see the cheapest size's price and pay for another,
        # so sizes/colors are only exposed when every active variant costs the same;
        # `priceVaries` says why they are empty.
        price_varies = len({v.price for v in variants}) > 1
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
                    get_storage().resolve_product_image_url(image.url, tenant_id=key_tenant)
                    if image
                    else None
                ),
                "availability": {"status": "available" if variant is not None else "unavailable"},
                "stock": available.get(p.id),
                "sizes": [] if price_varies else _distinct_option(variants, *_SIZE_KEYS),
                "colors": [] if price_varies else _distinct_option(variants, *_COLOR_KEYS),
                "priceVaries": price_varies,
                "category": category_names.get(p.category_id) if p.category_id else None,
            }
        )
    return {"products": products}
