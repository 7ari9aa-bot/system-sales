"""ORDERS domain service — checkout, lifecycle, payments, refunds.

The order flow is ONE logical unit inside the caller's transaction: validate
customer -> load variants -> reserve stock -> write order/items/history ->
stage the outbox event. The SERVICE NEVER COMMITS.

Money rules (quantization, the net collected/refunded arithmetic, and the
monotone payment-status rule) live in ``orders.money`` so they can be exercised
without a database; this module only supplies the aggregates they run on.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.writer import add_outbox_event
from app.core.idempotency import apply_versioned_update, require_version  # §17
from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.orders.models import (
    Order,
    OrderItem,
    OrderPayment,
    OrderStatusHistory,
    Refund,
    Shipment,
)
from app.modules.orders.money import (
    SETTLED_PAYMENT_STATUSES,
    compute_totals,
    net_collected,
    order_balance,
    positive_money,
    reconciliation_refusal,
    to_money,
)

logger = logging.getLogger(__name__)

# pending -> confirmed -> processing -> shipped -> delivered -> completed -> refunded
# (cancelled is reachable from every open state)
TRANSITIONS: dict[str, set[str]] = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"processing", "cancelled"},
    "processing": {"shipped", "cancelled"},
    "shipped": {"delivered", "returned"},
    "delivered": {"completed", "returned"},
    "completed": {"refunded"},
    # Reachable only through the return process, which restocks first
    # (`orders/returns.py`, ADR-052) — `change_status` refuses it by hand.
    "returned": {"refunded"},
}

_CANCELLABLE_STATUSES = {"pending", "confirmed"}
_PAYMENT_METHODS = {"cash", "card", "wallet", "bank_transfer", "cod", "manual"}
_PAYMENT_PROVIDER_STATUSES = {
    "pending": "pending",
    "processing": "pending",
    "authorized": "authorized",
    "captured": "captured",
    "paid": "captured",
    "succeeded": "captured",
    "failed": "failed",
    "rejected": "failed",
    "unknown": "unknown",
    "refunded": "refunded",
    "partially_refunded": "partially_refunded",
}
_NUMBER_ATTEMPTS = 2
# §140: a durable reservation row expires after 15 minutes if the order never
# completes (abandoned cart) — the maintenance worker flips it to EXPIRED.
_RESERVATION_TTL = timedelta(minutes=15)

# §139: order saga state machine — the cross-service fulfillment saga.
# created -> (paid and stock_reserved, in either order) -> fulfilled, and then
# either cancelled or returned.
ORDER_PROCESS_STATES = (
    "created",
    "paid",
    "stock_reserved",
    "fulfilled",
    "cancelled",
    "returned",
)
# `stock_reserved` and `paid` are reached in EITHER order, because checkout
# reserves stock before any money exists (COD is the common case here) while a
# card payment settles after the parcel is picked. A machine that only allowed
# created -> paid -> stock_reserved could not describe a real order.
#
# `returned` is reachable from all three of the non-terminal states, not just
# from `fulfilled`: the parcel can come back before the money exists (a COD
# order that never settled) or after it (a card order). It is the ORDER STATUS
# machine that decides whether a return is allowed (only from shipped /
# delivered); this machine only has to be able to say so, or the saga column
# would keep naming the money on a row whose goods are back on the shelf.
_PROCESS_TRANSITIONS: dict[str, set[str]] = {
    "created": {"paid", "stock_reserved", "cancelled"},
    "paid": {"stock_reserved", "fulfilled", "cancelled", "returned"},
    "stock_reserved": {"paid", "fulfilled", "cancelled", "returned"},
    "fulfilled": {"returned"},
    "cancelled": set(),  # terminal
    "returned": set(),  # terminal
}

#: The saga state each order status implies, for the moves made as a SIDE
#: EFFECT of a status change. Statuses absent here leave the saga alone.
_SAGA_ON_STATUS: dict[str, str] = {
    "cancelled": "cancelled",
    "delivered": "fulfilled",
    "completed": "fulfilled",
    "returned": "returned",
}

SHIPMENT_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"picked_up"},
    "picked_up": {"in_transit"},
    "in_transit": {"delivered", "returned", "failed"},
    "delivered": set(),  # terminal
    "returned": set(),  # terminal
    "failed": set(),  # terminal
}


def _now() -> datetime:
    return datetime.now(UTC)


def _new_order_number() -> str:
    return f"ORD-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:6].upper()}"


def _positive_int(value: object, field: str = "quantity") -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if number <= 0:
        raise ValueError(f"{field} must be greater than zero")
    return number


class OrderService:
    """All order business rules; static methods taking (session, tenant_id)."""

    # ------------------------------------------------------------- read ----

    @staticmethod
    async def get(
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        *,
        with_items: bool = True,
        for_update: bool = False,
    ) -> Order:
        """Fetch a tenant-scoped order; items attached when requested.

        for_update locks the row for the rest of the transaction — every
        MUTATING path must pass it so two concurrent transitions (e.g. cancel
        vs pay) serialize instead of both passing the status guard and
        double-releasing stock.

        Every mutating path also takes the ORDER lock before it takes a payment
        lock, so the two never deadlock against each other.
        """
        stmt = select(Order).where(
            Order.id == order_id,
            Order.tenant_id == tenant_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        order = (await session.execute(stmt)).scalar_one_or_none()
        if order is None:
            raise NotFoundError(f"order {order_id} not found")
        if with_items:
            items = (
                await session.execute(
                    select(OrderItem)
                    .where(
                        OrderItem.tenant_id == tenant_id,
                        OrderItem.order_id == order_id,
                    )
                    .order_by(OrderItem.created_at.asc(), OrderItem.id.asc())
                )
            ).scalars().all()
            # Transient, non-mapped attribute — the models declare no
            # relationships; this is the service's eager-load contract.
            order.items = list(items)
        return order

    @staticmethod
    async def list_orders(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        status: str | None = None,
        customer_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
        before_created_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> list[Order]:
        """Keyset-aware listing: pass before_created_at + before_id to page."""
        stmt = select(Order).where(Order.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(Order.status == status)
        if customer_id is not None:
            # Customer 360: without this filter the record page would have to
            # pull a tenant-wide page and filter client-side, which silently
            # reports "no orders" for anyone outside that page.
            stmt = stmt.where(Order.customer_id == customer_id)
        if before_created_at is not None and before_id is not None:
            stmt = stmt.where(
                tuple_(Order.created_at, Order.id)
                < tuple_(before_created_at, before_id)
            )
        stmt = (
            stmt.order_by(Order.created_at.desc(), Order.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await session.execute(stmt)).scalars().all())

    # ---------------------------------------------------------- create ----

    @staticmethod
    async def create_order(
        session: AsyncSession,
        tenant_id: UUID,
        customer_id: UUID,
        items: list[dict],
        *,
        channel: str | None = None,
        shipping_address: dict | None = None,
        warehouse_id: UUID | None = None,
        currency: str | None = None,
        discount_total: object = None,
        shipping_total: object = None,
        tax_total: object = None,
        # §8: function-scope imports — avoids module-scope service coupling.
    ) -> Order:
        from app.core.tenancy import resolve_tenant_currency
        from app.modules.catalog.service import CatalogService
        from app.modules.customers.service import CustomerService
        from app.modules.inventory.service import (
            InventoryService,
        )

        """Checkout: validate, reserve stock, persist order + snapshots.

        items: [{"variant_id": UUID, "quantity": int}, ...]
        Everything happens in the caller's transaction; the outbox row for
        order.created is written in the SAME transaction.
        """
        if not items:
            raise ValidationError("order must contain at least one item")

        # §47: the order is priced in the tenant's currency and in no other. An
        # HTTP caller already holds it on its context; the AI tool runtime and
        # any worker without one reads the tenant row.
        tenant_currency = await resolve_tenant_currency(session, tenant_id)
        if currency is not None and currency.upper() != tenant_currency:
            raise ConflictError(
                f"this tenant trades in {tenant_currency}; a {currency.upper()} "
                "order would be money no rate has agreed on"
            )
        currency = tenant_currency

        customer = await CustomerService.get(session, tenant_id, customer_id)
        # Blocked (fraud/abuse), tombstoned (privacy deletion) or merged-away
        # customers must never place orders — the last two would attach live
        # orders to a ghost record.
        if getattr(customer, "is_blocked", False):
            raise ConflictError("customer is blocked and cannot place orders")
        if getattr(customer, "deleted_at", None) is not None:
            raise ConflictError("customer is deleted")
        if getattr(customer, "merged_into_customer_id", None) is not None:
            raise ConflictError(
                "customer has been merged — resolve the canonical customer first"
            )

        warehouse = (
            await InventoryService.get_warehouse(session, tenant_id, warehouse_id)
            if warehouse_id is not None
            else await InventoryService.get_default_warehouse(session, tenant_id)
        )

        # The price is CAPTURED here, once, and everything downstream — the
        # line totals, the order total, the outbox payload — reads that
        # snapshot. Nothing recomputes a total from the (mutable) variant price.
        #
        # §47: the snapshot comes from the tenant's PRICE LADDER in the order's
        # currency, not from the bare variant price. A merchant who publishes
        # "6 units at 85" is quoting that tier, and a USD tier sitting on an EGP
        # shop is a different shop — it prices nothing here.
        prepared: list[tuple[Any, int, Decimal]] = []
        for item in items:
            try:
                variant_id = UUID(str(item["variant_id"]))
            except (KeyError, ValueError) as exc:
                raise ValueError("each item needs a valid variant_id") from exc
            variant = await CatalogService.get_variant(session, tenant_id, variant_id)
            quantity = _positive_int(item.get("quantity"))
            unit_price = await CatalogService.price_for(
                session, tenant_id, variant, currency=currency, quantity=quantity
            )
            prepared.append((variant, quantity, to_money(unit_price, "unit_price")))

        # Reserve first — insufficient stock aborts the whole order.
        for variant, quantity, _price in prepared:
            await InventoryService.reserve(
                session, tenant_id, variant.id, warehouse.id, quantity
            )

        subtotal = to_money(
            sum((price * quantity for _v, quantity, price in prepared), Decimal("0")),
            "subtotal",
        )
        # §47/the money gap: checkout used to write `grand_total = subtotal` and
        # leave the three components at zero, so a discount or a shipping charge
        # could be stated to the customer and never collected. The components
        # now add up to what the order is worth, or the call is refused.
        try:
            totals = compute_totals(
                subtotal=subtotal,
                discount=discount_total,
                shipping=shipping_total,
                tax=tax_total,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        order = await OrderService._insert_order(
            session,
            tenant_id,
            customer_id=customer_id,
            status="pending",
            # §139: the row is born with its stock already held (the reserve
            # loop above aborted the whole order if it could not), so recording
            # "created" here would be a claim the reservations contradict.
            process_state="stock_reserved",
            currency=currency,
            **totals,
            channel=channel,
            shipping_address=shipping_address,
            placed_at=_now(),
            extra={"warehouse_id": str(warehouse.id)},
        )

        # §140: durable reservation rows next to the balance hold — one per
        # line, expiring in 15 minutes unless the order completes.
        expires_at = _now() + _RESERVATION_TTL
        for variant, quantity, _price in prepared:
            await InventoryService.create_reservation(
                session,
                tenant_id,
                variant_id=variant.id,
                warehouse_id=warehouse.id,
                order_id=order.id,
                quantity=quantity,
                expires_at=expires_at,
            )

        # Line snapshots (title/sku frozen at purchase time).
        product_ids = {variant.product_id for variant, _q, _p in prepared}
        products = await CatalogService.get_products_by_ids(
            session, tenant_id, list(product_ids)
        )
        for variant, quantity, price in prepared:
            product = products.get(variant.product_id)
            session.add(
                OrderItem(
                    tenant_id=tenant_id,
                    order_id=order.id,
                    variant_id=variant.id,
                    title=variant.title or (product.title if product else ""),
                    sku=variant.sku,
                    quantity=quantity,
                    unit_price=price,
                    total=to_money(price * quantity, "line total"),
                )
            )

        session.add(
            OrderStatusHistory(
                tenant_id=tenant_id,
                order_id=order.id,
                from_status=None,
                to_status="pending",
                changed_by_user_id=None,
            )
        )
        await session.flush()

        await add_outbox_event(
            session,
            aggregate_type="order",
            aggregate_id=order.id,
            event_type="order.created",
            tenant_id=tenant_id,
            payload={
                "order_id": str(order.id),
                "number": order.number,
                "customer_id": str(customer_id),
                "warehouse_id": str(warehouse.id),
                "status": order.status,
                "currency": order.currency,
                # Decimal, like every other money value on the wire — the
                # envelope's value codec tags it so the consumer gets a Decimal
                # back, not a string or a float.
                "grand_total": order.grand_total,
                "item_count": sum(q for _v, q, _p in prepared),
            },
            # §153: the row's real version (VersionMixin) — never a literal.
            aggregate_version=order.version,
        )
        return order

    @staticmethod
    async def _insert_order(
        session: AsyncSession, tenant_id: UUID, **values: object
    ) -> Order:
        """Insert the order; retry once if the random number collides.

        The row is added INSIDE the savepoint so a failed attempt is fully
        expunged and the caller's transaction stays usable.
        """
        last_exc: IntegrityError | None = None
        for _attempt in range(_NUMBER_ATTEMPTS):
            try:
                async with session.begin_nested():
                    values = {**values, "number": _new_order_number()}
                    order = Order(tenant_id=tenant_id, **values)  # type: ignore[arg-type]
                    session.add(order)
                    await session.flush()
                return order
            except IntegrityError as exc:
                last_exc = exc  # number collision — regenerate and retry
        raise ConflictError(
            "could not allocate a unique order number"
        ) from last_exc

    # --------------------------------------------------------- cancel ----

    @staticmethod
    async def cancel_order(
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        *,
        by_user_id: UUID | None = None,
        expected_version: str | None = None,  # §17 If-Match
    ) -> Order:
        """Cancel an open order and give its reserved stock back."""
        order = await OrderService.get(
            session, tenant_id, order_id, with_items=True, for_update=True
        )
        # §17: fast-fail a stale If-Match before releasing stock.
        if expected_version is not None:
            require_version(expected_version, order.version)
        if order.status not in _CANCELLABLE_STATUSES:
            raise ConflictError(
                f"order {order_id} cannot be cancelled from status '{order.status}'"
            )
        await OrderService._release_order_stock(session, tenant_id, order)
        await OrderService._transition(
            session,
            tenant_id,
            order,
            "cancelled",
            by_user_id=by_user_id,
            event_type="order.cancelled",
            expected_version=expected_version,  # §17
        )
        return order

    # ------------------------------------------------------ lifecycle ----

    @staticmethod
    async def change_status(
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        to_status: str,
        *,
        by_user_id: UUID | None = None,
        note: str | None = None,
        expected_version: str | None = None,  # §17 If-Match
    ) -> Order:
        """Move an order along TRANSITIONS; cancellation frees the stock."""
        order = await OrderService.get(
            session, tenant_id, order_id, with_items=False, for_update=True
        )
        # §17: fast-fail a stale If-Match before doing any work.
        if expected_version is not None:
            require_version(expected_version, order.version)
        allowed = TRANSITIONS.get(order.status, set())
        if to_status not in allowed:
            raise ConflictError(
                f"illegal transition {order.status} -> {to_status}"
            )
        if to_status == "returned":
            # "returned" is a STOCK claim, not a label: the goods are back in the
            # warehouse. Running it by hand would close the order while the
            # ledger still says the units were sold, so the return process
            # (`orders/returns.py`, ADR-052) owns this transition — it restocks
            # first and only then moves the order.
            raise ConflictError(
                f"order {order_id} cannot be marked returned directly: return "
                "the shipment, which restocks the goods and closes the order"
            )
        if to_status == "cancelled":
            await OrderService._release_order_stock(session, tenant_id, order)
        if to_status == "refunded":
            # "refunded" is a MONEY claim, not a label. It may only be reached
            # once the merchant holds nothing for this order; otherwise the
            # order reads as refunded while the captured money stays put and no
            # `refunds` row exists to reconcile it against the capture.
            # Refunds are recorded through register_refund, which then performs
            # this transition itself.
            settled, refunded = await OrderService._settled_and_refunded(
                session, tenant_id, order
            )
            held = net_collected(settled, refunded)
            if held > 0:
                raise ConflictError(
                    f"order {order_id} still holds {held} captured — refund the "
                    "payment(s) before marking the order refunded"
                )
        await OrderService._transition(
            session, tenant_id, order, to_status, by_user_id=by_user_id, note=note,
            expected_version=expected_version,  # §17
        )
        return order

    @staticmethod
    async def _default_warehouse(session: AsyncSession, tenant_id: UUID):
        """Fetch (or race-safe bootstrap) the tenant's MAIN warehouse.

        Thin delegation: inventory owns warehouses; orders only needs the
        default when a cart arrives without an explicit warehouse_id.
        """
        from app.modules.inventory.service import InventoryService

        return await InventoryService.get_default_warehouse(session, tenant_id)

    @staticmethod
    async def _transition(
        session: AsyncSession,
        tenant_id: UUID,
        order: Order,
        to_status: str,
        *,
        by_user_id: UUID | None = None,
        note: str | None = None,
        event_type: str = "order.status_changed",
        expected_version: str | None = None,  # §17
    ) -> None:
        from_status = order.status
        # §17: atomic compare-and-swap when If-Match is present; a stale version
        # matches no row and apply_versioned_update raises ConflictError (409).
        values: dict = {"status": to_status}
        # §139: the saga moves with the statuses that imply it, in the SAME
        # statement — a second UPDATE for the same row would bypass the CAS.
        saga_target = _SAGA_ON_STATUS.get(to_status)
        apply_saga = saga_target is not None and OrderService._saga_move(order, saga_target)
        if apply_saga:
            values["process_state"] = saga_target
        if expected_version is not None:
            await apply_versioned_update(session, order, expected_version, values)
        else:
            order.status = to_status
            if apply_saga:
                order.process_state = saga_target
        session.add(
            OrderStatusHistory(
                tenant_id=tenant_id,
                order_id=order.id,
                from_status=from_status,
                to_status=to_status,
                changed_by_user_id=by_user_id,
                note=note,
            )
        )
        await session.flush()
        await add_outbox_event(
            session,
            aggregate_type="order",
            aggregate_id=order.id,
            event_type=event_type,
            tenant_id=tenant_id,
            payload={
                "order_id": str(order.id),
                "number": order.number,
                "from_status": from_status,
                "to_status": to_status,
            },
            # §153: post-mutation row version (bumped by apply_versioned_update
            # when If-Match was supplied; otherwise the row's current version).
            aggregate_version=order.version,
        )

    @staticmethod
    async def _release_order_stock(
        session: AsyncSession, tenant_id: UUID, order: Order
    ) -> None:
        """Release every item's reservation at the warehouse the order used.

        §140: the balance hold goes back AND the durable reservation rows are
        flipped to CANCELLED.
        """
        items = getattr(order, "items", None)
        if items is None:
            items = (
                await session.execute(
                    select(OrderItem).where(
                        OrderItem.tenant_id == tenant_id,
                        OrderItem.order_id == order.id,
                    )
                )
            ).scalars().all()
            order.items = list(items)

        warehouse_raw = (order.extra or {}).get("warehouse_id")
        if warehouse_raw:
            warehouse_id = UUID(str(warehouse_raw))
        else:  # legacy order without a recorded warehouse
            from app.modules.inventory.service import InventoryService as _IS
            warehouse_id = (await _IS.get_default_warehouse(session, tenant_id)).id

        for item in items:
            from app.modules.inventory.service import InventoryService as _IS2
            await _IS2.release(
                session, tenant_id, item.variant_id, warehouse_id, item.quantity
            )
        from app.modules.inventory.service import InventoryReservationService as _IRS
        await _IRS.cancel_for_order(
            session, tenant_id, order.id
        )

    # --------------------------------------------------------- payment ----

    @staticmethod
    async def add_payment(
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        *,
        method: str,
        amount: object,
        provider: str | None = None,
        currency: str | None = None,
    ) -> OrderPayment:
        """Capture a payment; a paid pending order becomes confirmed.

        "captured" is written only when the result is definitive; provider-
        timeout paths (result lost mid-flight) map to status "unknown" in the
        Stage payments adapter and are reconciled there — never retried
        blindly (§141).

        §47: a payment stated in a currency other than the order's is refused.
        Nothing converts, because this tenant has one currency and the order
        already names it — so a mismatch is a mistake or a different order, and
        never a rate to apply.
        """
        if method not in _PAYMENT_METHODS:
            raise ValidationError(
                f"method must be one of {sorted(_PAYMENT_METHODS)}, got {method!r}"
            )
        order = await OrderService.get(
            session, tenant_id, order_id, with_items=False, for_update=True
        )
        if currency is not None and currency.upper() != order.currency:
            raise ConflictError(
                f"order {order.number} is payable in {order.currency}, not "
                f"{currency.upper()} — the amount received is not the amount owed"
            )
        if order.status in ("cancelled", "refunded"):
            raise ConflictError(f"cannot pay a {order.status} order")
        captured = positive_money(amount)

        # Over-payment guard: the order's NET position (settled money minus
        # refunds) plus this capture must not exceed the order total. Summing
        # the payments GROSS counted a refunded amount as still collected, so
        # the refunded part could never be charged again.
        settled, refunded = await OrderService._settled_and_refunded(
            session, tenant_id, order
        )
        remaining = order_balance(order.grand_total, settled, refunded)
        if captured > remaining:
            raise ConflictError(
                f"payment exceeds order balance: remaining={remaining}, "
                f"requested={captured}"
            )

        payment = OrderPayment(
            tenant_id=tenant_id,
            order_id=order.id,
            method=method,
            status="captured",
            amount=captured,
            currency=order.currency,
            provider=provider,
            paid_at=_now(),
        )
        session.add(payment)
        await session.flush()

        # §140: a captured payment converts the order's stock reservations
        # into a sale (ACTIVE -> CONVERTED).
        from app.modules.inventory.service import InventoryReservationService as _IRS2
        await _IRS2.convert(session, tenant_id, order.id)

        # §139: money really arrived, so the saga says so.
        if OrderService._saga_move(order, "paid"):
            order.process_state = "paid"
            await session.flush()

        if order.status == "pending":
            await OrderService._transition(
                session, tenant_id, order, "confirmed", note=f"paid via {method}"
            )
        return payment

    @staticmethod
    async def reconcile_payment(
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        payment_id: UUID,
        *,
        provider_status: str,
        provider_ref: str | None = None,
    ) -> OrderPayment:
        """Resolve an external payment result without retrying the charge.

        Provider adapters perform the lookup and pass only the observed status
        here. A captured result applies reservation/order effects exactly once,
        and a captured payment is never downgraded by a later report — see
        ``money.resolve_payment_status``.
        """
        status = _PAYMENT_PROVIDER_STATUSES.get(provider_status.lower())
        if status is None:
            raise ValidationError(
                f"unsupported provider payment status: {provider_status}"
            )
        # The order lock first (global lock order: order -> payment), so two
        # reconciles on the same order cannot both observe "pending" and both
        # write a pending -> confirmed history row and event.
        order = await OrderService.get(
            session, tenant_id, order_id, with_items=False, for_update=True
        )
        payment = (
            await session.execute(
                select(OrderPayment)
                .where(
                    OrderPayment.id == payment_id,
                    OrderPayment.tenant_id == tenant_id,
                    OrderPayment.order_id == order.id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if payment is None:
            raise NotFoundError(f"payment {payment_id} not found for order {order_id}")

        refusal = reconciliation_refusal(payment.status, status)
        if refusal is not None:
            # A money state may only move forward: a human resolves the
            # disagreement, the service does not guess.
            raise ConflictError(refusal)
        if status == payment.status:
            # Already there: no effect may be applied a second time.
            if provider_ref:
                payment.provider_ref = provider_ref
                await session.flush()
            return payment

        payment.status = status
        if provider_ref:
            payment.provider_ref = provider_ref
        if status == "captured":
            payment.paid_at = payment.paid_at or _now()
            from app.modules.inventory.service import InventoryReservationService as _IRS3
            await _IRS3.convert(session, tenant_id, order.id)
            if OrderService._saga_move(order, "paid"):
                order.process_state = "paid"
            if order.status == "pending":
                await OrderService._transition(
                    session, tenant_id, order, "confirmed", note="payment reconciled"
                )
        await session.flush()
        return payment

    @staticmethod
    async def reconcile_stuck_payments(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        stuck_threshold_minutes: int = 15,
    ) -> list[dict]:
        """Reconcile stuck payment intents.

        Only 'unknown' rows are swept (§141): a result that was never observed
        AND that no provider webhook has since resolved. 'pending' rows are
        NOT touched — bank transfers and COD may legitimately sit for hours,
        and blindly failing them marked captured money as failed.
        """
        cutoff = _now() - timedelta(minutes=stuck_threshold_minutes)
        rows = (
            await session.execute(
                select(OrderPayment).where(
                    OrderPayment.tenant_id == tenant_id,
                    OrderPayment.status == "unknown",
                    OrderPayment.created_at <= cutoff,
                ).limit(50)
            )
        ).scalars().all()

        results = []
        for payment in rows:
            old_status = payment.status
            payment.status = "failed"
            results.append({
                "payment_id": str(payment.id),
                "order_id": str(payment.order_id),
                "old_status": old_status,
                "new_status": "failed",
            })
        if results:
            await session.flush()
        return results

    @staticmethod
    async def register_refund(
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        payment_id: UUID,
        *,
        amount: object,
        reason: str | None = None,
        by_user_id: UUID | None = None,
    ) -> Refund:
        """Register a refund against a captured payment and track its state."""
        order = await OrderService.get(
            session, tenant_id, order_id, with_items=False, for_update=True
        )
        payment = (
            await session.execute(
                select(OrderPayment)
                .where(
                    OrderPayment.id == payment_id,
                    OrderPayment.tenant_id == tenant_id,
                    OrderPayment.order_id == order.id,
                ).with_for_update()
            )
        ).scalar_one_or_none()
        if payment is None:
            raise NotFoundError(f"payment {payment_id} not found for order {order_id}")
        # Only captured money can be refunded — refunding a pending/failed
        # intent invented money that was never taken.
        if payment.status not in ("captured", "partially_refunded"):
            raise ConflictError(
                f"cannot refund a {payment.status} payment — only captured"
            )

        # Quantized BEFORE the cap is checked, so the arithmetic matches the
        # NUMERIC(14,2) rows that will actually be stored.
        refund_amount = positive_money(amount)
        refunded_total = Decimal(
            str(
                (
                    await session.execute(
                        select(func.coalesce(func.sum(Refund.amount), 0))
                        .select_from(Refund)
                        .where(
                            Refund.tenant_id == tenant_id,
                            Refund.payment_id == payment.id,
                            Refund.status != "rejected",
                        )
                    )
                ).scalar_one()
            )
        )
        payment_total = to_money(payment.amount, "captured amount")
        if refunded_total + refund_amount > payment_total:
            raise ConflictError(
                f"refund exceeds captured amount: refunded={refunded_total}, "
                f"requested={refund_amount}, captured={payment_total}"
            )

        refund = Refund(
            tenant_id=tenant_id,
            payment_id=payment.id,
            amount=refund_amount,
            reason=reason,
            status="processed",
            processed_at=_now(),
            created_by_user_id=by_user_id,
        )
        session.add(refund)
        payment.status = (
            "refunded"
            if refunded_total + refund_amount >= payment_total
            else "partially_refunded"
        )
        await session.flush()

        # A fully refunded order must not stay "completed" — dashboards and
        # analytics counted refunded money as revenue.
        if payment.status == "refunded" and order.status == "completed":
            await OrderService._transition(
                session, tenant_id, order, "refunded", note="fully refunded"
            )

        await add_outbox_event(
            session,
            aggregate_type="order",
            aggregate_id=order.id,
            event_type="order.refunded",
            tenant_id=tenant_id,
            payload={
                "order_id": str(order.id),
                "number": order.number,
                "payment_id": str(payment.id),
                # Decimal, exactly as `grand_total` is published on
                # order.created: the same field must not arrive as a float on
                # one event and a Decimal on another.
                "amount": refund_amount,
                "payment_status": payment.status,
            },
            # §153: the order row's real version, post-mutation — not a literal.
            aggregate_version=order.version,
        )
        return refund

    # ------------------------------------------------------------ shipments ----

    @staticmethod
    async def create_shipment(
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        *,
        carrier: str | None = None,
        tracking_number: str | None = None,
        label_url: str | None = None,
        by_user_id: UUID | None = None,
        note: str | None = None,
    ) -> Shipment:
        """Record the parcel AND move the order, through the one status path.

        Shipping is exactly the step ``TRANSITIONS`` already guards, so it is
        not re-implemented here: an order that reads `shipped` must have the
        history row and the outbox event that says so, or the tracking record
        and the order status would be two facts allowed to disagree.
        """
        order = await OrderService.get(
            session, tenant_id, order_id, with_items=False, for_update=True
        )
        if order.status != "processing":
            raise ConflictError(
                f"cannot ship an order in status '{order.status}' — it must be "
                "'processing' first"
            )
        await OrderService._transition(
            session,
            tenant_id,
            order,
            "shipped",
            by_user_id=by_user_id,
            note=note or "shipment recorded",
        )
        shipment = Shipment(
            tenant_id=tenant_id,
            order_id=order.id,
            carrier=carrier,
            tracking_number=tracking_number,
            label_url=label_url,
            status="pending",
            shipped_at=_now(),
        )
        session.add(shipment)
        await session.flush()
        return shipment

    @staticmethod
    async def get_shipment(
        session: AsyncSession, tenant_id: UUID, shipment_id: UUID
    ) -> Shipment:
        shipment = (
            await session.execute(
                select(Shipment).where(
                    Shipment.id == shipment_id,
                    Shipment.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if shipment is None:
            raise NotFoundError(f"shipment {shipment_id} not found")
        return shipment

    @staticmethod
    async def list_shipments(
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Shipment]:
        rows = (
            await session.execute(
                select(Shipment)
                .where(
                    Shipment.tenant_id == tenant_id,
                    Shipment.order_id == order_id,
                )
                .order_by(Shipment.created_at.asc(), Shipment.id.asc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def set_shipment_status(
        session: AsyncSession,
        tenant_id: UUID,
        shipment_id: UUID,
        new_status: str,
        *,
        by_user_id: UUID | None = None,
    ) -> Shipment:
        """Move a parcel along SHIPMENT_TRANSITIONS; delivery moves the order.

        A carrier scan that says "delivered" is the evidence the order's own
        `shipped -> delivered` step was always waiting for, so the two are not
        left to be updated by hand in two places.
        """
        if new_status not in SHIPMENT_TRANSITIONS:
            raise ValidationError(f"unknown shipment status: {new_status!r}")

        # Lock in the project's global order (order rows first), even though the
        # caller named the shipment: this path writes the order too.
        observed = await OrderService.get_shipment(session, tenant_id, shipment_id)
        order = await OrderService.get(
            session, tenant_id, observed.order_id, with_items=False, for_update=True
        )
        shipment = (
            await session.execute(
                select(Shipment)
                .where(Shipment.id == shipment_id, Shipment.tenant_id == tenant_id)
                .with_for_update()
            )
        ).scalar_one()

        allowed = SHIPMENT_TRANSITIONS.get(shipment.status, set())
        if new_status not in allowed:
            raise ConflictError(
                f"illegal shipment transition {shipment.status} -> {new_status}"
            )
        shipment.status = new_status
        if new_status == "delivered":
            shipment.delivered_at = shipment.delivered_at or _now()
            if order.status == "shipped":
                await OrderService._transition(
                    session,
                    tenant_id,
                    order,
                    "delivered",
                    by_user_id=by_user_id,
                    note="carrier delivery confirmed",
                )
        elif new_status in ("returned", "failed"):
            # The carrier says the goods are back, so the return process runs:
            # restock what left, then close the order (ADR-052, which supersedes
            # ADR-051's choice to leave this status inert).
            from app.modules.orders.returns import ReturnsService

            await ReturnsService.process_return(
                session,
                tenant_id,
                order.id,
                reason=(
                    "delivery_failed" if new_status == "failed" else "customer_return"
                ),
                by_user_id=by_user_id,
            )
        await session.flush()
        return shipment

    # -------------------------------------------------------- helpers ----

    @staticmethod
    def _saga_move(order: Order, new_state: str) -> bool:
        """Decide a saga move made as bookkeeping for something that happened.

        This is NOT the human-command path (`transition_process_state` below
        keeps raising for an illegal one). A capture that arrives second, or a
        delivery after a refund, must not fail the business operation that
        already succeeded — the only honest answer to "illegal from here" inside
        a side effect is to leave the state alone and say so.
        """
        current = order.process_state or "created"
        if new_state in _PROCESS_TRANSITIONS.get(current, set()):
            return True
        logger.info(
            "order.process_state left alone",
            extra={"order_id": str(order.id), "from": current, "attempted": new_state},
        )
        return False

    # ------------------------------------------- §139 saga state ----

    @staticmethod
    async def transition_process_state(
        session: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
        new_state: str,
    ) -> Order:
        """§139: advance the order's saga state with a validated transition.

        created -> paid -> stock_reserved -> fulfilled (terminal) or
        cancelled (terminal from created/paid/stock_reserved).
        """
        if new_state not in ORDER_PROCESS_STATES:
            raise ValidationError(f"unknown process_state: {new_state!r}")
        order = await OrderService.get(
            session, tenant_id, order_id, with_items=False, for_update=True
        )
        current = order.process_state or "created"
        allowed = _PROCESS_TRANSITIONS.get(current, set())
        if new_state not in allowed:
            raise ConflictError(f"illegal saga transition {current} -> {new_state}")
        order.process_state = new_state
        await session.flush()
        return order

    async def _settled_and_refunded(
        session: AsyncSession, tenant_id: UUID, order: Order
    ) -> tuple[Decimal, Decimal]:
        """(gross settled, non-rejected refunded) over the order's payments.

        Gross is summed over ``SETTLED_PAYMENT_STATUSES`` — which INCLUDES
        ``refunded`` — and the refunds are then subtracted by the caller. The
        two sides have to be consistent: dropping refunded payments from the
        gross side while still subtracting their refunds counts the refund
        twice.
        """
        settled = (
            await session.execute(
                select(func.coalesce(func.sum(OrderPayment.amount), 0))
                .select_from(OrderPayment)
                .where(
                    OrderPayment.tenant_id == tenant_id,
                    OrderPayment.order_id == order.id,
                    OrderPayment.status.in_(SETTLED_PAYMENT_STATUSES),
                )
            )
        ).scalar_one()
        refunded = (
            await session.execute(
                select(func.coalesce(func.sum(Refund.amount), 0))
                .select_from(Refund)
                .join(OrderPayment, OrderPayment.id == Refund.payment_id)
                .where(
                    Refund.tenant_id == tenant_id,
                    OrderPayment.tenant_id == tenant_id,
                    OrderPayment.order_id == order.id,
                    Refund.status != "rejected",
                )
            )
        ).scalar_one()
        return to_money(settled, "settled"), to_money(refunded, "refunded")

        # Warehouse lookup + bootstrap now handled by InventoryService (§8).


# ------------------------------------------- §137 read models ----

class OrderListQuery:
    """§137: read-optimized order list query.

    Returns a list of dicts (not ORM objects) using specific column selects,
    so list pages don't hydrate full ORM relationships.
    """

    @staticmethod
    async def search(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Read-optimized order list with optional status filter."""
        from sqlalchemy import text

        params: dict[str, object] = {"t": str(tenant_id), "limit": limit}
        sql = (
            "SELECT id, number, customer_id, status, grand_total, currency, "
            "placed_at, created_at "
            "FROM orders WHERE tenant_id = :t"
        )
        if status is not None:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC LIMIT :limit"

        rows = (await session.execute(text(sql), params)).all()
        return [dict(r._mapping) for r in rows]

