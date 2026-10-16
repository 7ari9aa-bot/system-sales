"""Stock movement and ledger entry services for InventoryService."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ValidationError
from app.modules.inventory.models import (
    InventoryBalance,
    InventoryMovement,
    InventoryReservation,
)
from ._common import (
    MOVEMENT_REASONS,
    RESERVATION_REFERENCE,
    _AVAILABILITY_DIRECTIONS,
    InsufficientStockError,
    _positive_int,
    check_movement_shape,
)
from .balances import BalanceServiceMixin


class MovementServiceMixin:
    """Stock movements, physical & availability ledger writes, and reservation holds."""

    # ------------------------------------------------------------- move ----

    @staticmethod
    async def move(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
        *,
        direction: str,
        quantity: int,
        reason: str,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> InventoryMovement:
        """Apply a stock movement and append its ledger row.

        - in:     on_hand += quantity
        - out:    on_hand -= quantity (InsufficientStockError below zero)
        - adjust: on_hand = quantity (absolute count, e.g. stocktake)

        The `hold`/`release` availability rows are NOT written here: a hold that
        did not move `reserved` would be a ledger lie, so they come from
        reserve()/release() only.
        """
        check_movement_shape(direction, reason)
        if direction in _AVAILABILITY_DIRECTIONS:
            raise ValidationError(
                f"direction {direction!r} is a reservation row: write it with "
                "reserve()/release(), which moves the balance as well"
            )
        quantity = _positive_int(quantity)

        await BalanceServiceMixin._get_variant(session, tenant_id, variant_id)
        await BalanceServiceMixin._get_warehouse(session, tenant_id, warehouse_id)
        balance = await BalanceServiceMixin._locked_balance(
            session, tenant_id, variant_id, warehouse_id
        )

        if direction == "in":
            new_on_hand = balance.on_hand + quantity
        elif direction == "out":
            new_on_hand = balance.on_hand - quantity
            if new_on_hand < 0:
                raise InsufficientStockError(
                    f"insufficient stock for variant {variant_id} in warehouse "
                    f"{warehouse_id}: on_hand={balance.on_hand}, out={quantity}"
                )
        else:  # adjust — set the absolute position
            new_on_hand = quantity

        balance.on_hand = new_on_hand
        return await MovementServiceMixin._append(
            session,
            tenant_id,
            variant_id,
            warehouse_id,
            direction=direction,
            quantity=quantity,
            reason=reason,
            balance_after=new_on_hand,
            reference_type=reference_type,
            reference_id=reference_id,
        )

    @staticmethod
    async def _append(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
        *,
        direction: str,
        quantity: int,
        reason: str,
        balance_after: int,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> InventoryMovement:
        """Append one ledger row (the single writer of the append-only ledger)."""
        check_movement_shape(direction, reason)
        movement = InventoryMovement(
            tenant_id=tenant_id,
            variant_id=variant_id,
            warehouse_id=warehouse_id,
            direction=direction,
            quantity=quantity,
            reason=reason,
            reference_type=reference_type,
            reference_id=reference_id,
            balance_after=balance_after,
        )
        session.add(movement)
        await session.flush()
        return movement

    # --------------------------------------------------- reserve/release ----

    @staticmethod
    async def reserve(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
        quantity: int,
    ) -> InventoryBalance:
        """Hold stock for an order: on_hand - reserved must cover quantity."""
        quantity = _positive_int(quantity)
        await BalanceServiceMixin._get_variant(session, tenant_id, variant_id)
        await BalanceServiceMixin._get_warehouse(session, tenant_id, warehouse_id)
        balance = await BalanceServiceMixin._locked_balance(
            session, tenant_id, variant_id, warehouse_id
        )

        available = balance.on_hand - balance.reserved
        if available < quantity:
            raise InsufficientStockError(
                f"cannot reserve {quantity} of variant {variant_id} in warehouse "
                f"{warehouse_id}: on_hand={balance.on_hand}, "
                f"reserved={balance.reserved}, available={available}"
            )
        balance.reserved += quantity
        await MovementServiceMixin._append(
            session,
            tenant_id,
            variant_id,
            warehouse_id,
            direction="hold",
            quantity=quantity,
            reason="reservation",
            balance_after=balance.on_hand,
        )
        await session.flush()
        return balance

    @staticmethod
    async def release(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
        quantity: int,
    ) -> InventoryBalance:
        """Give reserved stock back; never drops reserved below zero."""
        quantity = _positive_int(quantity)
        await BalanceServiceMixin._get_variant(session, tenant_id, variant_id)
        await BalanceServiceMixin._get_warehouse(session, tenant_id, warehouse_id)
        balance = await BalanceServiceMixin._locked_balance(
            session, tenant_id, variant_id, warehouse_id
        )

        freed = min(quantity, balance.reserved)
        if freed == 0:
            return balance
        balance.reserved -= freed
        await MovementServiceMixin._append_release(
            session,
            tenant_id,
            variant_id,
            warehouse_id,
            quantity=freed,
            balance_after=balance.on_hand,
        )
        await session.flush()
        return balance

    @staticmethod
    async def _append_release(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
        *,
        quantity: int,
        balance_after: int,
        reservation: InventoryReservation | None = None,
    ) -> InventoryMovement:
        """Append the `release` row for `quantity` units of held stock."""
        target = reservation or await MovementServiceMixin._pair_release_with_reservation(
            session, tenant_id, variant_id, warehouse_id
        )
        return await MovementServiceMixin._append(
            session,
            tenant_id,
            variant_id,
            warehouse_id,
            direction="release",
            quantity=quantity,
            reason="reservation_release",
            balance_after=balance_after,
            reference_type=RESERVATION_REFERENCE if target else None,
            reference_id=target.id if target else None,
        )

    @staticmethod
    async def _pair_release_with_reservation(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
    ) -> InventoryReservation | None:
        """The ACTIVE reservation this release belongs to, oldest first."""
        candidates = list(
            (
                await session.execute(
                    select(InventoryReservation)
                    .where(
                        InventoryReservation.tenant_id == tenant_id,
                        InventoryReservation.variant_id == variant_id,
                        InventoryReservation.warehouse_id == warehouse_id,
                        InventoryReservation.status == "ACTIVE",
                    )
                    .order_by(
                        InventoryReservation.created_at.asc(),
                        InventoryReservation.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not candidates:
            return None
        released = dict(
            (
                await session.execute(
                    select(
                        InventoryMovement.reference_id,
                        func.sum(InventoryMovement.quantity),
                    )
                    .where(
                        InventoryMovement.tenant_id == tenant_id,
                        InventoryMovement.reason == "reservation_release",
                        InventoryMovement.reference_type == RESERVATION_REFERENCE,
                        InventoryMovement.reference_id.in_([r.id for r in candidates]),
                    )
                    .group_by(InventoryMovement.reference_id)
                )
            ).all()
        )
        for reservation in candidates:
            if int(released.get(reservation.id) or 0) < reservation.quantity:
                return reservation
        return None

    @staticmethod
    async def list_movements(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID | None = None,
        *,
        reason: str | None = None,
        reservation_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InventoryMovement]:
        """Ledger, newest first — one variant, or the whole tenant's when None."""
        stmt = select(InventoryMovement).where(InventoryMovement.tenant_id == tenant_id)
        if variant_id is not None:
            stmt = stmt.where(InventoryMovement.variant_id == variant_id)
        if reason is not None:
            if reason not in MOVEMENT_REASONS:
                raise ValidationError(
                    f"reason must be one of {sorted(MOVEMENT_REASONS)}",
                    details={"reason": reason},
                )
            stmt = stmt.where(InventoryMovement.reason == reason)
        if reservation_id is not None:
            hold_movement_id = (
                await session.execute(
                    select(InventoryReservation.hold_movement_id).where(
                        InventoryReservation.tenant_id == tenant_id,
                        InventoryReservation.id == reservation_id,
                    )
                )
            ).scalar_one_or_none()
            linked = [
                and_(
                    InventoryMovement.reference_type == RESERVATION_REFERENCE,
                    InventoryMovement.reference_id == reservation_id,
                )
            ]
            if hold_movement_id is not None:
                linked.append(InventoryMovement.id == hold_movement_id)
            stmt = stmt.where(or_(*linked))
        stmt = (
            stmt.order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    async def create_reservation(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID,
        warehouse_id: UUID,
        order_id: UUID,
        quantity: int,
        expires_at: datetime,
    ) -> None:
        """Create a durable reservation row (§140) — cross-module safe (§8)."""
        reservation = InventoryReservation(
            tenant_id=tenant_id,
            variant_id=variant_id,
            warehouse_id=warehouse_id,
            order_id=order_id,
            quantity=quantity,
            status="ACTIVE",
            expires_at=expires_at,
        )
        session.add(reservation)
        reservation.hold_movement_id = await MovementServiceMixin._unclaimed_hold(
            session, tenant_id, variant_id, warehouse_id, quantity
        )
        await session.flush()

    @staticmethod
    async def _unclaimed_hold(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
        quantity: int,
    ) -> UUID | None:
        """The oldest `hold` row not yet owned by a reservation, or None."""
        claimed = select(InventoryReservation.hold_movement_id).where(
            InventoryReservation.tenant_id == tenant_id,
            InventoryReservation.hold_movement_id.is_not(None),
        )
        return (
            await session.execute(
                select(InventoryMovement.id)
                .where(
                    InventoryMovement.tenant_id == tenant_id,
                    InventoryMovement.variant_id == variant_id,
                    InventoryMovement.warehouse_id == warehouse_id,
                    InventoryMovement.reason == "reservation",
                    InventoryMovement.quantity == quantity,
                    ~InventoryMovement.id.in_(claimed),
                )
                .order_by(InventoryMovement.created_at.asc(), InventoryMovement.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
