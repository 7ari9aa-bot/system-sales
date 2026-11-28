"""A cart a customer sent from our WhatsApp catalog (an `order` message), made safe to show.

Meta's webhook for it (documented at developers.facebook.com, "Order messages webhook reference")
carries `order.catalog_id`, an optional `order.text`, and `order.product_items[]`, each with
`product_retailer_id`, `quantity`, `item_price` and `currency`.

Two rules shape this module:

* The customer's phone sent every number in it. A price here is what the customer's app showed,
  NOT what we charge: nothing in this module is a price we would bill. It is for the agent to read,
  and the order that gets booked later is priced from our own catalog.
* The payload is untrusted input from outside, so only a small checked shape ever leaves: strings
  are cut to a length, numbers must be finite and sane, a wrong type is dropped and not guessed.

A cart that cannot be read at all returns None, so the caller keeps its plain fallback instead of
showing an empty card.
"""

from __future__ import annotations

import math
from typing import Any

MAX_ITEMS = 100  # Meta caps a cart well below this; this only bounds a hostile payload.
MAX_TEXT = 1000
MAX_ID = 200
MAX_QUANTITY = 100_000
MAX_PRICE = 1_000_000_000
_CURRENCY_LEN = 3


def _clip(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    """A real finite number, else None. Booleans are not numbers here (True would read as 1)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _quantity(value: Any) -> int | None:
    n = _number(value)
    if n is None or n != int(n) or not 1 <= n <= MAX_QUANTITY:
        return None
    return int(n)


def _price(value: Any) -> float | None:
    n = _number(value)
    return n if n is not None and 0 <= n <= MAX_PRICE else None


def _currency(value: Any) -> str:
    # Exactly three letters or nothing. Cutting a longer word to three ("DOLLAR" -> "DOL")
    # would invent a code the customer never sent.
    code = value.strip().upper() if isinstance(value, str) else ""
    return code if len(code) == _CURRENCY_LEN and code.isascii() and code.isalpha() else ""


def parse_order(raw_message: Any) -> dict | None:
    """The checked cart from one inbound WhatsApp `order` message, or None.

    `raw_message` is the provider message as stored (`{"type": "order", "order": {...}}`).
    Lines with no usable product id or quantity are dropped, not guessed: a cart of three lines
    with one broken shows two, and `skipped` says one was left out so the agent is not misled.
    """
    if not isinstance(raw_message, dict) or raw_message.get("type") != "order":
        return None
    order = raw_message.get("order")
    if not isinstance(order, dict):
        return None
    lines = order.get("product_items")
    if not isinstance(lines, list):
        return None

    items: list[dict] = []
    skipped = 0
    for line in lines[:MAX_ITEMS]:
        if not isinstance(line, dict):
            skipped += 1
            continue
        retailer_id = _clip(line.get("product_retailer_id"), MAX_ID)
        quantity = _quantity(line.get("quantity"))
        if not retailer_id or quantity is None:
            skipped += 1
            continue
        items.append(
            {
                "retailer_id": retailer_id,
                "quantity": quantity,
                "shown_price": _price(line.get("item_price")),
                "currency": _currency(line.get("currency")),
            }
        )
    skipped += max(0, len(lines) - MAX_ITEMS)
    if not items:
        return None

    return {
        "catalog_id": _clip(order.get("catalog_id"), MAX_ID),
        "note": _clip(order.get("text"), MAX_TEXT),
        "items": items,
        "skipped": skipped,
    }


def order_summary(cart: dict) -> str:
    """One readable line per product, for the message body (search, previews, notifications).

    It states quantities and product ids only. No money: the customer's shown price is not ours.
    """
    lines = [f"{i['quantity']} x {i['retailer_id']}" for i in cart["items"]]
    if cart.get("skipped"):
        lines.append(f"(+{cart['skipped']} unreadable)")
    if cart.get("note"):
        lines.append(cart["note"])
    return "\n".join(lines)
