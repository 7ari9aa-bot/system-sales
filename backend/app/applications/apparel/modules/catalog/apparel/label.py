"""A printable shelf/garment label as SVG: name, size and colour, price, barcode, its digits.

SVG because it is vector (sharp on a 203 dpi thermal printer and on a laser sheet alike), needs no
library, and the browser prints it at an exact physical size in millimetres. Pure functions: the
text is escaped here, since a product name is typed by a user and ends up inside markup.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from xml.sax.saxutils import escape

from app.applications.apparel.modules.catalog.apparel.barcode import bars
from app.modules.errors import ValidationError

MODULE_MM = 0.33  # one EAN-13 module; the standard 100% size is 0.33 mm
QUIET_MODULES = 11  # the blank margin an EAN-13 needs on each side to scan
FONT = "Tahoma, Arial, 'Noto Sans Arabic', sans-serif"
MAX_TEXT = 40

# (width_mm, height_mm): the label stocks a Egyptian shop actually buys
SIZES = {"small": (40.0, 25.0), "medium": (50.0, 30.0), "large": (60.0, 40.0)}


def _fit(text: object, limit: int = MAX_TEXT) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def _price(value: object) -> str:
    try:
        amount = Decimal(str(value))
    except Exception:  # noqa: BLE001 - any unreadable figure is the caller's 422, never a crash
        raise ValidationError("price must be a number") from None
    if not amount.is_finite() or amount < 0:
        raise ValidationError("price must be zero or more")
    rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = f"{rounded:.2f}"
    return text[:-3] if text.endswith(".00") else text  # 250 not 250.00, but 249.50 stays


def label_svg(
    *,
    code: str,
    title: object,
    variant_text: object = "",
    price: object = None,
    currency: str = "ج.م",
    size: str = "medium",
) -> str:
    """One label as a standalone SVG whose width and height are real millimetres."""
    if size not in SIZES:
        raise ValidationError(f"label size must be one of {sorted(SIZES)}")
    width, height = SIZES[size]
    pattern = bars(code)  # refuses a number that is not a valid EAN-13, never draws a dud
    bar_width = MODULE_MM
    barcode_width = len(pattern) * bar_width
    if barcode_width + 2 * QUIET_MODULES * bar_width > width:
        raise ValidationError("this label size is too narrow for a scannable barcode")
    left = (width - barcode_width) / 2

    # geometry (millimetres)
    pad = 1.2
    title_y = pad + 3.2
    variant_y = title_y + 3.4
    bar_top = variant_y + 1.6
    digits_h = 2.8
    price_h = 4.2 if price is not None else 0.0
    bar_height = max(height - bar_top - digits_h - price_h - pad, 6.0)
    rects = []
    start = None
    for index, bit in enumerate([*pattern, "0"]):
        if bit == "1" and start is None:
            start = index
        elif bit != "1" and start is not None:
            rects.append(
                f'<rect x="{left + start * bar_width:.3f}" y="{bar_top:.2f}" '
                f'width="{(index - start) * bar_width:.3f}" height="{bar_height:.2f}"/>'
            )
            start = None
    digits_y = bar_top + bar_height + 2.4
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" '
        f'viewBox="0 0 {width} {height}" direction="rtl" font-family="{FONT}">',
        f'<rect width="{width}" height="{height}" fill="#fff"/>',
        f'<text x="{width / 2}" y="{title_y}" font-size="3" font-weight="bold" '
        f'text-anchor="middle">{escape(_fit(title))}</text>',
    ]
    if str(variant_text or "").strip():
        parts.append(
            f'<text x="{width / 2}" y="{variant_y}" font-size="2.6" text-anchor="middle">'
            f"{escape(_fit(variant_text))}</text>"
        )
    parts.append(f'<g fill="#000">{"".join(rects)}</g>')
    parts.append(
        f'<text x="{width / 2}" y="{digits_y:.2f}" font-size="2.2" text-anchor="middle" '
        f'font-family="monospace" direction="ltr">{escape(code)}</text>'
    )
    if price is not None:
        parts.append(
            f'<text x="{width / 2}" y="{height - pad:.2f}" font-size="4" font-weight="bold" '
            f'text-anchor="middle">{escape(_price(price))} {escape(currency)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)
