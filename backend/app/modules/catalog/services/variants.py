"""Product variant and pricing services."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
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
    ) -> ProductVariant:
        """Add a variant to a product; SKU (when given) is unique per tenant."""
        from app.modules.catalog.services import CatalogService

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
        # §179: every variant write also writes the relational option graph —
        # the JSONB dict never becomes the only representation again.
        await CatalogService._sync_variant_option_links(
            session, tenant_id, variant.id, product_id, option_values or {}
        )
        return variant

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
