"""Payment and refund endpoints for orders."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from ._deps import (
    OrderService,
    OrdersWriteCtx,
    TenantCtxDep,
    _history_out,
    _payment_out,
    router,
)


class PaymentReconciliationRequest(BaseModel):
    provider_status: str = Field(min_length=1, max_length=31)
    provider_ref: str | None = Field(default=None, max_length=255)


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


@router.post("/orders/{order_id}/payments/{payment_id}/reconcile")
async def reconcile_payment(
    order_id: uuid.UUID,
    payment_id: uuid.UUID,
    body: PaymentReconciliationRequest,
    ctx: OrdersWriteCtx,
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
    ctx: OrdersWriteCtx,
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
    ctx: OrdersWriteCtx,
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
