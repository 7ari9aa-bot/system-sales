"""Shipment and shipping endpoints for orders."""

from __future__ import annotations

import uuid

from fastapi import Depends, Response
from pydantic import BaseModel, Field

from ._deps import (
    IfMatch,
    OrderService,
    TenantContext,
    TenantCtxDep,
    _redact_order_pii,
    _shipment_out,
    apply_etag,
    require_permission,
    router,
)


class ShipmentCreateRequest(BaseModel):
    carrier: str | None = Field(default=None, max_length=63)
    tracking_number: str | None = Field(default=None, max_length=127)
    label_url: str | None = None
    note: str | None = Field(default=None, max_length=512)


class ShipmentStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=15)


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
    return _redact_order_pii(
        {
            "id": str(order.id),
            "number": order.number,
            "status": order.status,
            "version": order.version,
            "shipping_address": order.shipping_address,
            "shipping_method": (order.extra or {}).get("shipping_method"),
        },
        ctx.permission_codes,
    )


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
