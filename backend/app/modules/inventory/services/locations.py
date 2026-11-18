"""Warehouse internal locations and relocation service (D4, §4 Phase 3).

Warehouse locations are physical places inside a warehouse:
    zones, racks, shelves, bins, and functional areas (receiving, qc, storage,
    picking, packing, returns, quarantine, damaged).

Relocating stock between locations inside the SAME warehouse:
  - does NOT change warehouse on_hand
  - does NOT write an in/out ledger row
  - writes an append-only row in `inventory_location_movements`
  - enforces the invariant: sum(location_balances) <= warehouse.on_hand
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.inventory.models import (
    InventoryLocationBalance,
    InventoryLocationMovement,
    WarehouseLocation,
)
from app.modules.inventory.services.balances import BalanceServiceMixin

_VALID_LOCATION_KINDS = frozenset(
    {
        "receiving",
        "qc",
        "storage",
        "picking",
        "packing",
        "returns",
        "quarantine",
        "damaged",
        "zone",
        "rack",
        "shelf",
        "bin",
    }
)
_VALID_MOVEMENT_REASONS = frozenset(
    {"putaway", "replenishment", "pick", "transfer", "adjustment", "relocation"}
)


class WarehouseLocationService:
    """Internal warehouse storage layout and relocation workflows."""

    # ----------------------------------------------------- location CRUD --

    @staticmethod
    async def create_location(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        code: str,
        name: str,
        kind: str,
        parent_id: UUID | None = None,
        capacity: int | None = None,
        notes: str | None = None,
    ) -> WarehouseLocation:
        """Create a new bin, shelf, rack, zone, or functional area."""
        await BalanceServiceMixin._get_warehouse(session, tenant_id, warehouse_id)

        kind_clean = kind.lower().strip()
        if kind_clean not in _VALID_LOCATION_KINDS:
            raise ValidationError(
                f"kind must be one of {sorted(_VALID_LOCATION_KINDS)}",
                details={"kind": kind},
            )
        code_clean = code.strip().upper()
        if not code_clean:
            raise ValidationError("code is required")

        if parent_id:
            parent = (
                await session.execute(
                    select(WarehouseLocation).where(
                        WarehouseLocation.tenant_id == tenant_id,
                        WarehouseLocation.warehouse_id == warehouse_id,
                        WarehouseLocation.id == parent_id,
                    )
                )
            ).scalar_one_or_none()
            if parent is None:
                raise NotFoundError(f"parent location {parent_id} not found in this warehouse")

        existing = (
            await session.execute(
                select(WarehouseLocation.id).where(
                    WarehouseLocation.tenant_id == tenant_id,
                    WarehouseLocation.warehouse_id == warehouse_id,
                    WarehouseLocation.code == code_clean,
                )
            )
        ).first()
        if existing:
            raise ConflictError(f"location code '{code_clean}' already exists in this warehouse")

        loc = WarehouseLocation(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            code=code_clean,
            name=name.strip(),
            kind=kind_clean,
            parent_id=parent_id,
            capacity=capacity if (capacity is not None and capacity >= 0) else None,
            notes=(notes or "").strip() or None,
            is_active=True,
        )
        session.add(loc)
        await session.flush()
        return loc

    @staticmethod
    async def get_location(
        session: AsyncSession, tenant_id: UUID, location_id: UUID
    ) -> WarehouseLocation:
        loc = (
            await session.execute(
                select(WarehouseLocation).where(
                    WarehouseLocation.tenant_id == tenant_id,
                    WarehouseLocation.id == location_id,
                )
            )
        ).scalar_one_or_none()
        if loc is None:
            raise NotFoundError(f"location {location_id} not found")
        return loc

    @staticmethod
    async def list_locations(
        session: AsyncSession,
        tenant_id: UUID,
        warehouse_id: UUID,
        *,
        kind: str | None = None,
        is_active: bool = True,
    ) -> list[WarehouseLocation]:
        q = select(WarehouseLocation).where(
            WarehouseLocation.tenant_id == tenant_id,
            WarehouseLocation.warehouse_id == warehouse_id,
            WarehouseLocation.is_active == is_active,
        )
        if kind:
            q = q.where(WarehouseLocation.kind == kind.lower().strip())
        q = q.order_by(WarehouseLocation.code)
        return list((await session.execute(q)).scalars())

    # ------------------------------------------------ location balances --

    @staticmethod
    async def get_location_balance(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        location_id: UUID,
        variant_id: UUID,
    ) -> InventoryLocationBalance:
        bal = (
            await session.execute(
                select(InventoryLocationBalance).where(
                    InventoryLocationBalance.tenant_id == tenant_id,
                    InventoryLocationBalance.warehouse_id == warehouse_id,
                    InventoryLocationBalance.location_id == location_id,
                    InventoryLocationBalance.variant_id == variant_id,
                )
            )
        ).scalar_one_or_none()
        if bal is not None:
            return bal

        # Insert 0-row
        await session.execute(
            pg_insert(InventoryLocationBalance)
            .values(
                tenant_id=tenant_id,
                warehouse_id=warehouse_id,
                location_id=location_id,
                variant_id=variant_id,
                on_hand=0,
            )
            .on_conflict_do_nothing(constraint="uq_inv_location_balances_position")
        )
        return (
            await session.execute(
                select(InventoryLocationBalance).where(
                    InventoryLocationBalance.tenant_id == tenant_id,
                    InventoryLocationBalance.warehouse_id == warehouse_id,
                    InventoryLocationBalance.location_id == location_id,
                    InventoryLocationBalance.variant_id == variant_id,
                )
            )
        ).scalar_one()

    @staticmethod
    async def _locked_location_balance(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        location_id: UUID,
        variant_id: UUID,
    ) -> InventoryLocationBalance:
        await WarehouseLocationService.get_location_balance(
            session,
            tenant_id,
            warehouse_id=warehouse_id,
            location_id=location_id,
            variant_id=variant_id,
        )
        return (
            await session.execute(
                select(InventoryLocationBalance)
                .where(
                    InventoryLocationBalance.tenant_id == tenant_id,
                    InventoryLocationBalance.warehouse_id == warehouse_id,
                    InventoryLocationBalance.location_id == location_id,
                    InventoryLocationBalance.variant_id == variant_id,
                )
                .with_for_update()
            )
        ).scalar_one()

    # ------------------------------------------------------- relocation --

    @staticmethod
    async def putaway(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        variant_id: UUID,
        to_location_id: UUID,
        quantity: int,
        user_id: UUID | None = None,
    ) -> InventoryLocationMovement:
        """Place incoming stock from general warehouse space into a specific location."""
        return await WarehouseLocationService.relocate(
            session,
            tenant_id,
            warehouse_id=warehouse_id,
            variant_id=variant_id,
            from_location_id=None,
            to_location_id=to_location_id,
            quantity=quantity,
            reason="putaway",
            user_id=user_id,
        )

    @staticmethod
    async def relocate(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        variant_id: UUID,
        from_location_id: UUID | None,
        to_location_id: UUID | None,
        quantity: int,
        reason: str = "relocation",
        user_id: UUID | None = None,
    ) -> InventoryLocationMovement:
        """Move stock between locations within the same warehouse.

        Does NOT alter warehouse on_hand; maintains the invariant that sum of
        location balances <= warehouse.on_hand.
        """
        if quantity <= 0:
            raise ValidationError("quantity must be greater than zero")
        if from_location_id == to_location_id and from_location_id is not None:
            raise ValidationError("source and destination location must differ")
        if from_location_id is None and to_location_id is None:
            raise ValidationError("at least one of from_location_id or to_location_id is required")
        if reason not in _VALID_MOVEMENT_REASONS:
            raise ValidationError(f"reason must be one of {sorted(_VALID_MOVEMENT_REASONS)}")

        # Check warehouse & variant
        await BalanceServiceMixin._get_warehouse(session, tenant_id, warehouse_id)
        await BalanceServiceMixin._get_variant(session, tenant_id, variant_id)

        # Lock warehouse balance to check invariant
        wh_balance = await BalanceServiceMixin._locked_balance(
            session, tenant_id, variant_id, warehouse_id
        )

        # From location
        if from_location_id:
            from_loc = await WarehouseLocationService.get_location(
                session, tenant_id, from_location_id
            )
            if from_loc.warehouse_id != warehouse_id:
                raise ValidationError(
                    f"source location {from_location_id} belongs to warehouse "
                    f"{from_loc.warehouse_id}, not {warehouse_id}"
                )
            from_bal = await WarehouseLocationService._locked_location_balance(
                session,
                tenant_id,
                warehouse_id=warehouse_id,
                location_id=from_location_id,
                variant_id=variant_id,
            )
            if from_bal.on_hand < quantity:
                raise ConflictError(
                    f"insufficient stock at source location {from_location_id}: "
                    f"has {from_bal.on_hand}, requested {quantity}"
                )
            from_bal.on_hand -= quantity

        # To location
        if to_location_id:
            to_loc = await WarehouseLocationService.get_location(session, tenant_id, to_location_id)
            if to_loc.warehouse_id != warehouse_id:
                raise ValidationError(
                    f"destination location {to_location_id} belongs to warehouse "
                    f"{to_loc.warehouse_id}, not {warehouse_id}"
                )
            to_bal = await WarehouseLocationService._locked_location_balance(
                session,
                tenant_id,
                warehouse_id=warehouse_id,
                location_id=to_location_id,
                variant_id=variant_id,
            )

            # Check capacity if configured
            if to_loc.capacity is not None and (to_bal.on_hand + quantity) > to_loc.capacity:
                raise ConflictError(
                    f"location {to_loc.code} capacity exceeded: "
                    f"capacity={to_loc.capacity}, current={to_bal.on_hand}, adding={quantity}"
                )
            to_bal.on_hand += quantity

        # Verify overall invariant: sum(location_balances) <= warehouse.on_hand
        total_in_locs = (
            await session.execute(
                select(func.coalesce(func.sum(InventoryLocationBalance.on_hand), 0)).where(
                    InventoryLocationBalance.tenant_id == tenant_id,
                    InventoryLocationBalance.warehouse_id == warehouse_id,
                    InventoryLocationBalance.variant_id == variant_id,
                )
            )
        ).scalar_one()

        if int(total_in_locs) > wh_balance.on_hand:
            raise ConflictError(
                f"invariant violation: total location stock ({total_in_locs}) "
                f"exceeds warehouse on_hand ({wh_balance.on_hand})"
            )

        movement = InventoryLocationMovement(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            variant_id=variant_id,
            quantity=quantity,
            reason=reason,
            moved_by_user_id=user_id,
        )
        session.add(movement)
        await session.flush()
        return movement

    @staticmethod
    async def list_variant_locations(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        variant_id: UUID,
    ) -> list[dict]:
        """List all locations in the warehouse holding stock for this variant."""
        rows = (
            await session.execute(
                select(WarehouseLocation, InventoryLocationBalance.on_hand)
                .join(
                    InventoryLocationBalance,
                    (InventoryLocationBalance.location_id == WarehouseLocation.id)
                    & (InventoryLocationBalance.tenant_id == tenant_id)
                    & (InventoryLocationBalance.variant_id == variant_id),
                )
                .where(
                    WarehouseLocation.tenant_id == tenant_id,
                    WarehouseLocation.warehouse_id == warehouse_id,
                    InventoryLocationBalance.on_hand > 0,
                )
                .order_by(WarehouseLocation.code)
            )
        ).all()
        return [
            {
                "location_id": str(loc.id),
                "code": loc.code,
                "name": loc.name,
                "kind": loc.kind,
                "on_hand": int(qty),
            }
            for loc, qty in rows
        ]
