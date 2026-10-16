"""Shared dependencies, routers, models, and helpers for orders routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.core.field_auth import PII_FIELDS, redact_fields
from app.core.idempotency import IfMatch, apply_etag  # §17
from app.core.pagination import decode_cursor, page_slice
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.orders.models import OrderPayment, OrderStatusHistory, Shipment
from app.modules.orders.returns import ReturnsService
from app.modules.orders.service import OrderService

router = APIRouter(tags=["orders"])

_ORDER_PII_FIELDS = PII_FIELDS | {"shipping_address"}


def _redact_order_pii(payload: dict, permission_codes: set[str]) -> dict:
    """Apply the §146 field guard to one order payload.

    Shared by the read AND the write echo on purpose. `staff` holds
    `orders:write` without `pii:read` (`scripts/provision.py`), so a guard on
    `GET /orders/{id}` alone is not a guard: the same caller reads the denied
    address back out of the PATCH response beside it, having changed nothing but
    a shipping method. One seam, both routes.
    """
    if "pii:read" in permission_codes:
        return payload
    return redact_fields(
        payload,
        permission_codes=permission_codes,
        fields_to_redact=_ORDER_PII_FIELDS,
    )


def _order_detail_out(order, position: dict, *, permission_codes: set[str]) -> dict:
    """One order, read the way the correction screens read it (§146-guarded)."""
    items = getattr(order, "items", [])
    payload = {
        "id": str(order.id),
        "number": order.number,
        "status": order.status,
        "version": order.version,
        "grand_total": str(order.grand_total),
        "currency": order.currency,
        "refund_state": position["refund_state"],
        "refunded_total": str(position["refunded"]),
        "net_collected": str(position["net_collected"]),
        "shipping_address": order.shipping_address,
        "shipping_method": (order.extra or {}).get("shipping_method"),
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
    return _redact_order_pii(payload, permission_codes)


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
        "changed_by_user_id": (str(entry.changed_by_user_id) if entry.changed_by_user_id else None),
        "note": entry.note,
        "created_at": entry.created_at.isoformat(),
    }


def _shipment_out(shipment: Shipment) -> dict:
    return {
        "id": str(shipment.id),
        "order_id": str(shipment.order_id),
        "carrier": shipment.carrier,
        "tracking_number": shipment.tracking_number,
        "status": shipment.status,
        "shipped_at": shipment.shipped_at.isoformat() if shipment.shipped_at else None,
        "delivered_at": (shipment.delivered_at.isoformat() if shipment.delivered_at else None),
        "label_url": shipment.label_url,
    }


__all__ = [
    "IfMatch",
    "OrderPayment",
    "OrderService",
    "OrderStatusHistory",
    "PII_FIELDS",
    "Response",
    "ReturnsService",
    "Shipment",
    "TenantContext",
    "TenantCtxDep",
    "_ORDER_PII_FIELDS",
    "_history_out",
    "_order_detail_out",
    "_payment_out",
    "_redact_order_pii",
    "_shipment_out",
    "apply_etag",
    "decode_cursor",
    "page_slice",
    "redact_fields",
    "require_permission",
    "router",
]
