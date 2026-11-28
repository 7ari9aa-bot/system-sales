"""Quality inspection service — inspect receipts, returns, and transfers (D3, §4 Phase 1).

A quality inspection verifies goods before they enter sellable stock:
  * source_type: goods_receipt | return_receipt | transfer_receipt
  * status: open | passed | quarantined | rejected
  * results: per-variant verdict (pass | quarantine | reject)

Verdicts affect inventory balances:
  * pass: release from quarantine into sellable stock (quarantined -= qty)
  * quarantine: maintain in quarantine (or bump quarantined if not already)
  * reject: remove from on_hand (direction="out", reason="damage") and reduce quarantined

The service flushes, never commits; the caller owns the transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.applications.apparel.modules.inventory.models import (
    InventoryInspectionResult,
    InventoryQualityInspection,
)
from app.applications.apparel.modules.inventory.services.balances import BalanceServiceMixin
from app.applications.apparel.modules.inventory.services.movements import MovementServiceMixin

_VALID_SOURCES = frozenset({"goods_receipt", "return_receipt", "transfer_receipt"})
_VALID_VERDICTS = frozenset({"pass", "quarantine", "reject"})


class QualityInspectionService:
    """Inspection workflows and verdict application for incoming goods."""

    # ---------------------------------------------------------------- create --

    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        source_type: str,
        source_id: UUID | None,
        warehouse_id: UUID,
        note: str | None = None,
        user_id: UUID | None = None,
    ) -> InventoryQualityInspection:
        """Open a new quality inspection document."""
        if source_type not in _VALID_SOURCES:
            raise ValidationError(
                f"source_type must be one of {sorted(_VALID_SOURCES)}",
                details={"source_type": source_type},
            )
        await BalanceServiceMixin._get_warehouse(session, tenant_id, warehouse_id)

        inspection = InventoryQualityInspection(
            tenant_id=tenant_id,
            source_type=source_type,
            source_id=source_id,
            warehouse_id=warehouse_id,
            status="open",
            note=(note or "").strip()[:500] or None,
            inspected_by_user_id=user_id,
        )
        session.add(inspection)
        await session.flush()
        return inspection

    # -------------------------------------------------------- record_result --

    @staticmethod
    async def record_result(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        inspection_id: UUID,
        variant_id: UUID,
        quantity: int,
        verdict: str,
        note: str | None = None,
        user_id: UUID | None = None,
        apply_to_stock: bool = True,
    ) -> InventoryInspectionResult:
        """Record the inspection verdict for one variant and optionally apply to stock.

        When `apply_to_stock` is True:
          - pass: if currently quarantined, moves to sellable (quarantined -= qty)
          - quarantine: ensures the quantity is counted in quarantined
          - reject: if on hand, removes from stock (out / damage) and decrements quarantined
        """
        if verdict not in _VALID_VERDICTS:
            raise ValidationError(
                f"verdict must be one of {sorted(_VALID_VERDICTS)}",
                details={"verdict": verdict},
            )
        if quantity <= 0:
            raise ValidationError("quantity must be greater than zero")

        inspection = (
            await session.execute(
                select(InventoryQualityInspection)
                .where(
                    InventoryQualityInspection.tenant_id == tenant_id,
                    InventoryQualityInspection.id == inspection_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if inspection is None:
            raise NotFoundError("quality inspection not found")
        if inspection.status != "open":
            raise ConflictError(
                f"cannot record results for an inspection that is {inspection.status}"
            )

        await BalanceServiceMixin._get_variant(session, tenant_id, variant_id)

        # Check for duplicate result on same variant
        existing = (
            await session.execute(
                select(InventoryInspectionResult).where(
                    InventoryInspectionResult.tenant_id == tenant_id,
                    InventoryInspectionResult.inspection_id == inspection_id,
                    InventoryInspectionResult.variant_id == variant_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError("a result for this variant has already been recorded")

        # Apply stock movements/counter updates
        if apply_to_stock:
            balance = await BalanceServiceMixin._locked_balance(
                session, tenant_id, variant_id, inspection.warehouse_id
            )

            if verdict == "pass":
                # Release from quarantine into sellable stock
                if balance.quarantined and balance.quarantined > 0:
                    released = min(balance.quarantined, quantity)
                    balance.quarantined -= released

            elif verdict == "quarantine":
                # Ensure marked as quarantined
                balance.quarantined = (balance.quarantined or 0) + quantity

            elif verdict == "reject":
                # Scrapped/damaged goods leaving inventory
                if balance.quarantined and balance.quarantined > 0:
                    from_q = min(balance.quarantined, quantity)
                    balance.quarantined -= from_q
                # Move out of stock if goods were already posted to on_hand
                if balance.on_hand >= quantity:
                    await MovementServiceMixin.move(
                        session,
                        tenant_id,
                        variant_id,
                        inspection.warehouse_id,
                        direction="out",
                        quantity=quantity,
                        reason="damage",
                        reference_type="quality_inspection",
                        reference_id=inspection.id,
                        actor_user_id=user_id,
                        allow_reserved_breach=True,
                    )

        result = InventoryInspectionResult(
            tenant_id=tenant_id,
            inspection_id=inspection_id,
            variant_id=variant_id,
            quantity=quantity,
            verdict=verdict,
            note=(note or "").strip()[:500] or None,
            inspected_by_user_id=user_id,
        )
        session.add(result)
        await session.flush()
        return result

    # ------------------------------------------------------------- complete --

    @staticmethod
    async def complete(
        session: AsyncSession,
        tenant_id: UUID,
        inspection_id: UUID,
        *,
        user_id: UUID | None = None,
        note: str | None = None,
    ) -> InventoryQualityInspection:
        """Finalize the inspection based on recorded verdicts.

        Summary status:
          * all pass → passed
          * any quarantine → quarantined
          * all reject → rejected
        """
        inspection = (
            await session.execute(
                select(InventoryQualityInspection)
                .where(
                    InventoryQualityInspection.tenant_id == tenant_id,
                    InventoryQualityInspection.id == inspection_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if inspection is None:
            raise NotFoundError("quality inspection not found")
        if inspection.status != "open":
            raise ConflictError(f"inspection is already {inspection.status}")

        results = list(
            (
                await session.execute(
                    select(InventoryInspectionResult).where(
                        InventoryInspectionResult.tenant_id == tenant_id,
                        InventoryInspectionResult.inspection_id == inspection_id,
                    )
                )
            ).scalars()
        )
        if not results:
            raise ValidationError("cannot complete an inspection with no recorded results")

        verdicts = {r.verdict for r in results}
        if verdicts == {"pass"}:
            status = "passed"
        elif "quarantine" in verdicts:
            status = "quarantined"
        elif verdicts == {"reject"}:
            status = "rejected"
        else:
            # Mixed pass and reject
            status = "passed"

        inspection.status = status
        inspection.inspected_at = datetime.now(UTC)
        inspection.inspected_by_user_id = user_id
        if note:
            inspection.note = (
                f"{inspection.note}\n{note}".strip() if inspection.note else note.strip()
            )

        await session.flush()
        return inspection

    # ----------------------------------------------------------------- read --

    @staticmethod
    async def get(
        session: AsyncSession, tenant_id: UUID, inspection_id: UUID
    ) -> InventoryQualityInspection:
        inspection = (
            await session.execute(
                select(InventoryQualityInspection).where(
                    InventoryQualityInspection.tenant_id == tenant_id,
                    InventoryQualityInspection.id == inspection_id,
                )
            )
        ).scalar_one_or_none()
        if inspection is None:
            raise NotFoundError("quality inspection not found")
        return inspection

    @staticmethod
    async def results_of(
        session: AsyncSession, tenant_id: UUID, inspection_id: UUID
    ) -> list[InventoryInspectionResult]:
        return list(
            (
                await session.execute(
                    select(InventoryInspectionResult)
                    .where(
                        InventoryInspectionResult.tenant_id == tenant_id,
                        InventoryInspectionResult.inspection_id == inspection_id,
                    )
                    .order_by(InventoryInspectionResult.created_at)
                )
            ).scalars()
        )
