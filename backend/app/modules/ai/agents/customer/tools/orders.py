"""The customer's own purchases: get_my_orders (looked up by invoice number).

Split out of the former single-file ``customer/tools.py``; the code is unchanged.
"""

from __future__ import annotations

import uuid

from pydantic import Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.modules.ai.agents.customer.tools._shared import _money, _parse_bound_id, _StrictArgs


class GetMyOrdersArgs(_StrictArgs):
    """The invoice number the customer read off their receipt. Nothing else.

    The number is required, never optional: the agent opens ONE invoice the
    customer names, it never lists invoices. The store decided that the number
    on a purchase receipt is not sensitive, so on every channel the number alone
    opens the invoice (no phone or identity match).
    """

    number: str = Field(min_length=1, max_length=31)


_NOT_FOUND_HINT = "مفيش فاتورة بالرقم ده. اطلب منه يراجع الرقم المطبوع على الإيصال وكمّل معاه."


async def _get_my_orders(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    number: str,
    context: dict | None = None,
) -> dict:
    """Read-only: ONE invoice by the number the customer quotes, with its returns.

    The invoice number is the whole proof, on every channel: a customer who
    bought at the till reads it off the receipt and can ask about it from
    Telegram, Messenger or anywhere else. There is deliberately no phone or
    identity match (the store judged a purchase receipt number not sensitive).

    What stays bound by the server: the tenant (one store never sees another's
    invoices) and the conversation (the tool refuses to run without a customer
    bound to it). The invoice is looked up by exact number, soft-deleted
    invoices are hidden, and the result never carries the buyer's name or
    phone. Tables are read with bound SQL rather than imported
    (``ai -> orders`` / ``ai -> pos`` would close a module cycle, see
    tests/test_module_boundaries.py). Nothing here writes; a return or an
    exchange is staff work.
    """
    if _parse_bound_id((context or {}).get("customer_id")) is None:
        raise DomainError("no customer bound to this tool call")

    orders = (
        (
            await session.execute(
                text(
                    "SELECT o.id, o.number, o.status, o.currency, o.subtotal, "
                    "o.discount_total, o.grand_total, o.placed_at "
                    "FROM orders o "
                    "WHERE o.tenant_id = :tenant_id AND o.number = :number "
                    "AND o.deleted_at IS NULL "
                    "LIMIT 1"
                ),
                {"tenant_id": tenant_id, "number": number.strip()},
            )
        )
        .mappings()
        .all()
    )
    if not orders:
        return {"orders": [], "hint": _NOT_FOUND_HINT}

    order_ids = [row["id"] for row in orders]
    items = (
        (
            await session.execute(
                text(
                    "SELECT i.order_id, i.title, i.quantity, i.unit_price, i.total, "
                    "i.variant_id, v.product_id, v.option_values "
                    "FROM order_items i "
                    "LEFT JOIN product_variants v ON v.id = i.variant_id "
                    "AND v.tenant_id = i.tenant_id "
                    "WHERE i.tenant_id = :tenant_id AND i.order_id = ANY(:order_ids) "
                    "ORDER BY i.created_at, i.id"
                ),
                {"tenant_id": tenant_id, "order_ids": order_ids},
            )
        )
        .mappings()
        .all()
    )
    returned = (
        (
            await session.execute(
                text(
                    "SELECT order_id, SUM(quantity) AS quantity, "
                    "SUM(refund_total) AS refund_total "
                    "FROM pos_return_lines "
                    "WHERE tenant_id = :tenant_id AND order_id = ANY(:order_ids) "
                    "GROUP BY order_id"
                ),
                {"tenant_id": tenant_id, "order_ids": order_ids},
            )
        )
        .mappings()
        .all()
    )
    items_by_order: dict[object, list[dict]] = {}
    for item in items:
        items_by_order.setdefault(item["order_id"], []).append(
            {
                "title": item["title"],
                "quantity": int(item["quantity"]),
                "unit_price": _money(item["unit_price"]),
                "total": _money(item["total"]),
                # What the customer bought, so the agent can look up the same
                # product's other sizes/colours with get_product_details. The
                # ids are read from the invoice, never supplied by the model.
                "product_id": str(item["product_id"]) if item["product_id"] else None,
                "variant_id": str(item["variant_id"]) if item["variant_id"] else None,
                "option_values": item["option_values"] or {},
            }
        )
    returns_by_order = {row["order_id"]: row for row in returned}

    result_orders = []
    for row in orders:
        back = returns_by_order.get(row["id"])
        result_orders.append(
            {
                "number": row["number"],
                "status": row["status"],
                "placed_at": row["placed_at"].date().isoformat() if row["placed_at"] else None,
                "currency": row["currency"],
                "subtotal": _money(row["subtotal"]),
                "discount_total": _money(row["discount_total"]),
                "grand_total": _money(row["grand_total"]),
                "items": items_by_order.get(row["id"], []),
                "returned": (
                    {
                        "quantity": int(back["quantity"]),
                        "refund_total": _money(back["refund_total"]),
                    }
                    if back
                    else None
                ),
            }
        )
    return {"orders": result_orders}
