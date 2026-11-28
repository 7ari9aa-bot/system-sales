"""Suggest which of the merchant's columns is which Fihrist field.

Pure functions, no database. The merchant's file may use any header ("اسم الصنف", "Item Name",
"QTY "), so we normalize both sides and match, then let the merchant correct the result. A
suggestion is never applied silently: the mapping step shows it and the merchant confirms.
"""

from __future__ import annotations

import re
import unicodedata

from app.platform.imports.fields import SHEET_FIELDS, SHEET_STOCK, FieldSpec

_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_NON_WORD = re.compile(r"[^0-9a-z\u0600-\u06FF]+")
_ARABIC_LETTER_FOLD = str.maketrans(
    {"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"}
)
# Arabic-Indic and Persian digits fold to ASCII so "سعر 1" and "سعر ١" match the same header.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_header(raw: object) -> str:
    """Lower-case, strip diacritics/tatweel/punctuation/spaces and fold Arabic letter variants."""
    text = unicodedata.normalize("NFKC", str(raw if raw is not None else ""))
    text = _ARABIC_DIACRITICS.sub("", text).lower().translate(_ARABIC_LETTER_FOLD)
    text = text.translate(_DIGITS)
    return _NON_WORD.sub("", text)


def _index(fields: tuple[FieldSpec, ...]) -> dict[str, str]:
    """normalized spelling -> field key. The first field to claim a spelling keeps it."""
    out: dict[str, str] = {}
    for spec in fields:
        spellings = {
            normalize_header(spec.key),
            normalize_header(spec.label_ar),
            normalize_header(spec.label_en),
            *(normalize_header(s) for s in spec.synonyms),
        }
        for spelling in spellings:
            if spelling:
                out.setdefault(spelling, spec.key)
    return out


def suggest_mapping(sheet: str, headers: list[str]) -> dict[str, str | None]:
    """source header -> field key, or None when nothing matched.

    Each field is claimed by at most one column (the leftmost), so two columns that both look
    like "price" cannot both write it; the second is left unmapped for the merchant to decide.
    """
    fields = SHEET_FIELDS.get(sheet, ())
    index = _index(fields)
    taken: set[str] = set()
    result: dict[str, str | None] = {}
    for header in headers:
        key = index.get(normalize_header(header))
        if key is not None and key not in taken:
            taken.add(key)
            result[header] = key
        else:
            result[header] = None
    return result


def missing_required(sheet: str, mapping: dict[str, str | None]) -> list[str]:
    """Required field keys no column is mapped to."""
    chosen = {v for v in mapping.values() if v}
    return [f.key for f in SHEET_FIELDS.get(sheet, ()) if f.required and f.key not in chosen]


# Fields that belong to the Opening Stock sheet. A merchant who puts "الكمية" on the Variants
# sheet expects stock to be loaded; the column is unmapped there, so it would be dropped
# without a word. Saying so is the whole point.
_STOCK_ONLY = {"quantity", "warehouse"}


def ignored_columns(sheet: str, mapping: dict[str, str | None]) -> list[dict[str, str]]:
    """Columns the import will not read, each with a reason the merchant can act on.

    ``stock_on_wrong_sheet`` is the one that costs money: the quantity is silently not loaded.
    """
    stock_index = _index(SHEET_FIELDS.get(SHEET_STOCK, ()))
    out: list[dict[str, str]] = []
    for header, key in mapping.items():
        if key is not None:
            continue
        reason = "unmatched"
        if sheet != SHEET_STOCK and stock_index.get(normalize_header(header)) in _STOCK_ONLY:
            reason = "stock_on_wrong_sheet"
        out.append({"column": header, "reason": reason})
    return out
