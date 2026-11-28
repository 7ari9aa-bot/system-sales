"""Product CRUD and external store synchronization services."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sql import like_pattern
from app.applications.apparel.modules.catalog.limits import MATERIAL_MAX_LENGTH, SEASON_MAX_LENGTH
from app.applications.apparel.modules.catalog.models import Product, ProductVariant
from app.applications.apparel.modules.catalog.services._common import (
    _PRODUCT_STATUSES,
    _positive_decimal,
)
from app.modules.errors import ConflictError, NotFoundError, ValidationError


def _clean_season(raw: str | None) -> str | None:
    """The season a caller means: spaces trimmed, blank means none, too long is refused.

    Refused rather than cut: a season silently shortened to 40 characters would no longer match
    the name the owner typed.
    """
    if raw is None:
        return None
    cleaned = str(raw).strip()
    if not cleaned:
        return None
    if len(cleaned) > SEASON_MAX_LENGTH:
        raise ValueError(f"season must be at most {SEASON_MAX_LENGTH} characters")
    return cleaned


def _clean_material(raw: str | None) -> str | None:
    """The fabric a caller means: spaces trimmed, blank means none, too long is refused.

    Refused rather than cut, for the same reason as a season: a name silently shortened would
    no longer match what the owner typed.
    """
    if raw is None:
        return None
    cleaned = str(raw).strip()
    if not cleaned:
        return None
    if len(cleaned) > MATERIAL_MAX_LENGTH:
        raise ValueError(f"material must be at most {MATERIAL_MAX_LENGTH} characters")
    return cleaned


class ProductServiceMixin:
    """Product CRUD, queries, and external sync methods."""

    @staticmethod
    async def get_product(session: AsyncSession, tenant_id: UUID, product_id: UUID) -> Product:
        product = (
            await session.execute(
                select(Product).where(
                    Product.id == product_id,
                    Product.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if product is None:
            raise NotFoundError(f"product {product_id} not found")
        return product

    @staticmethod
    async def create_product(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        title: str,
        slug: str,
        description: str | None = None,
        brand_id: UUID | None = None,
        category_id: UUID | None = None,
        attributes: dict | None = None,
        season: str | None = None,
        material: str | None = None,
    ) -> Product:
        """Create a product; the slug must be unique within the tenant."""
        duplicate = (
            await session.execute(
                select(Product.id).where(
                    Product.tenant_id == tenant_id,
                    Product.slug == slug,
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise ConflictError(f"product slug '{slug}' already exists")

        # §settings: catalog.default_tax_rate — stamp the tenant's default tax
        # rate onto the product's attributes so order tax calculation can read
        # it when no explicit tax class is assigned.
        merged_attrs = attributes or {}
        if "default_tax_rate" not in merged_attrs:
            from app.modules.settings.service import SettingsService

            default_tax = await SettingsService(session, tenant_id).value(
                "catalog.default_tax_rate"
            )
            if default_tax and default_tax > 0:
                merged_attrs = {**merged_attrs, "default_tax_rate": default_tax}

        product = Product(
            tenant_id=tenant_id,
            title=title,
            slug=slug,
            description=description,
            brand_id=brand_id,
            category_id=category_id,
            attributes=merged_attrs,
            season=_clean_season(season),
            material=_clean_material(material),
        )
        try:
            async with session.begin_nested():
                session.add(product)
                await session.flush()
        except IntegrityError:
            # Lost a slug race with a concurrent request.
            raise ConflictError(f"product slug '{slug}' already exists") from None
        return product

    @staticmethod
    async def update_product(
        session: AsyncSession, tenant_id: UUID, product_id: UUID, **fields: object
    ) -> Product:
        """Partial update; unknown fields and bad statuses are rejected."""
        from app.applications.apparel.modules.catalog.services import CatalogService

        allowed = {
            "title",
            "slug",
            "description",
            "brand_id",
            "category_id",
            "attributes",
            "status",
            "season",
            "material",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown product fields: {sorted(unknown)}")
        for required in ("title", "slug"):
            if required in fields and fields[required] is None:
                raise ValueError(f"{required} must not be null")
        if "status" in fields and fields["status"] not in _PRODUCT_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_PRODUCT_STATUSES)}, got {fields['status']!r}"
            )

        product = await CatalogService.get_product(session, tenant_id, product_id)
        new_slug = fields.get("slug")
        if new_slug is not None and new_slug != product.slug:
            duplicate = (
                await session.execute(
                    select(Product.id).where(
                        Product.tenant_id == tenant_id,
                        Product.slug == new_slug,
                    )
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise ConflictError(f"product slug '{new_slug}' already exists")

        if "season" in fields:
            fields["season"] = _clean_season(fields["season"])
        if "material" in fields:
            fields["material"] = _clean_material(fields["material"])
        for key, value in fields.items():
            setattr(product, key, value)
        await session.flush()
        return product

    @staticmethod
    async def archive_product(session: AsyncSession, tenant_id: UUID, product_id: UUID) -> Product:
        from app.applications.apparel.modules.catalog.services import CatalogService

        return await CatalogService.update_product(
            session, tenant_id, product_id, status="archived"
        )

    @staticmethod
    async def _find_external_product(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        slug: str,
        source: str,
        external_ref: str,
    ) -> Product | None:
        """The row this external record already owns, if any.

        The slug is the tenant-unique natural key the handle maps onto; the
        provenance stamp is the fallback, because a merchant renaming a handle
        upstream must not buy a second product here.
        """
        by_slug = (
            await session.execute(
                select(Product).where(Product.tenant_id == tenant_id, Product.slug == slug)
            )
        ).scalar_one_or_none()
        if by_slug is not None:
            return by_slug
        return (
            await session.execute(
                select(Product).where(
                    Product.tenant_id == tenant_id,
                    Product.attributes["_source"].as_string() == source,
                    Product.attributes["_external_id"].as_string() == external_ref,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def upsert_from_external(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        external_ref: str,
        data: dict,
        source: str,
        currency: str | None = None,
    ) -> Product:
        """§161: create-or-update a product an external store owns (§8 service
        boundary — the adapters never write ``products`` themselves).

        §47: the incoming price is stamped with the currency its store declares,
        and anything other than this tenant's is a refusal. A ``Currency`` field
        is the difference between a price and a wrong invoice.
        """
        from app.core.tenancy import resolve_tenant_currency
        from app.applications.apparel.modules.catalog.services import CatalogService

        tenant_currency = await resolve_tenant_currency(session, tenant_id)
        code = (currency or tenant_currency).upper()
        if code != tenant_currency:
            raise ConflictError(
                f"{source} prices product {external_ref} in {code}, but this "
                f"tenant trades in {tenant_currency} — a {code} amount stored "
                f"as a {tenant_currency} one is a wrong number with a "
                "plausible label"
            )

        slug = (data.get("slug") or "").strip() or f"{source}-{external_ref}"
        title = (data.get("title") or "").strip() or f"{source} product {external_ref}"
        product = await CatalogService._find_external_product(
            session, tenant_id, slug=slug, source=source, external_ref=str(external_ref)
        )
        if product is None:
            product = await CatalogService.create_product(
                session,
                tenant_id,
                title=title,
                slug=slug,
                description=data.get("description") or None,
            )
        else:
            fields: dict = {"title": title}
            if data.get("description"):
                fields["description"] = data["description"]
            product = await CatalogService.update_product(session, tenant_id, product.id, **fields)
        if product.slug != slug:
            product = await CatalogService.update_product(session, tenant_id, product.id, slug=slug)
        # Applies to both paths: a new product is born a draft, and the store
        # saying "active" is the merchant's decision, not ours to delay.
        status = data.get("status")
        if status in _PRODUCT_STATUSES and product.status != status:
            product.status = status

        attributes = dict(product.attributes or {})
        attributes.update({"_source": source, "_external_id": str(external_ref)})
        product.attributes = attributes

        for spec in data.get("variants") or []:
            await CatalogService._upsert_external_variant(
                session, tenant_id, product, spec, str(external_ref)
            )
        await session.flush()
        return product

    @staticmethod
    async def _upsert_external_variant(
        session: AsyncSession,
        tenant_id: UUID,
        product: Product,
        spec: dict,
        external_ref: str,
    ) -> ProductVariant:
        """Match an external variant by SKU (tenant-unique), else by title.

        There is no column for the provider's variant id, so SKU is the key
        when the merchant filled it in and the title otherwise.
        """
        from app.applications.apparel.modules.catalog.services import CatalogService

        price = spec.get("price")
        if price in (None, ""):
            raise ValidationError(
                f"{product.slug} variant {spec.get('sku') or spec.get('title') or external_ref} "
                "has no price — a variant without one cannot be sold"
            )
        amount = _positive_decimal(price, "price")
        sku = (spec.get("sku") or "").strip() or None
        title = (spec.get("title") or "").strip() or None

        variant: ProductVariant | None = None
        if sku is not None:
            variant = (
                await session.execute(
                    select(ProductVariant).where(
                        ProductVariant.tenant_id == tenant_id,
                        ProductVariant.sku == sku,
                    )
                )
            ).scalar_one_or_none()
            if variant is not None and variant.product_id != product.id:
                raise ConflictError(f"variant SKU '{sku}' already belongs to another product")
        if variant is None and title is not None:
            variant = (
                await session.execute(
                    select(ProductVariant).where(
                        ProductVariant.tenant_id == tenant_id,
                        ProductVariant.product_id == product.id,
                        ProductVariant.title == title,
                    )
                )
            ).scalar_one_or_none()

        if variant is None:
            variant = await CatalogService.add_variant(
                session, tenant_id, product.id, sku=sku, title=title, price=amount
            )
        else:
            variant.price = amount
            if sku is not None and variant.sku is None:
                variant.sku = sku
            await session.flush()
        return variant

    @staticmethod
    async def list_products(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
        season: str | None = None,
        material: str | None = None,
    ) -> list[Product]:
        query = select(Product).where(Product.tenant_id == tenant_id)
        wanted = _clean_season(season)
        if wanted is not None:
            # A shop types SS26 and ss26 and " SS26" meaning the same season.
            query = query.where(func.lower(Product.season) == wanted.lower())
        wanted_material = _clean_material(material)
        if wanted_material is not None:
            # Cotton, cotton and " COTTON " are one fabric.
            query = query.where(func.lower(Product.material) == wanted_material.lower())
        rows = (
            (
                await session.execute(
                    query.order_by(Product.created_at.desc()).limit(limit).offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    def _product_filters(
        tenant_id: UUID,
        *,
        q: str | None = None,
        status: str | None = None,
        category_id: UUID | None = None,
        brand_id: UUID | None = None,
        season: str | None = None,
        material: str | None = None,
    ) -> list:
        """The WHERE clauses of the product list, shared by the page and its total count.

        One place, so the count can never disagree with the rows the shop is looking at.
        """
        clauses = [Product.tenant_id == tenant_id]
        term = (q or "").strip()
        if term:
            # الاسم أو الـslug أو كود أي صنف داخل المنتج: التاجر بيدوّر باللي قدامه.
            like = like_pattern(term.lower())
            clauses.append(
                or_(
                    func.lower(Product.title).like(like, escape="\\"),
                    func.lower(Product.slug).like(like, escape="\\"),
                    select(ProductVariant.id)
                    .where(
                        ProductVariant.tenant_id == tenant_id,
                        ProductVariant.product_id == Product.id,
                        func.lower(func.coalesce(ProductVariant.sku, "")).like(like, escape="\\"),
                    )
                    .exists(),
                )
            )
        if status and status != "all":
            clauses.append(Product.status == status)
        if category_id is not None:
            clauses.append(Product.category_id == category_id)
        if brand_id is not None:
            clauses.append(Product.brand_id == brand_id)
        wanted_season = _clean_season(season)
        if wanted_season is not None:
            clauses.append(func.lower(Product.season) == wanted_season.lower())
        wanted_material = _clean_material(material)
        if wanted_material is not None:
            clauses.append(func.lower(Product.material) == wanted_material.lower())
        return clauses

    @staticmethod
    async def search_products(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        q: str | None = None,
        status: str | None = None,
        category_id: UUID | None = None,
        brand_id: UUID | None = None,
        season: str | None = None,
        material: str | None = None,
        sort: str = "newest",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Product], int]:
        """One page of the shop's catalog, filtered and counted on the server.

        The products screen used to pull ``?limit=500`` once and search, filter and sort in the
        browser: a shop with 3,000 products could only ever reach the first 500. Here the database
        does the work and returns the page together with the total, so the screen can say "1–50 من
        3,000" and walk the rest.
        """
        clauses = ProductServiceMixin._product_filters(
            tenant_id,
            q=q,
            status=status,
            category_id=category_id,
            brand_id=brand_id,
            season=season,
            material=material,
        )
        order = {
            "newest": (Product.created_at.desc(), Product.id.desc()),
            "oldest": (Product.created_at.asc(), Product.id.asc()),
            "name": (func.lower(Product.title).asc(), Product.id.asc()),
            "name_desc": (func.lower(Product.title).desc(), Product.id.desc()),
        }.get(sort or "newest", (Product.created_at.desc(), Product.id.desc()))
        page_size = max(1, min(int(limit or 50), 200))
        rows = (
            (
                await session.execute(
                    select(Product)
                    .where(*clauses)
                    .order_by(*order)
                    .limit(page_size)
                    .offset(max(0, int(offset or 0)))
                )
            )
            .scalars()
            .all()
        )
        total = await session.scalar(select(func.count(Product.id)).where(*clauses))
        return list(rows), int(total or 0)

    @staticmethod
    async def get_products_by_ids(
        session: AsyncSession, tenant_id: UUID, product_ids: list[UUID]
    ) -> dict[UUID, Product]:
        """Batch-fetch products by ID — for cross-module line snapshotting (§8)."""
        if not product_ids:
            return {}
        rows = (
            (
                await session.execute(
                    select(Product).where(
                        Product.tenant_id == tenant_id,
                        Product.id.in_(product_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {p.id: p for p in rows}
