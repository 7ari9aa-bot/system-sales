"""Product identifiers and barcode resolution services."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import ProductIdentifier, ProductVariant
from app.modules.catalog.services._common import IDENTIFIER_TYPES
from app.modules.errors import ConflictError, NotFoundError, ValidationError


class IdentifierServiceMixin:
    """Barcode and identifier registration and lookup."""

    @staticmethod
    def _clean_identifier(identifier_type: str, value: str) -> str:
        if identifier_type not in IDENTIFIER_TYPES:
            raise ValidationError(f"identifier type must be one of {sorted(IDENTIFIER_TYPES)}")
        cleaned = value.strip()
        if not cleaned:
            raise ValidationError("identifier value must not be empty")
        if len(cleaned) > 127:
            raise ValidationError("identifier value must be at most 127 characters")
        return cleaned

    @staticmethod
    async def add_identifier(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        identifier_type: str,
        value: str,
    ) -> ProductIdentifier:
        """Register one scan code on a variant (§179).

        Uniqueness is per (tenant, type, value): the resolver must return
        exactly one sellable unit or nothing — never two candidates.
        """
        from app.modules.catalog.services import CatalogService

        cleaned = CatalogService._clean_identifier(identifier_type, value)
        variant = await CatalogService.get_variant(session, tenant_id, variant_id)
        row = ProductIdentifier(
            tenant_id=tenant_id,
            variant_id=variant.id,
            type=identifier_type,
            value=cleaned,
        )
        session.add(row)
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError:
            raise ConflictError(
                f"identifier {identifier_type}:{cleaned} already registered"
            ) from None
        return row

    @staticmethod
    async def resolve_identifier(
        session: AsyncSession, tenant_id: UUID, identifier_type: str, value: str
    ) -> ProductVariant | None:
        """The only scan-entry point (§179): one ACTIVE variant, or None.

        Sellability of the variant's product is the caller's check — the same
        discipline as price_for. An unknown or inactive variant resolves to
        None, never to a half-answer.
        """
        from app.modules.catalog.services import CatalogService

        cleaned = CatalogService._clean_identifier(identifier_type, value)
        row = (
            await session.execute(
                select(ProductIdentifier).where(
                    ProductIdentifier.tenant_id == tenant_id,
                    ProductIdentifier.type == identifier_type,
                    ProductIdentifier.value == cleaned,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        variant = (
            await session.execute(
                select(ProductVariant).where(
                    ProductVariant.tenant_id == tenant_id,
                    ProductVariant.id == row.variant_id,
                    ProductVariant.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        return variant

    @staticmethod
    async def list_identifiers(
        session: AsyncSession, tenant_id: UUID, variant_id: UUID
    ) -> list[ProductIdentifier]:
        rows = (
            (
                await session.execute(
                    select(ProductIdentifier)
                    .where(
                        ProductIdentifier.tenant_id == tenant_id,
                        ProductIdentifier.variant_id == variant_id,
                    )
                    .order_by(ProductIdentifier.created_at, ProductIdentifier.id)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    async def remove_identifier(
        session: AsyncSession, tenant_id: UUID, identifier_id: UUID
    ) -> None:
        row = (
            await session.execute(
                select(ProductIdentifier).where(
                    ProductIdentifier.tenant_id == tenant_id,
                    ProductIdentifier.id == identifier_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"identifier {identifier_id} not found")
        await session.delete(row)
