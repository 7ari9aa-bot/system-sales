"""Lifecycle of durable inventory reservation rows (spec §140)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.models import InventoryReservation
from ._common import _now, check_physical_settlement
from .balances import BalanceServiceMixin
from .movements import MovementServiceMixin


class InventoryReservationService:
    """Lifecycle of the durable reservation rows (spec §140).

    Rows are created by OrderService.create_order next to the balance hold;
    CONVERTED on payment capture, CANCELLED on order cancellation, EXPIRED by
    the maintenance worker. Only ACTIVE reservations count against
    availability (the balances are the operational truth).
    """

    @staticmethod
    async def convert(session: AsyncSession, tenant_id: UUID, order_id: UUID) -> int:
        """Mark the order's ACTIVE reservations CONVERTED (payment captured)."""
        reservations = (
            (
                await session.execute(
                    select(InventoryReservation)
                    .where(
                        InventoryReservation.tenant_id == tenant_id,
                        InventoryReservation.order_id == order_id,
                        InventoryReservation.status == "ACTIVE",
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )

        for reservation in reservations:
            balance = await BalanceServiceMixin._locked_balance(
                session, tenant_id, reservation.variant_id, reservation.warehouse_id
            )
            sold = check_physical_settlement(
                on_hand=balance.on_hand,
                quantity=reservation.quantity,
                variant_id=reservation.variant_id,
                warehouse_id=reservation.warehouse_id,
                context=f"converting reservation {reservation.id} for order {order_id}",
            )
            freed = min(balance.reserved, reservation.quantity)
            balance.reserved -= freed
            balance.on_hand -= sold
            if freed:
                await MovementServiceMixin._append_release(
                    session,
                    tenant_id,
                    reservation.variant_id,
                    reservation.warehouse_id,
                    quantity=freed,
                    balance_after=balance.on_hand,
                    reservation=reservation,
                )
            await MovementServiceMixin._append(
                session,
                tenant_id,
                reservation.variant_id,
                reservation.warehouse_id,
                direction="out",
                quantity=sold,
                reason="sale",
                balance_after=balance.on_hand,
                reference_type="order",
                reference_id=order_id,
            )
            reservation.status = "CONVERTED"
            reservation.converted_at = _now()
        return len(reservations)

    @staticmethod
    async def cancel_for_order(session: AsyncSession, tenant_id: UUID, order_id: UUID) -> int:
        """Mark the order's ACTIVE reservations CANCELLED (order cancelled).

        The balance-level stock release itself stays the caller's job
        (InventoryService.release) — this only flips the durable rows.
        """
        result = await session.execute(
            update(InventoryReservation)
            .where(
                InventoryReservation.tenant_id == tenant_id,
                InventoryReservation.order_id == order_id,
                InventoryReservation.status == "ACTIVE",
            )
            .values(status="CANCELLED", cancelled_at=_now())
        )
        return result.rowcount or 0

    @staticmethod
    async def expire_stale(session: AsyncSession, tenant_id: UUID) -> int:
        """Expire past-TTL ACTIVE reservations and release their holds."""
        reservations = (
            (
                await session.execute(
                    select(InventoryReservation)
                    .where(
                        InventoryReservation.tenant_id == tenant_id,
                        InventoryReservation.status == "ACTIVE",
                        InventoryReservation.expires_at.is_not(None),
                        InventoryReservation.expires_at < _now(),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )

        for reservation in reservations:
            balance = await BalanceServiceMixin._locked_balance(
                session, tenant_id, reservation.variant_id, reservation.warehouse_id
            )
            freed = min(balance.reserved, reservation.quantity)
            balance.reserved -= freed
            if freed:
                await MovementServiceMixin._append_release(
                    session,
                    tenant_id,
                    reservation.variant_id,
                    reservation.warehouse_id,
                    quantity=freed,
                    balance_after=balance.on_hand,
                    reservation=reservation,
                )
            reservation.status = "EXPIRED"
            reservation.cancelled_at = _now()
        return len(reservations)
