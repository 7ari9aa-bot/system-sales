"""Product variant and pricing services."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import Integer, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import ProductPrice, ProductVariant
from app.modules.catalog.services._common import _positive_decimal
from app.modules.errors import ConflictError, NotFoundError, ValidationError


class VariantServiceMixin:
    """Variant management, pricing tiers, and price resolution."""

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
        product_checked: bool = False,
        sku_checked: bool = False,
    ) -> ProductVariant:
        """Add a variant to a product; SKU (when given) is unique per tenant.

        ``product_checked`` / ``sku_checked`` say the caller already proved, inside this same
        transaction, that the product exists and that the SKU is free — the import batch does that
        once for the whole batch. The database's unique constraint still guards the write, and a
        lost race still surfaces as ``ConflictError``.
        """
        from app.modules.catalog.services import CatalogService

        if not product_checked:
            await CatalogService.get_product(session, tenant_id, product_id)
        unit_price = _positive_decimal(price, "price")

        # Enforce the per-product variant limit (catalog.max_variants_per_product).
        from app.modules.settings.service import SettingsService

        max_variants = await SettingsService(session, tenant_id).value(
            "catalog.max_variants_per_product"
        )
        if max_variants and max_variants > 0:
            current = (
                await session.execute(
                    select(func.count())
                    .select_from(ProductVariant)
                    .where(
                        ProductVariant.tenant_id == tenant_id,
                        ProductVariant.product_id == product_id,
                    )
                )
            ).scalar_one()
            if current >= max_variants:
                raise ValidationError(
                    f"this product already has the maximum of {max_variants} variants"
                )

        sku = sku or None
        # §settings: catalog.sku_format — when no SKU is provided, generate one
        # from the tenant's format pattern (e.g. "{category}-{number}").
        if sku is None:
            sku = await VariantServiceMixin._generate_sku(session, tenant_id, product_id)

        if sku is not None and not sku_checked:
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
        # §179: every variant write also writes the relational option graph —
        # the JSONB dict never becomes the only representation again.
        await CatalogService._sync_variant_option_links(
            session, tenant_id, variant.id, product_id, option_values or {}
        )

        # §settings: catalog.barcode_auto_generate — auto-generate a barcode
        # identifier for variants that don't have a manually entered one.
        auto_barcode = await SettingsService(session, tenant_id).value(
            "catalog.barcode_auto_generate"
        )
        if auto_barcode:
            from app.core.sequences import next_sequence
            from app.modules.catalog.apparel.barcode import internal_ean13
            from app.modules.catalog.models import ProductIdentifier

            existing = (
                await session.execute(
                    select(ProductIdentifier.id).where(
                        ProductIdentifier.tenant_id == tenant_id,
                        ProductIdentifier.variant_id == variant.id,
                        ProductIdentifier.type.in_(("barcode", "ean", "gtin", "upc")),
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                # Generate a proper EAN-13 from the shop's gap-free counter (same
                # path as POST /products/{id}/barcodes), not a UUID-derived hash.
                seq = await next_sequence(session, tenant_id, "BC", 0)
                barcode_val = internal_ean13(seq)
                session.add(
                    ProductIdentifier(
                        tenant_id=tenant_id,
                        variant_id=variant.id,
                        type="barcode",
                        value=barcode_val,
                    )
                )
                await session.flush()

        return variant

    @staticmethod
    async def _generate_sku(session: AsyncSession, tenant_id: UUID, product_id: UUID) -> str | None:
        """Generate a SKU from the tenant's ``catalog.sku_format`` pattern.

        ``{category}`` is replaced by the product's category name (or ``GEN`` when
        it has none) and ``{number}`` by a per-tenant auto-incremented counter.
        Returns ``None`` when the pattern is empty or would collide.
        """
        from app.modules.catalog.models import Product
        from app.modules.settings.service import SettingsService

        fmt = await SettingsService(session, tenant_id).value("catalog.sku_format")
        if not fmt:
            return None

        # Resolve the product's category name.
        product = (
            await session.execute(
                select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        category_name = "GEN"
        if product is not None and product.category_id is not None:
            from app.modules.catalog.models import Category

            cat = (
                await session.execute(
                    select(Category.name).where(Category.id == product.category_id)
                )
            ).scalar_one_or_none()
            if cat:
                category_name = cat.upper().replace(" ", "-")[:20]

        # Allocate the next sequential number.
        number = await VariantServiceMixin.allocate_sku_base(session, tenant_id)
        # allocate_sku_base returns "SKU-NNNN"; extract the number part.
        number = number.replace("SKU-", "")

        sku = fmt.replace("{category}", category_name).replace("{number}", number)
        return sku.strip() or None

    @staticmethod
    async def update_variant(
        session: AsyncSession, tenant_id: UUID, variant_id: UUID, **fields: object
    ) -> ProductVariant:
        """Partial update of a variant; unknown fields / bad prices rejected."""
        from app.modules.catalog.services import CatalogService

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
        if "option_values" in fields:
            await CatalogService._sync_variant_option_links(
                session, tenant_id, variant.id, variant.product_id, variant.option_values or {}
            )
        return variant

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
        from app.modules.catalog.services import CatalogService

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
                f"this tenant prices in {tenant_currency}; a {currency} tier could never be sold"
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

    @staticmethod
    async def price_for(
        session: AsyncSession,
        tenant_id: UUID,
        variant: ProductVariant,
        *,
        currency: str,
        quantity: int,
    ) -> Decimal:
        """The unit price THIS order pays: the deepest tier the quantity earns."""
        tier = (
            (
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
            )
            .scalars()
            .first()
        )
        return variant.price if tier is None else tier

    @staticmethod
    async def get_variants_by_ids(
        session: AsyncSession,
        tenant_id: UUID,
        variant_ids: list[UUID] | set[UUID],
    ) -> dict[UUID, ProductVariant]:
        """Batch-fetch variants by ID — a whole cart in one query."""
        if not variant_ids:
            return {}
        rows = (
            (
                await session.execute(
                    select(ProductVariant).where(
                        ProductVariant.tenant_id == tenant_id,
                        ProductVariant.id.in_(variant_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {v.id: v for v in rows}

    @staticmethod
    async def price_tiers_for_many(
        session: AsyncSession,
        tenant_id: UUID,
        variant_ids: list[UUID] | set[UUID],
        *,
        currency: str,
    ) -> dict[UUID, list[tuple[int, Decimal]]]:
        """Every price ladder for many variants, in ONE query."""
        if not variant_ids:
            return {}
        rows = (
            await session.execute(
                select(
                    ProductPrice.variant_id,
                    ProductPrice.min_quantity,
                    ProductPrice.unit_price,
                )
                .where(
                    ProductPrice.tenant_id == tenant_id,
                    ProductPrice.variant_id.in_(variant_ids),
                    ProductPrice.currency == currency.upper(),
                )
                .order_by(
                    ProductPrice.variant_id,
                    ProductPrice.min_quantity.desc(),
                    ProductPrice.id,
                )
            )
        ).all()
        ladders: dict[UUID, list[tuple[int, Decimal]]] = {}
        for variant_id, min_quantity, unit_price in rows:
            ladders.setdefault(variant_id, []).append((min_quantity, unit_price))
        return ladders

    @staticmethod
    def tiered_unit_price(
        variant_price: Decimal,
        tiers: list[tuple[int, Decimal]],
        quantity: int,
    ) -> Decimal:
        """``price_for``'s rules replayed in memory for one line."""
        for min_quantity, unit_price in tiers:
            if min_quantity <= quantity:
                return unit_price
        return variant_price

    @staticmethod
    async def active_variant_ids(session: AsyncSession, tenant_id: UUID) -> list[UUID]:
        """Ids of every active variant of the tenant (what a physical count walks through)."""
        rows = await session.execute(
            select(ProductVariant.id)
            .where(ProductVariant.tenant_id == tenant_id, ProductVariant.is_active.is_(True))
            .order_by(ProductVariant.id)
        )
        return list(rows.scalars().all())

    @staticmethod
    async def list_variants(
        session: AsyncSession, tenant_id: UUID, product_id: UUID
    ) -> list[ProductVariant]:
        rows = (
            (
                await session.execute(
                    select(ProductVariant)
                    .where(
                        ProductVariant.tenant_id == tenant_id,
                        ProductVariant.product_id == product_id,
                    )
                    .order_by(ProductVariant.created_at)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    #: The screen hands out SKU-0007 (base) and SKU-0007-0101 (variant).
    SKU_BASE_RE = r"^SKU-(\d+)"

    @staticmethod
    async def allocate_sku_base(session: AsyncSession, tenant_id: UUID) -> str:
        """Hand out the next SKU base for this shop, atomically.

        ``next_sku_base`` only *reads* the highest number, so two employees who open the
        add-product screen at the same moment are both shown SKU-0007 and the second save hits the
        unique constraint. This reserves the number in the database with one statement
        (``INSERT ... ON CONFLICT DO UPDATE ... RETURNING``): whichever request arrives second sees
        the bumped row and gets the number after it. A number handed out is never handed out again.
        """
        from sqlalchemy import text as sql_text

        series = VariantServiceMixin.SKU_BASE_RE
        used = await session.scalar(
            select(func.max(func.cast(func.substring(ProductVariant.sku, series), Integer))).where(
                ProductVariant.tenant_id == tenant_id,
                ProductVariant.sku.op("~")(series),
            )
        )
        seed = (used or 0) + 1
        taken = await session.scalar(
            sql_text(
                """
                INSERT INTO sku_counters (id, tenant_id, last_number, created_at, updated_at)
                VALUES (gen_random_uuid(), :tenant_id, :seed, now(), now())
                ON CONFLICT ON CONSTRAINT uq_sku_counters_tenant DO UPDATE
                    SET last_number = GREATEST(sku_counters.last_number, :seed) + 1,
                        updated_at = now()
                RETURNING last_number
                """
            ),
            {"tenant_id": tenant_id, "seed": seed},
        )
        return f"SKU-{int(taken or seed):04d}"

    @staticmethod
    async def next_sku_base(session: AsyncSession, tenant_id: UUID) -> str:
        """The next free "SKU-0001" base, from the highest SKU this shop already uses.

        One aggregate query instead of shipping the catalog to the browser: the add-product screen
        used to load up to 500 products, with every variant, only to count them in the page.
        Codes that do not start with SKU- are ignored, so imported or vendor codes never push the
        counter somewhere surprising.
        """
        series = VariantServiceMixin.SKU_BASE_RE
        used = await session.scalar(
            select(func.max(func.cast(func.substring(ProductVariant.sku, series), Integer))).where(
                ProductVariant.tenant_id == tenant_id,
                ProductVariant.sku.op("~")(series),
            )
        )
        return f"SKU-{(used or 0) + 1:04d}"

    @staticmethod
    async def list_variants_for_products(
        session: AsyncSession, tenant_id: UUID, product_ids: list[UUID]
    ) -> dict[UUID, list[ProductVariant]]:
        """Batch-load the variants of products already scoped by the caller.

        One query for the whole page instead of one per product: listing 500 products used to
        cost 501 round trips. Each product's variants keep the order `list_variants` gives
        (oldest first), and a product with none maps to nothing, so use `.get(id, [])`.
        """
        if not product_ids:
            return {}
        rows = (
            (
                await session.execute(
                    select(ProductVariant)
                    .where(
                        ProductVariant.tenant_id == tenant_id,
                        ProductVariant.product_id.in_(product_ids),
                    )
                    .order_by(ProductVariant.created_at)
                )
            )
            .scalars()
            .all()
        )
        grouped: dict[UUID, list[ProductVariant]] = {}
        for variant in rows:
            grouped.setdefault(variant.product_id, []).append(variant)
        return grouped
