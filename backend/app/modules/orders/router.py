"""ORDERS routes — order list, lifecycle actions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from app.core.idempotency import IfMatch, apply_etag  # §17
from app.core.pagination import decode_cursor, page_slice
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.orders.models import Shipment
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
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    before_created_at, before_id = decode_cursor(cursor) if cursor else (None, None)
    rows = await OrderService.list_orders(
        ctx.session,
        ctx.tenant_id,
        status=status,
        customer_id=customer_id,
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
    # §17: advertise the CAS token the status route's If-Match expects.
    apply_etag(response, order.version)
    return {
        "id": str(order.id),
        "number": order.number,
        "status": order.status,
        "version": order.version,
        "grand_total": str(order.grand_total),
        "currency": order.currency,
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
    amount: float = Field(gt=0)
    provider: str | None = Field(default=None, max_length=63)


class RefundCreateRequest(BaseModel):
    amount: float = Field(gt=0)
    reason: str | None = Field(default=None, max_length=512)


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


@router.get("/orders/{order_id}/shipments")
async def list_shipments(ctx: TenantCtxDep, order_id: uuid.UUID):
    await OrderService.get(ctx.session, ctx.tenant_id, order_id, with_items=False)
    rows = await OrderService.list_shipments(ctx.session, ctx.tenant_id, order_id)
    return [_shipment_out(s) for s in rows]


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
    )
    return {
        "id": str(order.id),
        "number": order.number,
        "status": order.status,
        "grand_total": str(order.grand_total),
        "currency": order.currency,
    }
