"""Traceability Service: Lots, Serials, Expiry, and Tracking Policies (§4 Phase 6, M2).

Supports:
- Per-variant tracking policies (none | batch | serial)
- Batch/Lot tracking with expiry dates and FEFO ordering
- Serial number tracking unit-by-unit with lifecycle status
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.applications.apparel.modules.inventory.models import (
    InventoryLot,
    InventorySerial,
    VariantTrackingPolicy,
)
from app.applications.apparel.modules.inventory.services.balances import BalanceServiceMixin


class TraceabilityService:
    """Manages lot tracking, serial numbers, and expiry compliance."""

    # --------------------------------------------------- Policies -----------

    @staticmethod
    async def set_tracking_policy(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID,
        mode: str = "none",
        expiry_required: bool = False,
    ) -> VariantTrackingPolicy:
        """Configure how a variant is tracked."""
        if mode not in ("none", "batch", "serial"):
            raise ValidationError(f"invalid tracking mode: {mode!r}")

        await BalanceServiceMixin._get_variant(session, tenant_id, variant_id)

        policy = (
            await session.execute(
                select(VariantTrackingPolicy).where(
                    VariantTrackingPolicy.tenant_id == tenant_id,
                    VariantTrackingPolicy.variant_id == variant_id,
                )
            )
        ).scalar_one_or_none()

        if policy is None:
            policy = VariantTrackingPolicy(
                tenant_id=tenant_id,
                variant_id=variant_id,
                mode=mode,
                expiry_required=expiry_required,
            )
            session.add(policy)
        else:
            policy.mode = mode
            policy.expiry_required = expiry_required

        await session.flush()
        return policy

    @staticmethod
    async def get_tracking_policy(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID,
    ) -> VariantTrackingPolicy | None:
        """Fetch tracking policy for a variant."""
        return (
            await session.execute(
                select(VariantTrackingPolicy).where(
                    VariantTrackingPolicy.tenant_id == tenant_id,
                    VariantTrackingPolicy.variant_id == variant_id,
                )
            )
        ).scalar_one_or_none()

    # --------------------------------------------------- Lots / Batches -----

    @staticmethod
    async def create_lot(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID,
        lot_code: str,
        expires_at: datetime | None = None,
        supplier_id: UUID | None = None,
        unit_cost: Decimal | str | float | None = None,
        received_at: datetime | None = None,
    ) -> InventoryLot:
        """Register a new batch/lot for a variant."""
        code_clean = (lot_code or "").strip()
        if not code_clean:
            raise ValidationError("lot_code cannot be empty")

        policy = await TraceabilityService.get_tracking_policy(
            session, tenant_id, variant_id=variant_id
        )
        if policy and policy.expiry_required and expires_at is None:
            raise ValidationError(
                f"expiry date is required for variant {variant_id} per tracking policy"
            )

        existing = (
            await session.execute(
                select(InventoryLot).where(
                    InventoryLot.tenant_id == tenant_id,
                    InventoryLot.variant_id == variant_id,
                    InventoryLot.lot_code == code_clean,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(f"lot_code {code_clean!r} already exists for this variant")

        cost = (
            Decimal(str(unit_cost)).quantize(Decimal("0.0001")) if unit_cost is not None else None
        )

        lot = InventoryLot(
            tenant_id=tenant_id,
            variant_id=variant_id,
            lot_code=code_clean,
            expires_at=expires_at,
            supplier_id=supplier_id,
            unit_cost=cost,
            received_at=received_at or datetime.now(UTC),
        )
        session.add(lot)
        await session.flush()
        return lot

    @staticmethod
    async def get_lot(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        lot_id: UUID,
    ) -> InventoryLot | None:
        return (
            await session.execute(
                select(InventoryLot).where(
                    InventoryLot.tenant_id == tenant_id, InventoryLot.id == lot_id
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_lots(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID | None = None,
        expiring_before: datetime | None = None,
    ) -> list[InventoryLot]:
        """List lots ordered by expires_at ASC (FEFO: First Expired First Out)."""
        q = select(InventoryLot).where(InventoryLot.tenant_id == tenant_id)
        if variant_id:
            q = q.where(InventoryLot.variant_id == variant_id)
        if expiring_before:
            q = q.where(InventoryLot.expires_at <= expiring_before)
        q = q.order_by(InventoryLot.expires_at.asc().nulls_last(), InventoryLot.received_at.asc())
        return list((await session.execute(q)).scalars())

    # --------------------------------------------------- Serials ------------

    @staticmethod
    async def register_serials(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID,
        serial_codes: list[str],
        lot_id: UUID | None = None,
    ) -> list[InventorySerial]:
        """Register individually tracked units by serial number."""
        if not serial_codes:
            raise ValidationError("must provide at least one serial code")

        clean_codes = [c.strip() for c in serial_codes if c.strip()]
        if len(clean_codes) != len(set(clean_codes)):
            raise ConflictError("duplicate serial codes in input")

        # Check existing serials
        existing = list(
            (
                await session.execute(
                    select(InventorySerial.serial_code).where(
                        InventorySerial.tenant_id == tenant_id,
                        InventorySerial.variant_id == variant_id,
                        InventorySerial.serial_code.in_(clean_codes),
                    )
                )
            ).scalars()
        )
        if existing:
            raise ConflictError(f"serial codes already registered: {existing}")

        serials = []
        for code in clean_codes:
            serial = InventorySerial(
                tenant_id=tenant_id,
                variant_id=variant_id,
                serial_code=code,
                lot_id=lot_id,
                status="in_stock",
            )
            session.add(serial)
            serials.append(serial)

        await session.flush()
        return serials

    @staticmethod
    async def update_serial_status(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID,
        serial_code: str,
        status: str,
    ) -> InventorySerial:
        """Update status of a serial unit (e.g. in_stock -> sold | returned | damaged)."""
        if status not in ("in_stock", "quarantined", "sold", "returned", "damaged"):
            raise ValidationError(f"invalid serial status: {status!r}")

        serial = (
            await session.execute(
                select(InventorySerial)
                .where(
                    InventorySerial.tenant_id == tenant_id,
                    InventorySerial.variant_id == variant_id,
                    InventorySerial.serial_code == serial_code.strip(),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if serial is None:
            raise NotFoundError(f"serial {serial_code!r} not found for this variant")

        serial.status = status
        await session.flush()
        return serial

    @staticmethod
    async def list_serials(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID | None = None,
        status: str | None = None,
        lot_id: UUID | None = None,
    ) -> list[InventorySerial]:
        """List serial units by variant, status, or lot."""
        q = select(InventorySerial).where(InventorySerial.tenant_id == tenant_id)
        if variant_id:
            q = q.where(InventorySerial.variant_id == variant_id)
        if status:
            q = q.where(InventorySerial.status == status)
        if lot_id:
            q = q.where(InventorySerial.lot_id == lot_id)
        return list((await session.execute(q)).scalars())
