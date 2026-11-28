"""Give stock a scannable barcode of the shop's own, and read back the labels to print.

The number comes from a gap-free counter taken under a row lock in the caller's transaction, so two
people labelling at once never get the same one and a rolled-back batch gives its numbers back. It
is stored as an ordinary ``barcode`` identifier (never ``gtin`` or ``ean``: those mean a number a
manufacturer issued, and the e-invoice needs to tell the two apart).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sequences import next_sequence
from app.applications.apparel.modules.catalog.apparel.barcode import internal_ean13, is_internal
from app.applications.apparel.modules.catalog.models import ProductIdentifier, ProductVariant
from app.modules.errors import ConflictError, NotFoundError, ValidationError

COUNTER_KIND = "BC"
COUNTER_YEAR = 0  # one endless sequence: a barcode must stay unique for the life of the shop
SCAN_TYPES = ("ean", "gtin", "upc", "barcode")  # every kind of code a till can scan
MAX_BATCH = 500


@dataclass(frozen=True, slots=True)
class LabelResult:
    assigned: dict[UUID, str]  # variant -> the barcode it was just given
    already: dict[UUID, str]  # variant -> the code it already had, left untouched


class BarcodeService:
    @staticmethod
    async def _first_code(
        session: AsyncSession, tenant_id: UUID, variant_ids: list[UUID]
    ) -> dict[UUID, str]:
        """The scan code each variant already has (its oldest), for those that have one."""
        rows = (
            await session.execute(
                select(ProductIdentifier)
                .where(
                    ProductIdentifier.tenant_id == tenant_id,
                    ProductIdentifier.variant_id.in_(variant_ids),
                    ProductIdentifier.type.in_(SCAN_TYPES),
                )
                .order_by(ProductIdentifier.created_at, ProductIdentifier.id)
            )
        ).scalars()
        found: dict[UUID, str] = {}
        for row in rows:
            found.setdefault(row.variant_id, row.value)
        return found

    @staticmethod
    async def assign_missing(
        session: AsyncSession, tenant_id: UUID, variant_ids: list[UUID]
    ) -> LabelResult:
        """Give every listed variant that has no scan code one of the shop's own.

        A variant that already has any code (a manufacturer's or an earlier internal one) is left
        exactly as it is and uses no number. All or nothing: a failure rolls the numbers back.
        """
        from app.applications.apparel.modules.catalog.services import CatalogService

        unique = list(dict.fromkeys(variant_ids))
        if not unique:
            raise ValidationError("choose at least one variant")
        if len(unique) > MAX_BATCH:
            raise ValidationError(f"label at most {MAX_BATCH} variants at a time")
        found = (
            (
                await session.execute(
                    select(ProductVariant.id).where(
                        ProductVariant.tenant_id == tenant_id,
                        ProductVariant.id.in_(unique),
                    )
                )
            )
            .scalars()
            .all()
        )
        missing = set(unique) - set(found)
        if missing:
            raise NotFoundError(f"unknown variants: {sorted(str(m) for m in missing)}")

        already = await BarcodeService._first_code(session, tenant_id, unique)
        assigned: dict[UUID, str] = {}
        for variant_id in unique:
            if variant_id in already:
                continue
            sequence = await next_sequence(session, tenant_id, COUNTER_KIND, year=COUNTER_YEAR)
            code = internal_ean13(sequence)
            if not is_internal(code):  # cannot happen; a bad number must never reach a shelf
                raise ConflictError(f"generated an invalid barcode {code!r}")
            await CatalogService.add_identifier(session, tenant_id, variant_id, "barcode", code)
            assigned[variant_id] = code
        return LabelResult(assigned=assigned, already=already)

    @staticmethod
    async def label_rows(
        session: AsyncSession, tenant_id: UUID, product_id: UUID, *, only: list[UUID] | None = None
    ) -> list[dict]:
        """What each label of a garment needs to print: title, size/colour, price and its code.

        Reads only; a variant with no code yet is reported with ``code=None`` so the caller can
        say "label these first" instead of printing a blank. Sold-out or inactive variants are
        included, because a shop labels stock it has just received.
        """
        from app.applications.apparel.modules.catalog.services import CatalogService

        product = await CatalogService.get_product(session, tenant_id, product_id)
        variants = (
            (
                await session.execute(
                    select(ProductVariant)
                    .where(
                        ProductVariant.tenant_id == tenant_id,
                        ProductVariant.product_id == product_id,
                    )
                    .order_by(ProductVariant.created_at, ProductVariant.id)
                )
            )
            .scalars()
            .all()
        )
        if only is not None:
            wanted = set(only)
            unknown = wanted - {v.id for v in variants}
            if unknown:
                raise NotFoundError("some variants do not belong to this product")
            variants = [v for v in variants if v.id in wanted]
        codes = await BarcodeService._first_code(session, tenant_id, [v.id for v in variants])
        rows = []
        for v in variants:
            values = [str(x) for x in (v.option_values or {}).values()]
            rows.append(
                {
                    "variant_id": v.id,
                    "title": product.title,
                    "variant_text": " / ".join(values),
                    "price": v.price,
                    "code": codes.get(v.id),
                }
            )
        return rows
