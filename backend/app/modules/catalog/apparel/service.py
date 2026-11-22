"""Create and read a garment's size x colour matrix through the catalog's own variant services.

No new tables: a matrix is the product's existing option axes (size, colour) and one variant per
combination. This writes them in one transaction (all of the garment's missing combinations or none
of them) and never touches a variant that already exists, so adding a colour to last season's
shirt does not disturb the sizes already on the shelf.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.apparel.matrix import (
    Cell,
    build_matrix,
    color_of,
    size_of,
    size_sort_key,
)
from app.modules.catalog.models import ProductVariant
from app.modules.catalog.services._common import _positive_decimal
from app.modules.errors import ConflictError, ValidationError


@dataclass(frozen=True, slots=True)
class MatrixResult:
    created: list[ProductVariant]
    skipped: list[str]  # SKUs that already existed on THIS product, left exactly as they were


class ApparelMatrixService:
    @staticmethod
    async def generate(
        session: AsyncSession,
        tenant_id: UUID,
        product_id: UUID,
        *,
        sizes: list[object],
        colors: list[object],
        price: object,
        sku_prefix: str,
        color_codes: dict[str, str] | None = None,
    ) -> MatrixResult:
        """Add every missing size x colour variant of ``product_id``.

        A combination that already exists on this product (same size and colour) is skipped and
        reported, not duplicated and not edited. A SKU that belongs to ANOTHER product is a
        conflict and nothing at all is written.
        """
        from app.modules.catalog.services import CatalogService

        await CatalogService.get_product(session, tenant_id, product_id)
        # the price is checked up front: a bad one must refuse the whole garment before a single
        # variant exists, and as a ValidationError (a 422), not the bare ValueError the catalog's
        # own helper raises for internal callers
        try:
            _positive_decimal(price, "price")
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        cells = build_matrix(
            sizes=sizes, colors=colors, sku_prefix=sku_prefix, color_codes=color_codes
        )

        existing = await ApparelMatrixService._existing(session, tenant_id, product_id)
        have = {(size_of(v.option_values), color_of(v.option_values)) for v in existing}
        todo = [c for c in cells if (c.size, c.color) not in have]
        skipped = [c.sku for c in cells if (c.size, c.color) in have]

        if todo:
            taken = (
                (
                    await session.execute(
                        select(ProductVariant.sku).where(
                            ProductVariant.tenant_id == tenant_id,
                            ProductVariant.sku.in_([c.sku for c in todo]),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if taken:
                # decided BEFORE the first write, so a refusal leaves the garment untouched
                raise ConflictError(
                    f"these SKUs already belong to another variant: {sorted(taken)}. "
                    "Pick another sku_prefix."
                )

        created: list[ProductVariant] = []
        for cell in todo:
            created.append(
                await CatalogService.add_variant(
                    session,
                    tenant_id,
                    product_id,
                    sku=cell.sku,
                    title=f"{cell.color} / {cell.size}",
                    option_values=dict(cell.option_values),
                    price=price,
                )
            )
        return MatrixResult(created=created, skipped=skipped)

    @staticmethod
    async def _existing(
        session: AsyncSession, tenant_id: UUID, product_id: UUID
    ) -> list[ProductVariant]:
        return list(
            (
                await session.execute(
                    select(ProductVariant).where(
                        ProductVariant.tenant_id == tenant_id,
                        ProductVariant.product_id == product_id,
                    )
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    async def view(session: AsyncSession, tenant_id: UUID, product_id: UUID) -> dict:
        """The garment as a grid: colours down, sizes across, the sellable stock in each cell.

        ``available`` is on hand minus quarantined minus reserved, summed over warehouses. An
        oversold variant shows its negative figure, not a reassuring 0. A size and colour that was
        never created is absent from its row (a gap in the grid), which is different from one
        created with nothing in stock (0).
        """
        from app.modules.catalog.services import CatalogService
        from app.modules.inventory.service import InventoryService

        await CatalogService.get_product(session, tenant_id, product_id)
        variants = await ApparelMatrixService._existing(session, tenant_id, product_id)
        ids = [v.id for v in variants]
        stock = await InventoryService.available_for_many(session, tenant_id, ids)

        sizes: set[str] = set()
        colors: list[str] = []
        grid: dict[str, dict[str, dict]] = {}
        for v in sorted(variants, key=lambda v: v.created_at):
            size = size_of(v.option_values)
            color = color_of(v.option_values)
            if size is None or color is None:
                continue  # a variant outside the matrix (a plain one-size item) is not on the grid
            sizes.add(size)
            if color not in grid:
                colors.append(color)
                grid[color] = {}
            grid[color][size] = {
                "variant_id": str(v.id),
                "sku": v.sku,
                "price": str(Decimal(str(v.price))),
                "active": bool(v.is_active),
                "available": stock.get(v.id, 0),
            }
        ordered = sorted(sizes, key=size_sort_key)
        return {
            "sizes": ordered,
            "colors": colors,
            "cells": grid,
            "total_available": sum(c["available"] for row in grid.values() for c in row.values()),
        }


__all__ = ["ApparelMatrixService", "Cell", "MatrixResult"]
