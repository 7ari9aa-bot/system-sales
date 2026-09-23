"""ORDERS routes — order list, lifecycle actions."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from app.core.idempotency import IfMatch, apply_etag  # §17
from app.core.pagination import decode_cursor, page_slice
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.orders.models import OrderPayment, OrderStatusHistory, Shipment
from app.modules.orders.returns import ReturnsService
from app.modules.orders.service import OrderService

router = APIRouter(tags=["orders"])


class StatusChangeRequest(BaseModel):
    status: str
    note: str | None = None


class PaymentReconciliationRequest(BaseModel):
    provider_status: str = Field(min_length=1, max_length=31)
    provider_ref: str | None = Field(default=None, max_length=255)


@router.get("/orders")
async def list_orders(
    ctx: TenantCtxDep,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    # M8: the three things staff actually search orders by. Each narrows the
    # tenant-scoped page the endpoint already returns — never widens it.
    number: str | None = Query(default=None, max_length=63),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    before_created_at, before_id = decode_cursor(cursor) if cursor else (None, None)
    rows = await OrderService.list_orders(
        ctx.session,
        ctx.tenant_id,
        status=status,
        customer_id=customer_id,
        number=number,
        created_from=created_from,
        created_to=created_to,
        limit=limit + 1,
        before_created_at=before_created_at,
        before_id=before_id,
    )
    page, next_cursor = page_slice(rows, limit)
    return {
        "items": [
            {
                "id": str(o.id),
                "number": o.number,
                "customer_id": str(o.customer_id),
                "status": o.status,
                "grand_total": str(o.grand_total),
                "currency": o.currency,
                "placed_at": o.placed_at.isoformat() if o.placed_at else None,
                "created_at": o.created_at.isoformat(),
            }
            for o in page
        ],
        "next_cursor": next_cursor,
    }


@router.get("/orders/{order_id}")
async def get_order(ctx: TenantCtxDep, order_id: uuid.UUID, response: Response):
    order = await OrderService.get(ctx.session, ctx.tenant_id, order_id)
    items = getattr(order, "items", [])
    # A refund is read from the ledger, never from `status`: the two axes are
    # reported side by side so a screen can say "completed, 25 of it given back"
    # without the money overwriting where the parcel is.
    position = await OrderService.refund_position(ctx.session, ctx.tenant_id, order_id)
    # §17: advertise the CAS token the status route's If-Match expects.
    apply_etag(response, order.version)
    return {
        "id": str(order.id),
        "number": order.number,
        "status": order.status,
        "version": order.version,
        "grand_total": str(order.grand_total),
        "currency": order.currency,
        "refund_state": position["refund_state"],
        "refunded_total": str(position["refunded"]),
        "net_collected": str(position["net_collected"]),
        "items": [
            {
                "id": str(item.id),
                "title": item.title,
                "sku": item.sku,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "total": str(item.total),
            }
            for item in items
        ],
    }


@router.post("/orders/{order_id}/status")
async def change_status(
    order_id: uuid.UUID,
    body: StatusChangeRequest,
    ctx: TenantContext = Depends(require_permission("orders:write")),
    if_match: IfMatch = None,  # §17 optimistic-concurrency; absent = unconditional
):
    await OrderService.change_status(
        ctx.session,
        ctx.tenant_id,
        order_id,
        body.status,
        by_user_id=ctx.user.id,
        note=body.note,
        expected_version=if_match,  # §17 — None when header absent (backward compatible)
    )
    return {"ok": True}


@router.post("/orders/{order_id}/payments/{payment_id}/reconcile")
async def reconcile_payment(
    order_id: uuid.UUID,
    payment_id: uuid.UUID,
    body: PaymentReconciliationRequest,
    ctx: TenantContext = Depends(require_permission("orders:write")),
):
    payment = await OrderService.reconcile_payment(
        ctx.session,
        ctx.tenant_id,
        order_id,
        payment_id,
        provider_status=body.provider_status,
        provider_ref=body.provider_ref,
    )
    return {
        "id": str(payment.id),
        "status": payment.status,
        "provider_ref": payment.provider_ref,
    }


class PaymentCreateRequest(BaseModel):
    method: str = Field(min_length=1, max_length=31)
    amount: Decimal = Field(gt=0)
    provider: str | None = Field(default=None, max_length=63)
    # §47: optional, and only ever to state the obvious. A currency other than
    # the order's is refused rather than converted, so passing it can only
    # catch a mistake — never settle one.
    currency: str | None = Field(default=None, pattern="^[A-Za-z]{3}$")


class RefundCreateRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    reason: str | None = Field(default=None, max_length=512)


def _payment_out(payment: OrderPayment) -> dict:
    return {
        "id": str(payment.id),
        "order_id": str(payment.order_id),
        "method": payment.method,
        "status": payment.status,
        # Money leaves as a string of the Decimal it is stored as (§47).
        "amount": str(payment.amount),
        "currency": payment.currency,
        "provider": payment.provider,
        "provider_ref": payment.provider_ref,
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
        "created_at": payment.created_at.isoformat(),
    }


def _history_out(entry: OrderStatusHistory) -> dict:
    return {
        "id": str(entry.id),
        "order_id": str(entry.order_id),
        "from_status": entry.from_status,
        "to_status": entry.to_status,
        "changed_by_user_id": (
            str(entry.changed_by_user_id) if entry.changed_by_user_id else None
        ),
        "note": entry.note,
        "created_at": entry.created_at.isoformat(),
    }


@router.get("/orders/{order_id}/payments")
async def list_order_payments(ctx: TenantCtxDep, order_id: uuid.UUID):
    """The payments written against one order, oldest capture first."""
    rows = await OrderService.list_payments(ctx.session, ctx.tenant_id, order_id)
    return [_payment_out(p) for p in rows]


@router.get("/orders/{order_id}/status-history")
async def list_order_status_history(ctx: TenantCtxDep, order_id: uuid.UUID):
    """The order's timeline: every transition the status path recorded."""
    rows = await OrderService.list_status_history(ctx.session, ctx.tenant_id, order_id)
    return [_history_out(h) for h in rows]


