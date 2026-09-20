"""ORDERS routes — order list, lifecycle actions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.pagination import decode_cursor, page_slice
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
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
async def get_order(ctx: TenantCtxDep, order_id: uuid.UUID):
    order = await OrderService.get(ctx.session, ctx.tenant_id, order_id)
    items = getattr(order, "items", [])
    return {
        "id": str(order.id),
        "number": order.number,
        "status": order.status,
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
):
    await OrderService.change_status(
        ctx.session,
        ctx.tenant_id,
        order_id,
        body.status,
        by_user_id=ctx.user.id,
        note=body.note,
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
