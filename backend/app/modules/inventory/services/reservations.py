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
    async def convert(
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        actor_user_id: UUID | None = None,
    ) -> int:
        """Mark the order's reservations CONVERTED (payment captured).

        Capture is the ONE place a reservation turns into an ``out``/sale
        movement — whatever the reservation's status was. An ACTIVE hold is
        released and sold as before. But a hold the expiry sweep already
        freed (a COD order paid later than the TTL) is a sale the ledger
        still owes: without this, the goods left while ``on_hand`` never
        moved — phantom stock and oversell, invisible to reconciliation
        because ledger and balance agree on the wrong number.

        Rows already CONVERTED are skipped, so a retry never sells twice.
        An order with NO reservation rows at all keeps the historical
        no-op (legacy orders predate the machinery).
        """
        rows = (
            (
                await session.execute(
                    select(InventoryReservation)
                    .where(
                        InventoryReservation.tenant_id == tenant_id,
                        InventoryReservation.order_id == order_id,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        pending = [r for r in rows if r.status != "CONVERTED"]
        if not pending:
            return 0

        # Aggregate demand per (variant, warehouse): a group can mix an
        # ACTIVE hold with an already-expired one, and the sale covers both.
        demand: dict[tuple[UUID, UUID], int] = {}
        active_ref: dict[tuple[UUID, UUID], InventoryReservation] = {}
        for reservation in pending:
            key = (reservation.variant_id, reservation.warehouse_id)
            demand[key] = demand.get(key, 0) + reservation.quantity
            if reservation.status == "ACTIVE" and key not in active_ref:
                active_ref[key] = reservation

        for (variant_id, warehouse_id), quantity in demand.items():
            balance = await BalanceServiceMixin._locked_balance(
                session, tenant_id, variant_id, warehouse_id
            )
            sold = check_physical_settlement(
                on_hand=balance.on_hand,
                quantity=quantity,
                variant_id=variant_id,
                warehouse_id=warehouse_id,
                context=f"converting reservations for order {order_id}",
            )
            freed = min(balance.reserved, quantity)
            balance.reserved -= freed
            balance.on_hand -= sold
            if freed:
                # Attribute the release to THIS group's ACTIVE hold; when the
                # group has none (the sweep freed it already — freed>0 can
                # only come from another group's hold, so this is defensive),
                # pass None and let _pair_release_with_reservation resolve the
                # right row instead of referencing a foreign group's
                # reservation (deep self-review).
                await MovementServiceMixin._append_release(
                    session,
                    tenant_id,
                    variant_id,
                    warehouse_id,
                    quantity=freed,
                    balance_after=balance.on_hand,
                    reservation=active_ref.get((variant_id, warehouse_id)),
                )
            await MovementServiceMixin._append(
                session,
                tenant_id,
                variant_id,
                warehouse_id,
                direction="out",
                quantity=sold,
                reason="sale",
                balance_after=balance.on_hand,
                reference_type="order",
                reference_id=order_id,
                actor_user_id=actor_user_id,
            )
        for reservation in pending:
            reservation.status = "CONVERTED"
            reservation.converted_at = _now()
        return len(pending)

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
