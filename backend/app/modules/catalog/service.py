"""CATALOG domain service — products, variants, brands, categories, prices.

Every method takes the caller's session and tenant and NEVER commits: the
request/worker owns the transaction, the service owns the rules.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import (
    Brand,
    Category,
    Product,
    ProductImage,
    ProductPrice,
    ProductVariant,
)
from app.modules.errors import ConflictError, NotFoundError, ValidationError

_PRODUCT_STATUSES = {"draft", "active", "archived"}


def _to_decimal(value: object, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a valid number") from exc


def _positive_decimal(value: object, field: str) -> Decimal:
    amount = _to_decimal(value, field)
    if amount <= 0:
        raise ValueError(f"{field} must be greater than zero")
    return amount


class CatalogService:
    """All catalog business rules; static methods taking (session, tenant_id)."""

    # ----------------------------------------------------------- product ----

    @staticmethod
    async def get_product(
        session: AsyncSession, tenant_id: UUID, product_id: UUID
    ) -> Product:
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

        product = Product(
            tenant_id=tenant_id,
            title=title,
            slug=slug,
            description=description,
            brand_id=brand_id,
            category_id=category_id,
            attributes=attributes or {},
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
        allowed = {
            "title",
            "slug",
            "description",
            "brand_id",
            "category_id",
            "attributes",
            "status",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown product fields: {sorted(unknown)}")
        for required in ("title", "slug"):
            if required in fields and fields[required] is None:
                raise ValueError(f"{required} must not be null")
        if "status" in fields and fields["status"] not in _PRODUCT_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_PRODUCT_STATUSES)}, "
                f"got {fields['status']!r}"
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

        for key, value in fields.items():
            setattr(product, key, value)
        await session.flush()
        return product

    @staticmethod
    async def archive_product(
        session: AsyncSession, tenant_id: UUID, product_id: UUID
    ) -> Product:
        return await CatalogService.update_product(
            session, tenant_id, product_id, status="archived"
        )

    @staticmethod
    async def _find_external_product(
        session: AsyncSession, tenant_id: UUID, *, slug: str, source: str,
        external_ref: str,
    ) -> Product | None:
        """The row this external record already owns, if any.

        The slug is the tenant-unique natural key the handle maps onto; the
        provenance stamp is the fallback, because a merchant renaming a handle
        upstream must not buy a second product here.
        """
        by_slug = (
            await session.execute(
                select(Product).where(
                    Product.tenant_id == tenant_id, Product.slug == slug
                )
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
            product = await CatalogService.update_product(
                session, tenant_id, product.id, **fields
            )
        if product.slug != slug:
            product = await CatalogService.update_product(
                session, tenant_id, product.id, slug=slug
            )
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
                raise ConflictError(
                    f"variant SKU '{sku}' already belongs to another product"
                )
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

    # ----------------------------------------------------------- variant ----

    @staticmethod
    async def get_variant(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        *,
        include_inactive: bool = False,
    ) -> ProductVariant:
        """Fetch a sellable variant; inactive (or foreign-tenant) -> NotFound."""
        variant = (
            await session.execute(
                select(ProductVariant).where(
                    ProductVariant.id == variant_id,
                    ProductVariant.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if variant is None or (not include_inactive and not variant.is_active):
            raise NotFoundError(f"variant {variant_id} not found")
        return variant

    @staticmethod
    async def add_variant(
        session: AsyncSession,
        tenant_id: UUID,
        product_id: UUID,
        *,
        sku: str | None = None,
        title: str | None = None,
        option_values: dict | None = None,
        price: object,
    ) -> ProductVariant:
        """Add a variant to a product; SKU (when given) is unique per tenant."""
        await CatalogService.get_product(session, tenant_id, product_id)
        unit_price = _positive_decimal(price, "price")
        sku = sku or None
        if sku is not None:
            duplicate = (
                await session.execute(
                    select(ProductVariant.id).where(
                        ProductVariant.tenant_id == tenant_id,
                        ProductVariant.sku == sku,
                    )
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise ConflictError(f"variant SKU '{sku}' already exists")

        variant = ProductVariant(
            tenant_id=tenant_id,
            product_id=product_id,
            sku=sku,
            title=title,
            option_values=option_values or {},
            price=unit_price,
        )
        try:
            async with session.begin_nested():
                session.add(variant)
                await session.flush()
        except IntegrityError:
            # Lost an SKU race with a concurrent request.
            raise ConflictError(f"variant SKU '{sku}' already exists") from None
        return variant

    @staticmethod
    async def update_variant(
        session: AsyncSession, tenant_id: UUID, variant_id: UUID, **fields: object
    ) -> ProductVariant:
        """Partial update of a variant; unknown fields / bad prices rejected."""
        allowed = {"sku", "title", "option_values", "price", "compare_at_price", "is_active"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValidationError(f"unknown variant fields: {sorted(unknown)}")
        if fields.get("option_values") is None and "option_values" in fields:
            raise ValidationError("option_values must not be null")
        if fields.get("is_active") is None and "is_active" in fields:
            raise ValidationError("is_active must not be null")

        variant = await CatalogService.get_variant(
            session, tenant_id, variant_id, include_inactive=True
        )
        if "price" in fields:
            if fields["price"] is None:
                raise ValidationError("price must be a positive number")
            try:
                fields["price"] = _positive_decimal(fields["price"], "price")
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
        if fields.get("compare_at_price") is not None:
            try:
                fields["compare_at_price"] = _positive_decimal(
                    fields["compare_at_price"], "compare_at_price"
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

        new_sku = fields.get("sku")
        if new_sku is not None and new_sku != variant.sku:
            duplicate = (
                await session.execute(
                    select(ProductVariant.id).where(
                        ProductVariant.tenant_id == tenant_id,
                        ProductVariant.sku == new_sku,
                        ProductVariant.id != variant_id,
                    )
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise ConflictError(f"variant SKU '{new_sku}' already exists")

        for key, value in fields.items():
            setattr(variant, key, value)
        await session.flush()
        return variant

    # ------------------------------------------------------------ prices ----

    @staticmethod
    async def set_variant_price(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        unit_price: object,
        currency: str | None = None,
        min_quantity: int = 1,
    ) -> ProductPrice:
        """Write the price tier row (append-only table, tier upserted).

        §47: the currency defaults to the tenant's, and anything else is
        refused. A tier in a currency this tenant does not trade in can never
        be sold — it is not a price, it is a future wrong invoice.
        """
        from app.core.tenancy import resolve_tenant_currency

        variant = await CatalogService.get_variant(
            session, tenant_id, variant_id, include_inactive=True
        )
        amount = _positive_decimal(unit_price, "unit_price")
        if min_quantity < 1:
            raise ValueError("min_quantity must be >= 1")
        tenant_currency = await resolve_tenant_currency(session, tenant_id)
        currency = (currency or tenant_currency).upper()
        if currency != tenant_currency:
            raise ConflictError(
                f"this tenant prices in {tenant_currency}; a {currency} tier "
                "could never be sold"
            )

        row = (
            await session.execute(
                select(ProductPrice).where(
                    ProductPrice.tenant_id == tenant_id,
                    ProductPrice.variant_id == variant.id,
                    ProductPrice.currency == currency,
                    ProductPrice.min_quantity == min_quantity,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProductPrice(
                tenant_id=tenant_id,
                variant_id=variant.id,
                currency=currency,
                unit_price=amount,
                min_quantity=min_quantity,
            )
            session.add(row)
        else:
            row.unit_price = amount
        await session.flush()
        return row

    # ---------------------------------------------------- price ladder ------

    @staticmethod
    async def price_for(
        session: AsyncSession,
        tenant_id: UUID,
        variant: ProductVariant,
        *,
        currency: str,
        quantity: int,
    ) -> Decimal:
        """The unit price THIS order pays: the deepest tier the quantity earns.

        Two rules the table enforced by itself but nobody asked before §47:

        * a tier counts only in the order's currency, so a legacy row left over
          from another shop cannot price this tenant's line;
        * the highest ``min_quantity`` at or below the quantity wins, which is
          what a quantity ladder means.

        With no applicable tier the variant's own price is the answer — the
        ladder is an override, not a prerequisite. Takes the variant the caller
        already loaded: checkout needs its title and SKU for the snapshot
        anyway, and a price lookup should not re-query for it.
        """
        tier = (
            await session.execute(
                select(ProductPrice.unit_price)
                .where(
                    ProductPrice.tenant_id == tenant_id,
                    ProductPrice.variant_id == variant.id,
                    ProductPrice.currency == currency.upper(),
                    ProductPrice.min_quantity <= quantity,
                )
                .order_by(ProductPrice.min_quantity.desc(), ProductPrice.id)
                .limit(1)
            )
        ).scalars().first()
        return variant.price if tier is None else tier

    # ------------------------------------------------- brands/categories ----

    @staticmethod
    async def create_brand(
        session: AsyncSession, tenant_id: UUID, *, name: str
    ) -> Brand:
        brand = Brand(tenant_id=tenant_id, name=name)
        try:
            async with session.begin_nested():
                session.add(brand)
                await session.flush()
        except IntegrityError:
            raise ConflictError(f"brand '{name}' already exists") from None
        return brand

    @staticmethod
    async def create_category(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        name: str,
        parent_id: UUID | None = None,
    ) -> Category:
        """Create a category; the parent (when given) must be in the tenant."""
        if parent_id is not None:
            parent = (
                await session.execute(
                    select(Category).where(
                        Category.id == parent_id,
                        Category.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if parent is None:
                raise NotFoundError(f"category {parent_id} not found")

        category = Category(tenant_id=tenant_id, name=name, parent_id=parent_id)
        session.add(category)
        await session.flush()
        return category

    # --------------------------------------------------------------- images ----

    @staticmethod
    async def add_image(
        session: AsyncSession,
        tenant_id: UUID,
        product_id: UUID,
        *,
        url: str,
        alt: str | None = None,
    ) -> ProductImage:
        """Append one gallery image, positioned after the product's last one.

        The position is derived, not supplied: two merchandisers posting in a row
        must not both count the same slot.
        """
        await CatalogService.get_product(session, tenant_id, product_id)
        highest = (
            await session.execute(
                select(func.max(ProductImage.position)).where(
                    ProductImage.tenant_id == tenant_id,
                    ProductImage.product_id == product_id,
                )
            )
        ).scalar()
        image = ProductImage(
            tenant_id=tenant_id,
            product_id=product_id,
            url=url,
            alt=alt,
            position=0 if highest is None else highest + 1,
        )
        session.add(image)
        await session.flush()
        return image

    @staticmethod
    async def list_images(
        session: AsyncSession, tenant_id: UUID, product_id: UUID
    ) -> list[ProductImage]:
        """The product's gallery in display order."""
        await CatalogService.get_product(session, tenant_id, product_id)
        rows = (
            await session.execute(
                select(ProductImage)
                .where(
                    ProductImage.tenant_id == tenant_id,
                    ProductImage.product_id == product_id,
                )
                .order_by(ProductImage.position.asc(), ProductImage.id.asc())
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def list_brands(
        session: AsyncSession, tenant_id: UUID, *, limit: int = 200, offset: int = 0
    ) -> list[Brand]:
        rows = (
            await session.execute(
                select(Brand)
                .where(Brand.tenant_id == tenant_id)
                .order_by(Brand.name.asc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def list_categories(
        session: AsyncSession, tenant_id: UUID, *, limit: int = 200, offset: int = 0
    ) -> list[Category]:
        rows = (
            await session.execute(
                select(Category)
                .where(Category.tenant_id == tenant_id)
                .order_by(Category.name.asc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def list_products(
        session: AsyncSession, tenant_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> list[Product]:
        rows = (
            await session.execute(
                select(Product)
                .where(Product.tenant_id == tenant_id)
                .order_by(Product.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def list_variants(
        session: AsyncSession, tenant_id: UUID, product_id: UUID
    ) -> list[ProductVariant]:
        rows = (
            await session.execute(
                select(ProductVariant)
                .where(
                    ProductVariant.tenant_id == tenant_id,
                    ProductVariant.product_id == product_id,
                )
                .order_by(ProductVariant.created_at)
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def get_products_by_ids(
        session: AsyncSession, tenant_id: UUID, product_ids: list[UUID]
    ) -> dict[UUID, Product]:
        """Batch-fetch products by ID — for cross-module line snapshotting (§8)."""
        if not product_ids:
            return {}
        rows = (
            await session.execute(
                select(Product).where(
                    Product.tenant_id == tenant_id,
                    Product.id.in_(product_ids),
                )
            )
        ).scalars().all()
        return {p.id: p for p in rows}
