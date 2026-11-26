"""Brands, categories, and product gallery image services."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.limits import MAX_IMAGES_PER_SKU
from app.modules.catalog.models import Brand, Category, ProductImage
from app.modules.errors import ConflictError, NotFoundError, ValidationError


class TaxonomyServiceMixin:
    """Brands, categories, and media/gallery images."""

    @staticmethod
    async def create_brand(session: AsyncSession, tenant_id: UUID, *, name: str) -> Brand:
        brand = Brand(tenant_id=tenant_id, name=name)
        try:
            async with session.begin_nested():
                session.add(brand)
                await session.flush()
        except IntegrityError:
            raise ConflictError(f"brand '{name}' already exists") from None
        return brand

    @staticmethod
    async def categories_exist(
        session: AsyncSession, tenant_id: UUID, category_ids: list[UUID]
    ) -> bool:
        """Whether every id is a live category of this tenant.

        The POS profile's catalog scoping guards against a terminal pointing
        at a missing category — that would silently serve an empty grid.
        """
        if not category_ids:
            return True
        known = (
            await session.execute(
                select(func.count())
                .select_from(Category)
                .where(
                    Category.tenant_id == tenant_id,
                    Category.id.in_(list(category_ids)),
                )
            )
        ).scalar_one()
        return known == len(set(category_ids))

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

    @staticmethod
    async def add_image(
        session: AsyncSession,
        tenant_id: UUID,
        product_id: UUID,
        *,
        url: str,
        alt: str | None = None,
        variant_id: UUID | None = None,
    ) -> ProductImage:
        """Append one gallery image, positioned after the product's last one."""
        from app.modules.catalog.services import CatalogService

        await CatalogService.get_product(session, tenant_id, product_id)
        bound_variant = None
        if variant_id is not None:
            bound_variant = await CatalogService.get_variant(
                session, tenant_id, variant_id, include_inactive=True
            )
            if bound_variant.product_id != product_id:
                raise ValidationError("variant does not belong to this product")
        # نفس حد الصور في كل المسارات: الصنف (التركيبة) لو الصورة مربوطة بصنف، وإلا معرض المنتج.
        # الرفع اليدوي والـZIP وورقة الصور بيقروا الرقم من catalog/limits.py.
        scope = (
            ProductImage.variant_id == bound_variant.id
            if bound_variant is not None
            else ProductImage.variant_id.is_(None)
        )
        existing = (
            await session.execute(
                select(func.count(ProductImage.id)).where(
                    ProductImage.tenant_id == tenant_id,
                    ProductImage.product_id == product_id,
                    scope,
                )
            )
        ).scalar()
        # الحد بقى إعداد (catalog.max_images_per_sku) بدل ثابت في الكود: نفس الرقم اللي
        # الصفحة بتعرضه هو اللي الخدمة بتفرضه، والثابت في limits.py بقى الاحتياطي فقط لو
        # الإعداد مش مقروء.
        limit = MAX_IMAGES_PER_SKU
        try:
            from app.modules.settings.service import SettingsService

            limit = int(
                await SettingsService(session, tenant_id).value("catalog.max_images_per_sku")
                or MAX_IMAGES_PER_SKU
            )
        except Exception:  # noqa: BLE001 - an unreadable setting must not block an upload
            limit = MAX_IMAGES_PER_SKU
        if (existing or 0) >= limit:
            raise ValidationError(
                f"الصنف ده وصل للحد الأقصى ({limit} صور). امسح صورة قبل ما تضيف غيرها"
            )
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
            variant_id=bound_variant.id if bound_variant is not None else None,
            url=url,
            alt=alt,
            position=0 if highest is None else highest + 1,
        )
        session.add(image)
        await session.flush()
        return image

    @staticmethod
    async def get_image(
        session: AsyncSession, tenant_id: UUID, product_id: UUID, image_id: UUID
    ) -> ProductImage:
        """One gallery row that must belong to this product (404 otherwise)."""
        row = (
            await session.execute(
                select(ProductImage).where(
                    ProductImage.tenant_id == tenant_id,
                    ProductImage.product_id == product_id,
                    ProductImage.id == image_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("image not found on this product")
        return row

    @staticmethod
    async def update_image(
        session: AsyncSession,
        tenant_id: UUID,
        product_id: UUID,
        image_id: UUID,
        *,
        alt: str | None = None,
        variant_id: UUID | None = None,
        unbind_variant: bool = False,
    ) -> ProductImage:
        """Rebind a shot to a colour/variant (or back to the product gallery) and retitle it."""
        from app.modules.catalog.services import CatalogService

        image = await TaxonomyServiceMixin.get_image(session, tenant_id, product_id, image_id)
        if alt is not None:
            image.alt = alt
        if unbind_variant:
            image.variant_id = None
        elif variant_id is not None:
            variant = await CatalogService.get_variant(
                session, tenant_id, variant_id, include_inactive=True
            )
            if variant.product_id != product_id:
                raise ValidationError("variant does not belong to this product")
            image.variant_id = variant.id
        await session.flush()
        return image

    @staticmethod
    async def reorder_images(
        session: AsyncSession, tenant_id: UUID, product_id: UUID, image_ids: list[UUID]
    ) -> list[ProductImage]:
        """Set the gallery order to exactly ``image_ids`` (first shown first)."""
        rows = await TaxonomyServiceMixin.list_images(session, tenant_id, product_id)
        by_id = {row.id: row for row in rows}
        if set(image_ids) != set(by_id) or len(image_ids) != len(by_id):
            raise ValidationError("image_ids must list every image of this product exactly once")
        for index, image_id in enumerate(image_ids):
            by_id[image_id].position = index
        await session.flush()
        return [by_id[i] for i in image_ids]

    @staticmethod
    async def delete_image(
        session: AsyncSession, tenant_id: UUID, product_id: UUID, image_id: UUID
    ) -> str | None:
        """Remove a gallery row and hand back the stored object key so the caller can delete it."""
        image = await TaxonomyServiceMixin.get_image(session, tenant_id, product_id, image_id)
        url = image.url
        await session.delete(image)
        await session.flush()
        return url[len("s3://") :] if url.startswith("s3://") else None

    @staticmethod
    async def list_images(
        session: AsyncSession, tenant_id: UUID, product_id: UUID
    ) -> list[ProductImage]:
        """The product's gallery in display order."""
        from app.modules.catalog.services import CatalogService

        await CatalogService.get_product(session, tenant_id, product_id)
        rows = (
            (
                await session.execute(
                    select(ProductImage)
                    .where(
                        ProductImage.tenant_id == tenant_id,
                        ProductImage.product_id == product_id,
                    )
                    .order_by(ProductImage.position.asc(), ProductImage.id.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    async def list_images_for_products(
        session: AsyncSession, tenant_id: UUID, product_ids: list[UUID]
    ) -> dict[UUID, list[ProductImage]]:
        """Batch-load galleries for products already scoped by the caller."""
        if not product_ids:
            return {}
        rows = (
            (
                await session.execute(
                    select(ProductImage)
                    .where(
                        ProductImage.tenant_id == tenant_id,
                        ProductImage.product_id.in_(product_ids),
                    )
                    .order_by(
                        ProductImage.product_id.asc(),
                        ProductImage.position.asc(),
                        ProductImage.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        grouped: dict[UUID, list[ProductImage]] = {}
        for image in rows:
            grouped.setdefault(image.product_id, []).append(image)
        return grouped

    @staticmethod
    async def list_brands(
        session: AsyncSession, tenant_id: UUID, *, limit: int = 200, offset: int = 0
    ) -> list[Brand]:
        rows = (
            (
                await session.execute(
                    select(Brand)
                    .where(Brand.tenant_id == tenant_id)
                    .order_by(Brand.name.asc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    async def list_categories(
        session: AsyncSession, tenant_id: UUID, *, limit: int = 200, offset: int = 0
    ) -> list[Category]:
        rows = (
            (
                await session.execute(
                    select(Category)
                    .where(Category.tenant_id == tenant_id)
                    .order_by(Category.name.asc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)
