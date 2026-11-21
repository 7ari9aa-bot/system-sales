"""Size x colour matrix: which variants a garment needs, their SKUs, and how sizes are ordered.

Pure functions only: no database, no session. A merchant says "this shirt, sizes S to XL, in black
and white" and gets every combination, in the order a shelf is read (S before M before L, never
alphabetical), each with a SKU a person can read off a tag. The service writes the result through
the catalog's existing variant and option services; nothing here knows about tables.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.modules.errors import ValidationError

SIZE_AXIS = "المقاس"
COLOR_AXIS = "اللون"

#: Letter sizes in the order a rack is read. A size is matched case-insensitively.
LETTER_SIZES = ("XXXS", "XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "XXXXL")
#: Common ways a shopkeeper writes the same size. Normalised to the canonical letter form.
_SIZE_ALIASES = {
    "2XL": "XXL",
    "3XL": "XXXL",
    "4XL": "XXXXL",
    "SMALL": "S",
    "MEDIUM": "M",
    "LARGE": "L",
    "صغير": "S",
    "وسط": "M",
    "متوسط": "M",
    "كبير": "L",
}
MAX_COMBINATIONS = 200  # one garment with more than this is a typo, not a range
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _clean(value: object, what: str) -> str:
    text = unicodedata.normalize("NFKC", str(value)).translate(_ARABIC_DIGITS).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        raise ValidationError(f"{what} must not be empty")
    if len(text) > 63:
        raise ValidationError(f"{what} must be at most 63 characters")
    return text


def normalise_size(raw: object) -> str:
    """A size as the shop will store it: letters upper-cased, aliases folded, digits Latin."""
    text = _clean(raw, "size")
    key = text.upper()
    return _SIZE_ALIASES.get(key, _SIZE_ALIASES.get(text, key))


def size_sort_key(size: str) -> tuple[int, float, str]:
    """Order sizes the way a rack is read: letters by their ladder, then numbers by value.

    Letter sizes come first (S < M < L < XL), numeric sizes (38, 40, 42, or 3-4 years) after, by
    their first number, and anything unrecognised last in the order it was typed, never lost.
    """
    if size in LETTER_SIZES:
        return (0, float(LETTER_SIZES.index(size)), size)
    match = re.match(r"^(\d+(?:\.\d+)?)", size)
    if match:
        return (1, float(match.group(1)), size)
    return (2, 0.0, size)


def _unique(values: Iterable[object], clean, what: str) -> list[str]:
    seen: dict[str, None] = {}
    for raw in values:
        value = clean(raw)
        # case-insensitive: "Red" and "red" are one colour, not two variants
        seen.setdefault(value, None)
    out: list[str] = []
    folded: set[str] = set()
    for value in seen:
        key = value.casefold()
        if key not in folded:
            folded.add(key)
            out.append(value)
    if not out:
        raise ValidationError(f"at least one {what} is required")
    return out


def _code(text: str) -> str:
    """A short, tag-friendly fragment of a name: letters and digits only, upper-cased.

    Arabic is kept as is (a shopkeeper reads it), spaces and punctuation become nothing.
    """
    return re.sub(r"[^\w]", "", text, flags=re.UNICODE).upper()


@dataclass(frozen=True, slots=True)
class Cell:
    """One sellable unit of the matrix."""

    size: str
    color: str
    sku: str
    option_values: dict[str, str]


def build_matrix(
    *,
    sizes: Sequence[object],
    colors: Sequence[object],
    sku_prefix: str,
    color_codes: dict[str, str] | None = None,
) -> list[Cell]:
    """Every size x colour of a garment, sizes in rack order, colours as the merchant listed them.

    SKUs read ``PREFIX-COLOR-SIZE`` (``SH24-BLK-M``). ``color_codes`` lets the merchant choose the
    short code for a colour; otherwise it is the first three characters of its name. Two colours
    that would end up with the same code are refused rather than silently sharing a SKU.
    """
    prefix = _code(_clean(sku_prefix, "sku_prefix"))
    if not prefix:
        raise ValidationError("sku_prefix must contain letters or digits")
    size_list = sorted(
        _unique(sizes, normalise_size, "size"),
        key=size_sort_key,
    )
    color_list = _unique(colors, lambda c: _clean(c, "colour"), "colour")
    if len(size_list) * len(color_list) > MAX_COMBINATIONS:
        raise ValidationError(
            f"{len(size_list)} sizes x {len(color_list)} colours is more than "
            f"{MAX_COMBINATIONS} variants for one garment"
        )

    explicit = {
        k.casefold(): _code(_clean(v, "colour code")) for k, v in (color_codes or {}).items()
    }
    codes: dict[str, str] = {}
    for color in color_list:
        code = explicit.get(color.casefold()) or _code(color)[:3]
        if not code:
            raise ValidationError(
                f"colour {color!r} has no usable code: give it one in color_codes"
            )
        codes[color] = code
    clash: dict[str, str] = {}
    for color, code in codes.items():
        if code in clash:
            raise ValidationError(
                f"colours {clash[code]!r} and {color!r} would share the code {code!r}: "
                "give one of them its own in color_codes"
            )
        clash[code] = color

    cells: list[Cell] = []
    for color in color_list:
        for size in size_list:
            cells.append(
                Cell(
                    size=size,
                    color=color,
                    sku=f"{prefix}-{codes[color]}-{_code(size)}",
                    option_values={SIZE_AXIS: size, COLOR_AXIS: color},
                )
            )
    # the code of a size could in theory collide too ("1/2" and "12" both become "12")
    skus = [c.sku for c in cells]
    if len(set(skus)) != len(skus):
        raise ValidationError("two sizes would produce the same SKU: rename one of them")
    return cells
