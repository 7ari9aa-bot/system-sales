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
        currency: str = "EGP",
        min_quantity: int = 1,
    ) -> ProductPrice:
        """Write the price tier row (append-only table, tier upserted)."""
        variant = await CatalogService.get_variant(
            session, tenant_id, variant_id, include_inactive=True
        )
        amount = _positive_decimal(unit_price, "unit_price")
        if min_quantity < 1:
            raise ValueError("min_quantity must be >= 1")
        currency = (currency or "EGP").upper()

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
