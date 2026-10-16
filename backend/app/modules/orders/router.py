"""ORDERS routes — order list, lifecycle actions.

Re-export aggregator for decomposed orders routers package.
"""

from __future__ import annotations

from app.modules.orders.routers import router
from app.modules.orders.routers._deps import (
    _ORDER_PII_FIELDS,
    _history_out,
    _order_detail_out,
    _payment_out,
    _redact_order_pii,
    _shipment_out,
)
from app.modules.orders.routers.orders import (
    CreateOrderRequest,
    OrderItemRequest,
    ReturnRequest,
    StatusChangeRequest,
    cancel_order,
    change_status,
    create_order,
    get_order,
    list_orders,
    return_order,
)
from app.modules.orders.routers.payments import (
    PaymentCreateRequest,
    PaymentReconciliationRequest,
    RefundCreateRequest,
    create_payment,
    create_refund,
    list_order_payments,
    list_order_status_history,
    reconcile_payment,
)
from app.modules.orders.routers.shipments import (
    ShipmentCreateRequest,
    ShipmentStatusRequest,
    ShippingUpdateRequest,
    create_shipment,
    list_shipments,
    set_shipment_status,
    update_shipping,
)

# Preserve module qualification for introspection and test sweeps
for _endpoint in (
    list_orders,
    get_order,
    change_status,
    reconcile_payment,
    list_order_payments,
    list_order_status_history,
    create_payment,
    create_refund,
    cancel_order,
    return_order,
    list_shipments,
    update_shipping,
    create_shipment,
    set_shipment_status,
    create_order,
):
    _endpoint.__module__ = "app.modules.orders.router"

__all__ = [
    "CreateOrderRequest",
    "OrderItemRequest",
    "PaymentCreateRequest",
    "PaymentReconciliationRequest",
    "RefundCreateRequest",
    "ReturnRequest",
    "ShipmentCreateRequest",
    "ShipmentStatusRequest",
    "ShippingUpdateRequest",
    "StatusChangeRequest",
    "_ORDER_PII_FIELDS",
    "_history_out",
    "_order_detail_out",
    "_payment_out",
    "_redact_order_pii",
    "_shipment_out",
    "cancel_order",
    "change_status",
    "create_order",
    "create_payment",
    "create_refund",
    "create_shipment",
    "get_order",
    "list_order_payments",
    "list_order_status_history",
    "list_orders",
    "list_shipments",
    "reconcile_payment",
    "return_order",
    "router",
    "set_shipment_status",
    "update_shipping",
]
