"""Product option axes, option values, and variant links."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import (
    ProductOption,
    ProductOptionValue,
    ProductVariant,
    ProductVariantOptionValue,
)
from app.modules.errors import ConflictError, NotFoundError, ValidationError


class OptionServiceMixin:
    """Option graph, options, option values, and variant option links."""

    @staticmethod
    async def _sync_variant_option_links(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        product_id: UUID,
        options: dict,
    ) -> dict[str, str]:
        """Write the relational option graph for one variant (§179, P2).

        Replace-all semantics: link rows are rebuilt to match ``options``,
        missing option/value rows are auto-created, and the variant's JSONB
        read model is rewritten to the same dict. The two representations
        cannot drift because one service writes both in one transaction.
        """
        from app.modules.catalog.services import CatalogService

        cleaned: dict[str, str] = {}
        for raw_name, raw_value in (options or {}).items():
            name = str(raw_name).strip()
            value = str(raw_value).strip()
            if not name or not value:
                raise ValidationError("option name and value must not be empty")
            if len(name) > 63:
                raise ValidationError("option name must be at most 63 characters")
            if len(value) > 127:
                raise ValidationError("option value must be at most 127 characters")
            cleaned[name] = value

        await session.execute(
            delete(ProductVariantOptionValue).where(
                ProductVariantOptionValue.tenant_id == tenant_id,
                ProductVariantOptionValue.variant_id == variant_id,
            )
        )
        for name, value in cleaned.items():
            option = (
                await session.execute(
                    select(ProductOption).where(
                        ProductOption.tenant_id == tenant_id,
                        ProductOption.product_id == product_id,
                        ProductOption.name == name,
                    )
                )
            ).scalar_one_or_none()
            if option is None:
                option = ProductOption(tenant_id=tenant_id, product_id=product_id, name=name)
                session.add(option)
                try:
                    async with session.begin_nested():
                        await session.flush()
                except IntegrityError:
                    # Lost a creation race with a concurrent variant write —
                    # both writers meant the same option row.
                    option = (
                        await session.execute(
                            select(ProductOption).where(
                                ProductOption.tenant_id == tenant_id,
                                ProductOption.product_id == product_id,
                                ProductOption.name == name,
                            )
                        )
                    ).scalar_one()
            value_row = (
                await session.execute(
                    select(ProductOptionValue).where(
                        ProductOptionValue.tenant_id == tenant_id,
                        ProductOptionValue.option_id == option.id,
                        ProductOptionValue.value == value,
                    )
                )
            ).scalar_one_or_none()
            if value_row is None:
                value_row = ProductOptionValue(
                    tenant_id=tenant_id, option_id=option.id, value=value
                )
                session.add(value_row)
                try:
                    async with session.begin_nested():
                        await session.flush()
                except IntegrityError:
                    value_row = (
                        await session.execute(
                            select(ProductOptionValue).where(
                                ProductOptionValue.tenant_id == tenant_id,
                                ProductOptionValue.option_id == option.id,
                                ProductOptionValue.value == value,
                            )
                        )
                    ).scalar_one()
            session.add(
                ProductVariantOptionValue(
                    tenant_id=tenant_id,
                    variant_id=variant_id,
                    option_id=option.id,
                    option_value_id=value_row.id,
                )
            )
        variant = await CatalogService.get_variant(
            session, tenant_id, variant_id, include_inactive=True
        )
        variant.option_values = cleaned
        await session.flush()
        return cleaned

    @staticmethod
    async def set_variant_options(
        session: AsyncSession, tenant_id: UUID, variant_id: UUID, option_values: dict
    ) -> ProductVariant:
        """Replace a variant's option graph — one value per option (§179)."""
        from app.modules.catalog.services import CatalogService

        variant = await CatalogService.get_variant(
            session, tenant_id, variant_id, include_inactive=True
        )
        await CatalogService._sync_variant_option_links(
            session, tenant_id, variant.id, variant.product_id, option_values
        )
        return variant

    @staticmethod
    async def add_option(
        session: AsyncSession, tenant_id: UUID, product_id: UUID, name: str
    ) -> ProductOption:
        from app.modules.catalog.services import CatalogService

        await CatalogService.get_product(session, tenant_id, product_id)
        cleaned = str(name).strip()
        if not cleaned:
            raise ValidationError("option name must not be empty")
        if len(cleaned) > 63:
            raise ValidationError("option name must be at most 63 characters")
        row = ProductOption(tenant_id=tenant_id, product_id=product_id, name=cleaned)
        session.add(row)
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError:
            raise ConflictError(f"option '{cleaned}' already exists on this product") from None
        return row

    @staticmethod
    async def add_option_value(
        session: AsyncSession, tenant_id: UUID, option_id: UUID, value: str
    ) -> ProductOptionValue:
        option = (
            await session.execute(
                select(ProductOption).where(
                    ProductOption.tenant_id == tenant_id,
                    ProductOption.id == option_id,
                )
            )
        ).scalar_one_or_none()
        if option is None:
            raise NotFoundError(f"option {option_id} not found")
        cleaned = str(value).strip()
        if not cleaned:
            raise ValidationError("option value must not be empty")
        if len(cleaned) > 127:
            raise ValidationError("option value must be at most 127 characters")
        row = ProductOptionValue(tenant_id=tenant_id, option_id=option.id, value=cleaned)
        session.add(row)
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError:
            raise ConflictError(f"value '{cleaned}' already exists on this option") from None
        return row

    @staticmethod
    async def list_product_options(
        session: AsyncSession, tenant_id: UUID, product_id: UUID
    ) -> list[tuple[ProductOption, list[ProductOptionValue]]]:
        """The product's option axes with their values, in creation order."""
        from app.modules.catalog.services import CatalogService

        await CatalogService.get_product(session, tenant_id, product_id)
        options = (
            (
                await session.execute(
                    select(ProductOption)
                    .where(
                        ProductOption.tenant_id == tenant_id,
                        ProductOption.product_id == product_id,
                    )
                    .order_by(ProductOption.created_at.asc(), ProductOption.id.asc())
                )
            )
            .scalars()
            .all()
        )
        option_ids = [o.id for o in options]
        values_by_option: dict[UUID, list[ProductOptionValue]] = {}
        if option_ids:
            values = (
                (
                    await session.execute(
                        select(ProductOptionValue)
                        .where(
                            ProductOptionValue.tenant_id == tenant_id,
                            ProductOptionValue.option_id.in_(option_ids),
                        )
                        .order_by(ProductOptionValue.created_at.asc(), ProductOptionValue.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            for v in values:
                values_by_option.setdefault(v.option_id, []).append(v)
        return [(o, values_by_option.get(o.id, [])) for o in options]
