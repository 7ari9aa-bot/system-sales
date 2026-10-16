"""Common constants and validation helpers for catalog services."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

_PRODUCT_STATUSES = {"draft", "active", "archived"}

# §179 closed vocabulary — one importer cannot invent "EAN13" while another
# writes "ean-13" and split the same barcode across two rows.
IDENTIFIER_TYPES = {"gtin", "ean", "upc", "barcode", "qr_token", "external"}


def _to_decimal(value: object, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a valid number") from exc


def _positive_decimal(value: object, field: str) -> Decimal:
    amount = _to_decimal(value, field)
    if amount <= 0:
        raise ValueError(f"{field} must be greater than zero")
    return amount
