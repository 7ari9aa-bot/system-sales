"""Catalog Bundle Service Mixin: bundles and kits (§4 Phase 6, M2/D7).

Bundles represent products sold as sets of components.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.apparel.modules.catalog.models import (
    Product,
    ProductBundle,
    ProductBundleLine,
    ProductVariant,
)
from app.modules.errors import ConflictError, NotFoundError, ValidationError


class BundleServiceMixin:
    """Methods for creating and managing product bundles and kits."""

    @staticmethod
    async def create_bundle(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        product_id: UUID,
        name: str,
        bundle_type: str = "bundle",
        lines: list[dict[str, Any]],
    ) -> ProductBundle:
        """Create a new bundle or kit with component lines."""
        if bundle_type not in ("bundle", "kit"):
            raise ValidationError(f"invalid bundle_type: {bundle_type!r}")

        name_clean = (name or "").strip()
        if not name_clean:
            raise ValidationError("bundle name cannot be empty")

        if not lines:
            raise ValidationError("a bundle must have at least one component line")

        # Verify product exists
        prod = (
            await session.execute(
                select(Product).where(Product.tenant_id == tenant_id, Product.id == product_id)
            )
        ).scalar_one_or_none()
        if prod is None:
            raise NotFoundError("product not found")

        # Validate variant lines
        seen_variants = set()
        clean_lines = []
        for idx, line in enumerate(lines):
            var_id = UUID(str(line["variant_id"]))
            if var_id in seen_variants:
                raise ConflictError(f"variant {var_id} specified more than once in bundle")
            seen_variants.add(var_id)

            qty = int(line.get("quantity", 0))
            if qty <= 0:
                raise ValidationError(f"line {idx}: quantity must be positive")

            # Verify variant exists
            var = (
                await session.execute(
                    select(ProductVariant).where(
                        ProductVariant.tenant_id == tenant_id,
                        ProductVariant.id == var_id,
                    )
                )
            ).scalar_one_or_none()
            if var is None:
                raise NotFoundError(f"variant {var_id} not found")

            clean_lines.append({"variant_id": var_id, "quantity": qty})

        bundle = ProductBundle(
            tenant_id=tenant_id,
            product_id=product_id,
            name=name_clean,
            bundle_type=bundle_type,
            is_active=True,
        )
        session.add(bundle)
        await session.flush()

        for cl in clean_lines:
            b_line = ProductBundleLine(
                tenant_id=tenant_id,
                bundle_id=bundle.id,
                variant_id=cl["variant_id"],
                quantity=cl["quantity"],
            )
            session.add(b_line)

        await session.flush()
        return bundle

    @staticmethod
    async def get_bundle(
        session: AsyncSession, tenant_id: UUID, bundle_id: UUID
    ) -> ProductBundle | None:
        """Fetch bundle by ID."""
        return (
            await session.execute(
                select(ProductBundle).where(
                    ProductBundle.tenant_id == tenant_id, ProductBundle.id == bundle_id
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get_bundle_lines(
        session: AsyncSession, tenant_id: UUID, bundle_id: UUID
    ) -> list[ProductBundleLine]:
        """Fetch all component lines of a bundle."""
        return list(
            (
                await session.execute(
                    select(ProductBundleLine).where(
                        ProductBundleLine.tenant_id == tenant_id,
                        ProductBundleLine.bundle_id == bundle_id,
                    )
                )
            ).scalars()
        )

    @staticmethod
    async def list_bundles(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        product_id: UUID | None = None,
        active_only: bool = True,
    ) -> list[ProductBundle]:
        """List bundles for a tenant, optionally filtered by product."""
        q = select(ProductBundle).where(ProductBundle.tenant_id == tenant_id)
        if product_id:
            q = q.where(ProductBundle.product_id == product_id)
        if active_only:
            q = q.where(ProductBundle.is_active.is_(True))
        return list((await session.execute(q)).scalars())
