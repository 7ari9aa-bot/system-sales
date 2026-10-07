"""§139 — the goods-return process, driven by the saga engine.

A return is the one business process in this system with a real compensation
requirement: the units come back, and then the paperwork has to change. If the
paperwork fails, the units must go back out again — a ledger that reports stock
the warehouse does not have is worse than a return that never happened.

That is what makes it a saga rather than a status update: ordered steps, each
with the undo that the next step's failure is entitled to demand.

    step 0  restock    paid line  -> `in`/return movement per line
                       COD line   -> release the hold that never settled
                       undo       -> `out`/return_reversal, or reserve again
    step 1  close      order -> `returned` (+ history row, + outbox event)
                       undo       -> the previous status and saga state restored

Giving money back is NOT a step here. §115 lists "Refund approval" among the
critical flows, so a refund stays a human decision on a payment
(`POST /orders/{id}/payments/{pid}/refunds`); a box arriving at a warehouse is
evidence about stock, not an instruction about money.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.saga import Saga, SagaManager, SagaStatus, SagaStepHandler
from app.modules.errors import ConflictError, ValidationError
from app.modules.orders.models import Order, OrderItem, OrderStatusHistory
from app.modules.orders.service import _RESERVATION_TTL, OrderService, _now

#: The saga type registered on :class:`app.core.saga.SagaManager`.
RETURN_SAGA_TYPE = "order_return"

#: Statuses a parcel can come back from. `pending`/`confirmed`/`processing`
#: never left the building, and `cancelled`/`returned`/`refunded` are already
#: closed — a return of one of those is a duplicate click, not a process.
RETURNABLE_STATUSES = frozenset({"shipped", "delivered"})

#: Why the goods are back, in the words the history note and audit use.
RETURN_REASONS = frozenset({"customer_return", "delivery_failed"})


async def _active_reservation_variant_ids(
    session: AsyncSession, tenant_id: uuid.UUID, order_id: uuid.UUID
) -> set[uuid.UUID]:
    """Variants this order still HOLDS (ACTIVE) rather than has sold."""
    from app.modules.inventory.models import InventoryReservation

    rows = (
        await session.execute(
            select(InventoryReservation.variant_id).where(
                InventoryReservation.tenant_id == tenant_id,
                InventoryReservation.order_id == order_id,
                InventoryReservation.status == "ACTIVE",
            )
        )
    ).all()
    return {r[0] for r in rows}


async def _order_warehouse_id(
    session: AsyncSession, tenant_id: uuid.UUID, order: Order
) -> uuid.UUID:
    raw = (order.extra or {}).get("warehouse_id")
    if raw:
        return uuid.UUID(str(raw))
    from app.modules.inventory.service import InventoryService

    return (await InventoryService.get_default_warehouse(session, tenant_id)).id


class RestockReturnedLines(SagaStepHandler):
    """step 0 — put every returned line back where the order took it from."""

    async def execute(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        saga: Saga,
        context: dict,
    ) -> dict:
        from app.modules.inventory.service import (
            InventoryReservationService,
            InventoryService,
        )

        order = await OrderService.get(
            session, tenant_id, saga.aggregate_id, with_items=True, for_update=True
        )
        warehouse_id = await _order_warehouse_id(session, tenant_id, order)
        held = await _active_reservation_variant_ids(session, tenant_id, order.id)

        items = order.items or list(
            (
                await session.execute(
                    select(OrderItem).where(
                        OrderItem.tenant_id == tenant_id,
                        OrderItem.order_id == order.id,
                    )
                )
            )
            .scalars()
            .all()
        )

        restocked: list[dict[str, Any]] = []
        released: list[dict[str, Any]] = []
        for item in items:
            if item.variant_id in held:
                # Cash on delivery: the units were held, never sold, so they are
                # still inside `on_hand`. Adding them again would invent stock.
                await InventoryService.release(
                    session, tenant_id, item.variant_id, warehouse_id, item.quantity
                )
                released.append({"variant_id": str(item.variant_id), "quantity": item.quantity})
            else:
                await InventoryService.move(
                    session,
                    tenant_id,
                    item.variant_id,
                    warehouse_id,
                    direction="in",
                    quantity=item.quantity,
                    reason="return",
                    reference_type="order",
                    reference_id=order.id,
                )
                restocked.append({"variant_id": str(item.variant_id), "quantity": item.quantity})

        # The durable reservation rows (§140) must not outlive the order they
        # held stock for, whatever state they are in.
        await InventoryReservationService.cancel_for_order(session, tenant_id, order.id)
        return {
            "restocked": restocked,
            "released": released,
            "warehouse_id": str(warehouse_id),
        }

    async def compensate(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        saga: Saga,
        context: dict,
    ) -> dict:
        """Take back exactly what `execute` put back — the same lines, the same
        warehouse, in the opposite direction.
        """
        from app.modules.inventory.service import InventoryService

        warehouse_id = uuid.UUID(str(context["warehouse_id"]))
        for line in context.get("restocked", []):
            await InventoryService.move(
                session,
                tenant_id,
                uuid.UUID(line["variant_id"]),
                warehouse_id,
                direction="out",
                quantity=int(line["quantity"]),
                reason="return_reversal",
                reference_type="order",
                reference_id=saga.aggregate_id,
            )
        for line in context.get("released", []):
            # The hold goes back too, so a retried return sees the same position
            # the failed one saw rather than a newly-available one.
            await InventoryService.reserve(
                session,
                tenant_id,
                uuid.UUID(line["variant_id"]),
                warehouse_id,
                int(line["quantity"]),
            )
            # And the durable §140 row goes back with it. `execute` cancelled it,
            # so a hold with no row behind it reads as "this order never held
            # anything" to the retry — which would restock units never sold.
            await InventoryService.create_reservation(
                session,
                tenant_id,
                variant_id=uuid.UUID(line["variant_id"]),
                warehouse_id=warehouse_id,
                order_id=saga.aggregate_id,
                quantity=int(line["quantity"]),
                expires_at=_now() + _RESERVATION_TTL,
            )
        return {"reversed": True}


class CloseReturnedOrder(SagaStepHandler):
    """step 1 — the paperwork half: the order itself says `returned`."""

    async def execute(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        saga: Saga,
        context: dict,
    ) -> dict:
        order = await OrderService.get(
            session, tenant_id, saga.aggregate_id, with_items=False, for_update=True
        )
        from_status = order.status
        from_state = order.process_state
        await OrderService._transition(
            session,
            tenant_id,
            order,
            "returned",
            by_user_id=_actor(context),
            note=f"returned ({context.get('reason', 'customer_return')})",
        )
        return {"closed_from": from_status, "saga_from": from_state}

    async def compensate(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        saga: Saga,
        context: dict,
    ) -> dict:
        order = await OrderService.get(
            session, tenant_id, saga.aggregate_id, with_items=False, for_update=True
        )
        restored = context.get("closed_from")
        previous_state = context.get("saga_from")
        if restored not in RETURNABLE_STATUSES or restored == order.status:
            # No legal place to go back to: say so loudly rather than leaving
            # the order in a state nothing predicted.
            raise RuntimeError(
                f"cannot restore order {order.id} to {restored!r} after a failed return"
            )
        session.add(
            OrderStatusHistory(
                tenant_id=tenant_id,
                order_id=order.id,
                from_status=order.status,
                to_status=restored,
                changed_by_user_id=_actor(context),
                note="return compensation: the process failed",
            )
        )
        order.status = restored
        if previous_state:
            order.process_state = previous_state
        await session.flush()
        return {"restored": restored}


def _actor(context: dict) -> uuid.UUID | None:
    raw = context.get("by_user_id")
    return uuid.UUID(str(raw)) if raw else None


SagaManager.register(RETURN_SAGA_TYPE, 0, RestockReturnedLines())
SagaManager.register(RETURN_SAGA_TYPE, 1, CloseReturnedOrder())


class ReturnsService:
    """The entry point: run the return to the end, or back to the start."""

    @staticmethod
    async def process_return(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        order_id: uuid.UUID,
        *,
        reason: str = "customer_return",
        by_user_id: uuid.UUID | None = None,
    ) -> Saga:
        """Return a parcel's worth of goods and close the order on it.

        Raises whatever a step raised, after the engine has compensated the
        steps that had already completed — so a failure here leaves the stock,
        the order and a `failed` saga row behind, never a half-finished process.
        """
        if reason not in RETURN_REASONS:
            raise ValidationError(f"unknown return reason: {reason!r}")
        order = await OrderService.get(
            session, tenant_id, order_id, with_items=False, for_update=True
        )
        if order.status not in RETURNABLE_STATUSES:
            raise ConflictError(
                f"cannot return a {order.status} order: the goods must have left "
                "the warehouse first"
            )

        saga = await SagaManager.create_saga(
            session,
            tenant_id,
            saga_type=RETURN_SAGA_TYPE,
            aggregate_type="order",
            aggregate_id=order.id,
            context={
                "reason": reason,
                "by_user_id": str(by_user_id) if by_user_id else None,
            },
        )
        while saga.status == SagaStatus.RUNNING.value:
            saga = await SagaManager.execute_next(session, tenant_id, saga.id)
        return saga
