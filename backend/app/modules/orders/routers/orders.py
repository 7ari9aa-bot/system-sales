"""Core order lifecycle endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, Query, Response
from pydantic import BaseModel, Field

from ._deps import (
    IfMatch,
    OrderService,
    ReturnsService,
    TenantContext,
    TenantCtxDep,
    _order_detail_out,
    apply_etag,
    decode_cursor,
    page_slice,
    require_permission,
    router,
)


class StatusChangeRequest(BaseModel):
    status: str
    note: str | None = None


class ReturnRequest(BaseModel):
    reason: str = Field(default="customer_return", max_length=31)


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


@router.get("/orders")
async def list_orders(
    ctx: TenantCtxDep,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    # M8: the three things staff actually search orders by. Each narrows the
    # tenant-scoped page the endpoint already returns — never widens it.
    number: Annotated[str | None, Query(max_length=63)] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
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
    # A refund is read from the ledger, never from `status`: the two axes are
    # reported side by side so a screen can say "completed, 25 of it given back"
    # without the money overwriting where the parcel is.
    position = await OrderService.refund_position(ctx.session, ctx.tenant_id, order_id)
    # §17: advertise the CAS token the status route's If-Match expects.
    apply_etag(response, order.version)
    return _order_detail_out(order, position, permission_codes=ctx.permission_codes)


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


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("orders:write")),
):
    """Cancel an open order and release its reserved stock (idempotent via
    the row lock: two concurrent cancels cannot double-release)."""
    await OrderService.cancel_order(ctx.session, ctx.tenant_id, order_id, by_user_id=ctx.user.id)
    return {"ok": True}


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
