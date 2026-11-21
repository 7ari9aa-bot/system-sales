"""Turn a merchant's cell text into a clean value, or say precisely why it cannot be one.

Pure functions. A merchant types prices as ``١٢٥٫٥٠``, ``1,250.50``, ``1.250,50`` or ``125 ج.م``,
and pastes SKUs with trailing spaces and invisible characters. Each parser returns the value or
raises ``CellError`` with a stable ``code`` (what the report groups by) and a message.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

# Arabic-Indic, Persian digits and the Arabic decimal/thousands separators fold to ASCII.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")
# zero-width and bidi marks that arrive when text is copied from a chat or a web page
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff\u00a0]")
_CURRENCY_WORDS = re.compile(r"(egp|usd|sar|aed|le|l\.e\.|جنيه|ج\.م|جم|ريال|درهم|\$|£|€)", re.I)

MAX_MONEY = Decimal("99999999.99")  # MONEY is Numeric(14, 2); keep a safe ceiling below it
MAX_QUANTITY = Decimal("1000000")  # a sanity bound against a typo, mirrors the ledger's ceiling
SKU_MAX = 63
BARCODE_MAX = 127
TITLE_MAX = 255
SLUG_MAX = 255


class CellError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def clean_text(value: object) -> str:
    """NFKC, invisible characters removed, whitespace collapsed, trimmed."""
    text = unicodedata.normalize("NFKC", "" if value is None else str(value))
    return re.sub(r"\s+", " ", _INVISIBLE.sub("", text)).strip()


def parse_decimal(raw: object, *, field: str) -> Decimal | None:
    """``None`` for a blank cell. Understands ``1,250.50``, ``1.250,50``, ``١٢٥٫٥`` and units."""
    text = clean_text(raw)
    if not text:
        return None
    text = _CURRENCY_WORDS.sub("", text.translate(_DIGITS)).replace(" ", "")
    if not text or not re.fullmatch(r"[+-]?[0-9.,]+", text):
        raise CellError("not_a_number", f"{field} is not a number")
    last_dot, last_comma = text.rfind("."), text.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        # both present: the one that comes last is the decimal mark, the other groups thousands
        decimal_mark = "." if last_dot > last_comma else ","
        thousands = "," if decimal_mark == "." else "."
        text = text.replace(thousands, "").replace(decimal_mark, ".")
    elif last_comma >= 0:
        # a lone comma is a decimal mark only when 1-2 digits follow it; "1,250" is a thousand
        text = (
            text.replace(",", ".")
            if len(text) - last_comma - 1 in (1, 2)
            else text.replace(",", "")
        )
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        raise CellError("not_a_number", f"{field} is not a number") from None


def parse_price(raw: object, *, field: str = "price", allow_blank: bool = False) -> Decimal | None:
    """A sellable price: greater than zero, at most two decimals once rounded, within the column."""
    value = parse_decimal(raw, field=field)
    if value is None:
        if allow_blank:
            return None
        raise CellError("required", f"{field} is required")
    if value <= 0:
        raise CellError("not_positive", f"{field} must be greater than zero")
    if value > MAX_MONEY:
        raise CellError("too_large", f"{field} is too large")
    return value.quantize(Decimal("0.01"))


def parse_cost(raw: object) -> Decimal | None:
    """A cost may be blank, and zero is a real cost (a free sample); negative is not."""
    value = parse_decimal(raw, field="cost")
    if value is None:
        return None
    if value < 0:
        raise CellError("negative", "cost cannot be negative")
    if value > MAX_MONEY:
        raise CellError("too_large", "cost is too large")
    return value.quantize(Decimal("0.01"))


def parse_quantity(raw: object) -> Decimal:
    """Opening stock: a whole, non-negative number of units. Zero is allowed (nothing on hand)."""
    value = parse_decimal(raw, field="quantity")
    if value is None:
        raise CellError("required", "quantity is required")
    if value < 0:
        raise CellError("negative", "quantity cannot be negative")
    if value != value.to_integral_value():
        raise CellError("not_whole", "quantity must be a whole number")
    if value > MAX_QUANTITY:
        raise CellError("too_large", "quantity is implausibly large")
    return value


def parse_code(raw: object, *, field: str, max_len: int) -> str | None:
    """A SKU or barcode: trimmed, no inner spaces/controls. Excel's ``1.23E+12`` is refused.

    A barcode typed into a General-format cell is silently turned into scientific notation, and
    the digits after the 15th are replaced by zeros. That cannot be repaired, only rejected.
    """
    text = clean_text(raw)
    if not text:
        return None
    if re.fullmatch(r"[0-9]+(\.[0-9]+)?[eE][+-]?[0-9]+", text):
        raise CellError(
            "scientific_notation",
            f"{field} looks like scientific notation ({text}); format the column as Text",
        )
    if re.search(r"\s", text):
        raise CellError("has_spaces", f"{field} contains spaces")
    if len(text) > max_len:
        raise CellError("too_long", f"{field} is longer than {max_len} characters")
    return text


IMAGE_URL_MAX = 2000
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")


def parse_image_url(raw: object) -> str:
    """A link to one picture: http(s) only, no credentials, no spaces, a sane length.

    This only checks the SHAPE of the text. Whether the host is a public one is decided when the
    picture is fetched (``app.core.net_guard`` runs on every hop), because a name can resolve
    differently later and a check made here would be stale by then. A link without an image
    extension is allowed (CDNs often serve ``/image?id=5``): the downloaded bytes are checked by
    their signature instead.
    """
    text = clean_text(raw)
    if not text:
        raise CellError("required", "image is required")
    if len(text) > IMAGE_URL_MAX:
        raise CellError("too_long", f"image link is longer than {IMAGE_URL_MAX} characters")
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise CellError("not_a_link", "image must be a full http(s) link")
    if parts.username or parts.password:
        raise CellError("not_a_link", "image link must not carry a user name or password")
    if re.search(r"\s", text):
        raise CellError("has_spaces", "image link contains spaces")
    return text


def looks_like_image_path(url: str) -> bool:
    """True when the link's path ends in a picture extension (informational, never a gate)."""
    return urlsplit(url).path.lower().endswith(_IMAGE_EXTENSIONS)


