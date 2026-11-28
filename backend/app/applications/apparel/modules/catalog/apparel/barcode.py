"""Internal barcodes: EAN-13 numbers a shop prints itself for stock that has none.

Most clothing bought wholesale has no manufacturer barcode, so the shop numbers its own. The
number is a real EAN-13 so any scanner reads it, and it starts with ``2``: GS1 reserves the 20 to
29 range for in-store use, so it can never collide with a genuine product's GTIN.

Pure functions: no database, no clock. The sequence comes from the caller (a gap-free counter
taken under a row lock), this module only turns it into a valid number and checks one.
"""

from __future__ import annotations

import re

from app.modules.errors import ValidationError

INTERNAL_PREFIX = "2"
MAX_SEQUENCE = 10**11 - 1  # 11 digits after the prefix: 100 billion labels per shop
_DIGITS = re.compile(r"^\d{13}$")


def check_digit(first_twelve: str) -> int:
    """The EAN-13 check digit: weights 1,3,1,3... from the left over the first 12 digits."""
    if not re.fullmatch(r"\d{12}", first_twelve):
        raise ValidationError("an EAN-13 body must be exactly 12 digits")
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first_twelve))
    return (10 - total % 10) % 10


def internal_ean13(sequence: int) -> str:
    """The shop's own barcode for the ``sequence``-th labelled item (1, 2, 3...)."""
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise ValidationError("sequence must be a whole number")
    if sequence < 1 or sequence > MAX_SEQUENCE:
        raise ValidationError(f"sequence must be between 1 and {MAX_SEQUENCE}")
    body = f"{INTERNAL_PREFIX}{sequence:011d}"
    return f"{body}{check_digit(body)}"


def is_valid_ean13(value: object) -> bool:
    """True when ``value`` is 13 digits whose last one is the correct check digit."""
    text = str(value).strip()
    return bool(_DIGITS.fullmatch(text)) and check_digit(text[:12]) == int(text[12])


def is_internal(value: object) -> bool:
    """True for a valid EAN-13 in the in-store range (this shop's own, not a manufacturer's)."""
    text = str(value).strip()
    return is_valid_ean13(text) and text.startswith(INTERNAL_PREFIX)


# Bar patterns for EAN-13 (see ISO/IEC 15420). Left half uses A or B sets chosen by the first
# digit, right half uses C. Used to draw a label without any external library.
_L = (
    "0001101",
    "0011001",
    "0010011",
    "0111101",
    "0100011",
    "0110001",
    "0101111",
    "0111011",
    "0110111",
    "0001011",
)
_G = (
    "0100111",
    "0110011",
    "0011011",
    "0100001",
    "0011101",
    "0111001",
    "0000101",
    "0010001",
    "0001001",
    "0010111",
)
_R = (
    "1110010",
    "1100110",
    "1101100",
    "1000010",
    "1011100",
    "1001110",
    "1010000",
    "1000100",
    "1001000",
    "1110100",
)
_PARITY = (
    "LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
    "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL",
)  # fmt: skip


def bars(value: object) -> str:
    """The 95 modules of an EAN-13 as a string of 1 (bar) and 0 (space), guards included."""
    text = str(value).strip()
    if not is_valid_ean13(text):
        raise ValidationError(f"{text!r} is not a valid EAN-13")
    parity = _PARITY[int(text[0])]
    left = "".join((_L if p == "L" else _G)[int(d)] for p, d in zip(parity, text[1:7], strict=True))
    right = "".join(_R[int(d)] for d in text[7:])
    return f"101{left}01010{right}101"
