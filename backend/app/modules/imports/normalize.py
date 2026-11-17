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

from app.core.contact_norm import ContactNormalizationError, normalize_email, normalize_phone

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


# Arabic-Indic and Persian digits, so a phone typed in an Arabic keyboard reads as a phone.
_PHONE_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
EMAIL_MAX = 254
TAGS_MAX = 20
TAG_MAX = 60


def parse_phone(raw: object) -> str | None:
    """A canonical E.164 phone, or None when the cell is blank.

    The shop's own rule decides what a valid number is (``normalize_phone``), so a row cannot
    pass here and then be refused by the customers service. The one thing it does not know is
    that a merchant types ``٠١٠١٢٣٤٥٦٧٨`` on an Arabic keyboard, so those digits are folded first.
    Excel also drops the leading zero of a number typed into a General cell (``1012345678``); the
    same rule reads that as the Egyptian number it is, so it is accepted, not guessed at.
    """
    text = clean_text(raw).translate(_PHONE_DIGITS)
    if not text:
        return None
    if re.fullmatch(r"[0-9]+(\.[0-9]+)?[eE][+-]?[0-9]+", text):
        raise CellError(
            "scientific_notation",
            f"phone looks like scientific notation ({text}); format the column as Text",
        )
    if re.fullmatch(r"[0-9]+\.0+", text):  # a number cell read back as 1012345678.0
        text = text.split(".", 1)[0]
    try:
        return normalize_phone(text)
    except ContactNormalizationError as exc:
        raise CellError("bad_phone", f"phone '{text}' is not a dialable number") from exc


def parse_email(raw: object) -> str | None:
    text = clean_text(raw)
    if not text:
        return None
    if len(text) > EMAIL_MAX:
        raise CellError("too_long", f"email is longer than {EMAIL_MAX} characters")
    try:
        return normalize_email(text)
    except ContactNormalizationError as exc:
        raise CellError("bad_email", f"email '{text}' is not a valid address") from exc


def parse_tags(raw: object) -> list[str]:
    """``vip, جملة ; wholesale`` -> ['vip', 'جملة', 'wholesale'], once each, in order."""
    out: list[str] = []
    for part in re.split(r"[,،;؛\n]", clean_text(raw).replace("\u200f", "")):
        tag = clean_text(part)
        if not tag:
            continue
        if len(tag) > TAG_MAX:
            raise CellError("too_long", f"a tag is longer than {TAG_MAX} characters")
        if tag.casefold() not in {t.casefold() for t in out}:
            out.append(tag)
    if len(out) > TAGS_MAX:
        raise CellError("too_many_tags", f"more than {TAGS_MAX} tags on one customer")
    return out


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


def is_link(text: str) -> bool:
    """True when the cell is meant as a link (so it is judged as one), not as a file name."""
    return text.strip().lower().startswith(("http://", "https://"))


def parse_image_file_name(raw: object) -> str:
    """A picture's file name as the merchant typed it: no folders, a picture extension.

    A path is refused rather than trimmed: ``photos/a.jpg`` and ``a.jpg`` are the same picture to
    a person, but a cell that carries ``../`` is never something to quietly repair.
    """
    text = clean_text(raw)
    if not text:
        raise CellError("required", "image is required")
    if len(text) > 255:
        raise CellError("too_long", "image file name is longer than 255 characters")
    if "/" in text or "\\" in text or ".." in text.split("."):
        raise CellError("bad_file_name", "write the file name only, without a folder")
    if not text.lower().endswith(_IMAGE_EXTENSIONS):
        raise CellError(
            "bad_file_name", "image file name must end in .jpg, .png, .gif, .webp or .bmp"
        )
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
