"""A medicine that may only be sold against a prescription.

A pharmacy marks a product as prescription-only and turns on the ``prescription_required``
capability for its workspace. From then on a sale that contains such a product must name the
prescription (its number, and who it is for) or the sale is refused before any order or stock
reservation exists. A shop that has not turned the capability on, and any product that is not
marked, sells exactly as before.

Nothing here is a new table: the mark lives in the product's own ``attributes`` and the reference
rides in the order's ``extra`` beside the warehouse and the invoice remark.
"""

from __future__ import annotations

from typing import Any

from app.modules.errors import ValidationError

# The product attribute that marks a prescription-only item.
PRESCRIPTION_ONLY_ATTRIBUTE = "prescription_only"
# Where the reference is kept on the order.
PRESCRIPTION_EXTRA_KEY = "prescription"


def is_prescription_only(attributes: dict | None) -> bool:
    """Whether a product's attributes mark it prescription-only (only a real ``True`` counts)."""
    return (attributes or {}).get(PRESCRIPTION_ONLY_ATTRIBUTE) is True


def clean_reference(reference: dict[str, Any] | None) -> dict[str, str] | None:
    """The prescription as it is stored: a number and the name it is for, trimmed, or ``None``.

    Both parts are needed. A number alone cannot be traced to a person and a name alone cannot be
    traced to a paper, so a half-filled reference counts as none.
    """
    if not reference:
        return None
    number = str(reference.get("number") or "").strip()
    name = str(reference.get("name") or "").strip()
    if not number or not name:
        return None
    return {"number": number, "name": name}


def ensure_prescription_given(
    *,
    required: bool,
    products: list[Any],
    reference: dict[str, Any] | None,
) -> dict[str, str] | None:
    """Refuse a sale of a prescription-only product that names no prescription.

    ``required`` is the workspace's ``prescription_required`` answer and ``products`` the products
    in the cart, both read by the caller. Returns the reference to store on the order, or ``None``
    when there is nothing to store. A reference sent with a cart that does not need one is kept
    anyway: the cashier wrote it down.
    """
    cleaned = clean_reference(reference)
    if not required:
        return cleaned
    flagged = sorted(p.title for p in products if is_prescription_only(p.attributes))
    if flagged and cleaned is None:
        raise ValidationError(
            "a prescription is required: send its number and the name it is for for "
            + ", ".join(flagged)
        )
    return cleaned
