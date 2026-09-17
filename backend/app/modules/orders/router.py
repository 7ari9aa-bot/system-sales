"""ORDERS routes — order list, lifecycle actions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.modules.identity.deps import TenantCtxDep
from app.modules.orders.service import OrderService

router = APIRouter(tags=["orders"])


class StatusChangeRequest(BaseModel):
    status: str
    note: str | None = None


@router.get("/orders")
async def list_orders(
    ctx: TenantCtxDep, status: str | None = None, limit: int = 50, offset: int = 0
):
    orders = await OrderService.list_orders(
        ctx.session, ctx.tenant_id, status=status, limit=limit, offset=offset
    )
    return [
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
        for o in orders
    ]


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
async def change_status(ctx: TenantCtxDep, order_id: uuid.UUID, body: StatusChangeRequest):
    await OrderService.change_status(
        ctx.session,
        ctx.tenant_id,
        order_id,
        body.status,
        by_user_id=ctx.user.id,
        note=body.note,
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
async def create_order(ctx: TenantCtxDep, body: CreateOrderRequest):
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