def parse_title(raw: object, *, field: str = "title") -> str:
    text = clean_text(raw)
    if not text:
        raise CellError("required", f"{field} is required")
    if len(text) > TITLE_MAX:
        raise CellError("too_long", f"{field} is longer than {TITLE_MAX} characters")
    return text


def parse_status(raw: object) -> str | None:
    """draft | active | archived, with the Arabic words a merchant would use."""
    text = clean_text(raw).lower()
    if not text:
        return None
    table = {
        "draft": "draft", "مسودة": "draft", "مسوده": "draft",
        "active": "active", "نشط": "active", "فعال": "active", "مفعل": "active",
        "archived": "archived", "مؤرشف": "archived", "مخفي": "archived", "ارشيف": "archived",
    }  # fmt: skip
    if text not in table:
        raise CellError("bad_status", "status must be draft, active or archived")
    return table[text]


def slugify(value: str) -> str:
    """A URL-safe handle that keeps Arabic letters (the catalog's slug column allows them)."""
    text = clean_text(value).lower()
    text = re.sub(r"[^0-9a-z\u0600-\u06FF]+", "-", text).strip("-")
    return text[:SLUG_MAX]


ITEM_CODE_MAX = 100
_CODE_TYPE_ALIASES = {"EGS": "EGS", "GS1": "GS1", "GTIN": "GS1"}
_GTIN_LENGTHS = (8, 12, 13, 14)


def parse_item_code_type(raw: object) -> str:
    """The authority's two item-code kinds, read in any case. Nothing else is a tax item code."""
    text = clean_text(raw).upper()
    if not text:
        raise CellError("required", "code type is required (EGS or GS1)")
    kind = _CODE_TYPE_ALIASES.get(text)
    if kind is None:
        raise CellError("bad_code_type", "code type must be EGS or GS1")
    return kind


def gtin_check_digit(body: str) -> str:
    """The GS1 check digit for the digits before it (weights 3,1,3,1... from the right)."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str((10 - total % 10) % 10)


def parse_item_code(kind: str, raw: object) -> str:
    """One tax item code, judged by what can be known without the authority.

    Every code: trimmed, no spaces, not Excel's scientific notation (which silently destroys the
    trailing digits), and bounded. A GS1 code must also be a real GTIN: 8, 12, 13 or 14 digits
    whose last digit is the published check digit, so a mistyped digit is caught here instead of
    being rejected by the authority a week later. An EGS code has a format the authority owns and
    this code does not know, so it is kept exactly as written and never guessed at.
    """
    text = parse_code(raw, field="code", max_len=ITEM_CODE_MAX)
    if text is None:
        raise CellError("required", "code is required")
    if kind == "GS1":
        if not text.isascii() or not text.isdigit():
            raise CellError("not_a_gtin", "a GS1 code is digits only")
        if len(text) not in _GTIN_LENGTHS:
            raise CellError("bad_length", "a GS1 code (GTIN) has 8, 12, 13 or 14 digits")
        if gtin_check_digit(text[:-1]) != text[-1]:
            raise CellError("bad_check_digit", "the last digit of this GTIN does not match")
    return text
