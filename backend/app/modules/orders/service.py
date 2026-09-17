"""ORDERS domain service — checkout, lifecycle, payments, refunds.

The order flow is ONE logical unit inside the caller's transaction: validate
customer -> load variants -> reserve stock -> write order/items/history ->
stage the outbox event. The SERVICE NEVER COMMITS.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.writer import add_outbox_event
from app.modules.catalog.models import Product, ProductVariant
from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.errors import ConflictError, NotFoundError
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders.models import (
    Order,
    OrderItem,
    OrderPayment,
    OrderStatusHistory,
    Refund,
)

# pending -> confirmed -> processing -> shipped -> delivered -> completed -> refunded
# (cancelled is reachable from every open state)
TRANSITIONS: dict[str, set[str]] = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"processing", "cancelled"},
    "processing": {"shipped", "cancelled"},
    "shipped": {"delivered"},
    "delivered": {"completed"},
    "completed": {"refunded"},
}

_CANCELLABLE_STATUSES = {"pending", "confirmed"}
_PAYMENT_METHODS = {"cash", "card", "wallet", "bank_transfer", "cod", "manual"}
_NUMBER_ATTEMPTS = 2


def _now() -> datetime:
    return datetime.now(UTC)


def _new_order_number() -> str:
    return f"ORD-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:6].upper()}"


def _positive_amount(value: object, field: str = "amount") -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a valid number") from exc
    if amount <= 0:
        raise ValueError(f"{field} must be greater than zero")
    return amount


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
        session: AsyncSession, tenant_id: UUID, order_id: UUID, *, with_items: bool = True
    ) -> Order:
        """Fetch a tenant-scoped order; items attached when requested."""
        order = (
            await session.execute(
                select(Order).where(
                    Order.id == order_id,
                    Order.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
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
        limit: int = 50,
        offset: int = 0,
    ) -> list[Order]:
        stmt = select(Order).where(Order.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(Order.status == status)
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
    ) -> Order:
        """Checkout: validate, reserve stock, persist order + snapshots.

        items: [{"variant_id": UUID, "quantity": int}, ...]
        Everything happens in the caller's transaction; the outbox row for
        order.created is written in the SAME transaction.
        """
        if not items:
            raise ValueError("order must contain at least one item")

        await CustomerService.get(session, tenant_id, customer_id)

        warehouse = (
            await OrderService._get_warehouse(session, tenant_id, warehouse_id)
            if warehouse_id is not None
            else await OrderService._default_warehouse(session, tenant_id)
        )

        prepared: list[tuple[ProductVariant, int, Decimal]] = []
        for item in items:
            try:
                variant_id = UUID(str(item["variant_id"]))
            except (KeyError, ValueError) as exc:
                raise ValueError("each item needs a valid variant_id") from exc
            variant = await CatalogService.get_variant(session, tenant_id, variant_id)
            quantity = _positive_int(item.get("quantity"))
            prepared.append((variant, quantity, Decimal(str(variant.price))))

        # Reserve first — insufficient stock aborts the whole order.
        for variant, quantity, _price in prepared:
            await InventoryService.reserve(
                session, tenant_id, variant.id, warehouse.id, quantity
            )

        subtotal = sum((price * quantity for _v, quantity, price in prepared), Decimal("0"))
        subtotal_f = float(round(subtotal, 2))

        order = await OrderService._insert_order(
            session,
            tenant_id,
            customer_id=customer_id,
            status="pending",
            currency="EGP",
            subtotal=subtotal_f,
            discount_total=0.0,
            shipping_total=0.0,
            tax_total=0.0,
            grand_total=subtotal_f,
            channel=channel,
            shipping_address=shipping_address,
            placed_at=_now(),
            extra={"warehouse_id": str(warehouse.id)},
        )

        # Line snapshots (title/sku frozen at purchase time).
        product_ids = {variant.product_id for variant, _q, _p in prepared}
        products: dict[UUID, Product] = {}
        if product_ids:
            rows = (
                await session.execute(
                    select(Product).where(
                        Product.tenant_id == tenant_id,
                        Product.id.in_(product_ids),
                    )
                )
            ).scalars().all()
            products = {p.id: p for p in rows}
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
                    unit_price=float(price),
                    total=float(price * quantity),
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
                "grand_total": order.grand_total,
                "item_count": sum(q for _v, q, _p in prepared),
            },
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
    ) -> Order:
        """Cancel an open order and give its reserved stock back."""
        order = await OrderService.get(session, tenant_id, order_id, with_items=True)
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
    ) -> Order:
        """Move an order along TRANSITIONS; cancellation frees the stock."""
        order = await OrderService.get(session, tenant_id, order_id, with_items=False)
        allowed = TRANSITIONS.get(order.status, set())
        if to_status not in allowed:
            raise ConflictError(
                f"illegal transition {order.status} -> {to_status}"
            )
        if to_status == "cancelled":
            await OrderService._release_order_stock(session, tenant_id, order)
        await OrderService._transition(
            session, tenant_id, order, to_status, by_user_id=by_user_id, note=note
        )
        return order

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
    ) -> None:
        from_status = order.status
        order.status = to_status
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
        )

    @staticmethod
    async def _release_order_stock(
        session: AsyncSession, tenant_id: UUID, order: Order
    ) -> None:
        """Release every item's reservation at the warehouse the order used."""
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
            warehouse_id = (await OrderService._default_warehouse(session, tenant_id)).id

        for item in items:
            await InventoryService.release(
                session, tenant_id, item.variant_id, warehouse_id, item.quantity
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
    ) -> OrderPayment:
        """Capture a payment; a paid pending order becomes confirmed."""
        if method not in _PAYMENT_METHODS:
            raise ValueError(
                f"method must be one of {sorted(_PAYMENT_METHODS)}, got {method!r}"
            )
        order = await OrderService.get(session, tenant_id, order_id, with_items=False)
        captured = _positive_amount(amount)

        payment = OrderPayment(
            tenant_id=tenant_id,
            order_id=order.id,
            method=method,
            status="captured",
            amount=float(captured),
            currency=order.currency,
            provider=provider,
            paid_at=_now(),
        )
        session.add(payment)
        await session.flush()

        if order.status == "pending":
            await OrderService._transition(
                session, tenant_id, order, "confirmed", note=f"paid via {method}"
            )
        return payment

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
        order = await OrderService.get(session, tenant_id, order_id, with_items=False)
        payment = (
            await session.execute(
                select(OrderPayment).where(
                    OrderPayment.id == payment_id,
                    OrderPayment.tenant_id == tenant_id,
                    OrderPayment.order_id == order.id,
                )
            )
        ).scalar_one_or_none()
        if payment is None:
            raise NotFoundError(f"payment {payment_id} not found for order {order_id}")

        refund_amount = _positive_amount(amount)
        refunded_total = Decimal(
            str(
                (
                    await session.execute(
                        select(func.coalesce(func.sum(Refund.amount), 0)).where(
                            Refund.tenant_id == tenant_id,
                            Refund.payment_id == payment.id,
                            Refund.status != "rejected",
                        )
                    )
                ).scalar_one()
            )
        )
        payment_total = Decimal(str(payment.amount))
        if refunded_total + refund_amount > payment_total:
            raise ValueError(
                f"refund exceeds captured amount: refunded={refunded_total}, "
                f"requested={refund_amount}, captured={payment_total}"
            )

        refund = Refund(
            tenant_id=tenant_id,
            payment_id=payment.id,
            amount=float(refund_amount),
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
                "amount": float(refund_amount),
                "payment_status": payment.status,
            },
        )
        return refund

    # -------------------------------------------------------- helpers ----

    @staticmethod
    async def _get_warehouse(
        session: AsyncSession, tenant_id: UUID, warehouse_id: UUID
    ) -> Warehouse:
        warehouse = (
            await session.execute(
                select(Warehouse).where(
                    Warehouse.id == warehouse_id,
                    Warehouse.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if warehouse is None:
            raise NotFoundError(f"warehouse {warehouse_id} not found")
        return warehouse

    @staticmethod
    async def _default_warehouse(
        session: AsyncSession, tenant_id: UUID
    ) -> Warehouse:
        """The tenant's first active warehouse, bootstrapping 'Main' if needed."""
        warehouse = (
            await session.execute(
                select(Warehouse)
                .where(
                    Warehouse.tenant_id == tenant_id,
                    Warehouse.is_active.is_(True),
                )
                .order_by(Warehouse.created_at.asc(), Warehouse.name.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if warehouse is not None:
            return warehouse

        # No warehouse yet — create "Main" (race-safe: converge on one row).
        await session.execute(
            pg_insert(Warehouse)
            .values(tenant_id=tenant_id, name="Main", code="MAIN")
            .on_conflict_do_nothing(index_elements=["tenant_id", "code"])
        )
        return (
            await session.execute(
                select(Warehouse).where(
                    Warehouse.tenant_id == tenant_id,
                    Warehouse.code == "MAIN",
                )
            )
        ).scalar_one()