@router.post("/orders/{order_id}/payments", status_code=201)
async def create_payment(
    order_id: uuid.UUID,
    body: PaymentCreateRequest,
    ctx: TenantContext = Depends(require_permission("orders:write")),
):
    """Record a captured payment (cash/POS/manual). A paid pending order is
    confirmed and its stock reservations convert into a sale."""
    payment = await OrderService.add_payment(
        ctx.session,
        ctx.tenant_id,
        order_id,
        method=body.method,
        amount=body.amount,
        provider=body.provider,
        currency=body.currency,
    )
    return {
        "id": str(payment.id),
        "status": payment.status,
        "amount": str(payment.amount),
        "currency": payment.currency,
    }


@router.post("/orders/{order_id}/payments/{payment_id}/refunds", status_code=201)
async def create_refund(
    order_id: uuid.UUID,
    payment_id: uuid.UUID,
    body: RefundCreateRequest,
    ctx: TenantContext = Depends(require_permission("orders:write")),
):
    """Refund a captured payment (validated against the captured amount)."""
    refund = await OrderService.register_refund(
        ctx.session,
        ctx.tenant_id,
        order_id,
        payment_id,
        amount=body.amount,
        reason=body.reason,
        by_user_id=ctx.user.id,
    )
    return {
        "id": str(refund.id),
        "status": refund.status,
        "amount": str(refund.amount),
    }


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("orders:write")),
):
    """Cancel an open order and release its reserved stock (idempotent via
    the row lock: two concurrent cancels cannot double-release)."""
    await OrderService.cancel_order(
        ctx.session, ctx.tenant_id, order_id, by_user_id=ctx.user.id
    )
    return {"ok": True}


class ReturnRequest(BaseModel):
    reason: str = Field(default="customer_return", max_length=31)


@router.post("/orders/{order_id}/return")
async def return_order(
    order_id: uuid.UUID,
    body: ReturnRequest,
    ctx: TenantContext = Depends(require_permission("orders:write")),
):
    """Return a parcel: restock what left the warehouse, then close the order.

    The two steps run as a saga (ADR-052), so a failure halfway leaves the
    stock exactly where it was and a `failed` saga row saying what happened —
    never goods back on the shelf under an order that still claims they sold.
    Money is NOT touched here: a refund stays an approved action on a payment.
    """
    saga = await ReturnsService.process_return(
        ctx.session, ctx.tenant_id, order_id, reason=body.reason, by_user_id=ctx.user.id
    )
    order = await OrderService.get(ctx.session, ctx.tenant_id, order_id, with_items=False)
    return {
        "ok": True,
        "saga_id": str(saga.id),
        "saga_status": saga.status,
        "order_status": order.status,
    }


class ShipmentCreateRequest(BaseModel):
    carrier: str | None = Field(default=None, max_length=63)
    tracking_number: str | None = Field(default=None, max_length=127)
    label_url: str | None = None
    note: str | None = Field(default=None, max_length=512)


class ShipmentStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=15)


def _shipment_out(shipment: Shipment) -> dict:
    return {
        "id": str(shipment.id),
        "order_id": str(shipment.order_id),
        "carrier": shipment.carrier,
        "tracking_number": shipment.tracking_number,
        "status": shipment.status,
        "shipped_at": shipment.shipped_at.isoformat() if shipment.shipped_at else None,
        "delivered_at": (
            shipment.delivered_at.isoformat() if shipment.delivered_at else None
        ),
        "label_url": shipment.label_url,
    }


class ShippingUpdateRequest(BaseModel):
    shipping_address: dict | None = None
    shipping_method: str | None = Field(default=None, max_length=31)


@router.get("/orders/{order_id}/shipments")
async def list_shipments(ctx: TenantCtxDep, order_id: uuid.UUID):
    await OrderService.get(ctx.session, ctx.tenant_id, order_id, with_items=False)
    rows = await OrderService.list_shipments(ctx.session, ctx.tenant_id, order_id)
    return [_shipment_out(s) for s in rows]


@router.patch("/orders/{order_id}/shipping")
async def update_shipping(
    order_id: uuid.UUID,
    body: ShippingUpdateRequest,
    response: Response,
    ctx: TenantContext = Depends(require_permission("orders:write")),
    if_match: IfMatch = None,  # §17 — the row has a version, so it can be lost
):
    """Correct where an open order is going. Not a status move: the order has
    not left, and saying so is what the audit row and the version are for."""
    order = await OrderService.update_shipping(
        ctx.session,
        ctx.tenant_id,
        order_id,
        shipping_address=body.shipping_address,
        shipping_method=body.shipping_method,
        by_user_id=ctx.user.id,
        expected_version=if_match,
    )
    apply_etag(response, order.version)
    return {
        "id": str(order.id),
        "number": order.number,
        "status": order.status,
        "version": order.version,
        "shipping_address": order.shipping_address,
        "shipping_method": (order.extra or {}).get("shipping_method"),
    }


@router.post("/orders/{order_id}/shipments", status_code=201)
async def create_shipment(
    order_id: uuid.UUID,
    body: ShipmentCreateRequest,
    ctx: TenantContext = Depends(require_permission("orders:write")),
):
    """Record the carrier + tracking number, and move the order to `shipped`."""
    shipment = await OrderService.create_shipment(
        ctx.session,
        ctx.tenant_id,
        order_id,
        carrier=body.carrier,
        tracking_number=body.tracking_number,
        label_url=body.label_url,
        note=body.note,
        by_user_id=ctx.user.id,
    )
    return _shipment_out(shipment)


@router.post("/shipments/{shipment_id}/status")
async def set_shipment_status(
    shipment_id: uuid.UUID,
    body: ShipmentStatusRequest,
    ctx: TenantContext = Depends(require_permission("orders:write")),
):
    """A carrier scan. `delivered` also moves the order shipped -> delivered."""
    shipment = await OrderService.set_shipment_status(
        ctx.session,
        ctx.tenant_id,
        shipment_id,
        body.status,
        by_user_id=ctx.user.id,
    )
    return _shipment_out(shipment)


class OrderItemRequest(BaseModel):
    variant_id: uuid.UUID
    quantity: int = Field(gt=0)


class CreateOrderRequest(BaseModel):
    customer_id: uuid.UUID
    items: list[OrderItemRequest] = Field(min_length=1)
    channel: str = "dashboard"
    shipping_address: dict | None = None
    # §47: the money components of the order. Each is optional (absent = zero),
    # and `grand_total` is computed from them rather than copied from the
    # subtotal, so what the merchant states is what the customer is charged.
    discount_total: Decimal | None = Field(default=None, ge=0)
    shipping_total: Decimal | None = Field(default=None, ge=0)
    tax_total: Decimal | None = Field(default=None, ge=0)


@router.post("/orders", status_code=201)
async def create_order(
    body: CreateOrderRequest,
    ctx: TenantContext = Depends(require_permission("orders:write")),
):
    """Transactional order creation: stock reservation + snapshot + outbox."""
    order = await OrderService.create_order(
        ctx.session,
        ctx.tenant_id,
        body.customer_id,
        [{"variant_id": i.variant_id, "quantity": i.quantity} for i in body.items],
        channel=body.channel,
        shipping_address=body.shipping_address,
        currency=ctx.currency,
        discount_total=body.discount_total,
        shipping_total=body.shipping_total,
        tax_total=body.tax_total,
    )
    return {
        "id": str(order.id),
        "number": order.number,
        "status": order.status,
        "subtotal": str(order.subtotal),
        "discount_total": str(order.discount_total),
        "shipping_total": str(order.shipping_total),
        "tax_total": str(order.tax_total),
        "grand_total": str(order.grand_total),
        "currency": order.currency,
    }
