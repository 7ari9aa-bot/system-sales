"""Pasting rows straight from Excel: the same import, without saving a file first.

A merchant's price list is usually already open in a spreadsheet. Making them "save as .csv, find
the file, upload it" is a step that loses people. The text they copy is tab-separated, one row per
line, and it carries what a variant line carries in the shop: the product name repeated on each
line, plus colour, size, price, SKU and maybe an opening quantity.

This module only turns that text into the sheets the Import Center already understands — it does
not validate anything and it does not touch the catalog. The rows go through exactly the same
mapping, validation and apply as an uploaded workbook.
"""

from __future__ import annotations

import csv
import io

from app.core.errors import ValidationError
from app.modules.imports.fields import SHEET_PRODUCTS, SHEET_STOCK, SHEET_VARIANTS
from app.modules.imports.mapping import suggest_mapping
from app.modules.imports.normalize import slugify

MAX_PASTED_ROWS = 10_000

# Columns that only make sense on a variant line. If any of them is present, the paste describes
# variants (one line each) and the product columns are folded into one Products row per name.
_VARIANT_ONLY = {"sku", "price", "color", "size", "barcode", "option", "stock_qty"}


def _delimiter(text: str) -> str:
    first = text.splitlines()[0] if text.strip() else ""
    if "\t" in first:
        return "\t"
    if ";" in first and first.count(";") > first.count(","):
        return ";"
    return ","


def _table(text: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text), delimiter=_delimiter(text))
    return [[cell.strip() for cell in row] for row in reader]


def _drop_empty(rows: list[list[str]]) -> list[list[str]]:
    return [row for row in rows if any(cell for cell in row)]


def parse_pasted(text: str) -> dict[str, list[dict[str, str]]]:
    """The pasted text as sheets of header-keyed rows, exactly like a read workbook.

    Raises ``ValidationError`` when there is nothing usable: no header, no rows, or no column the
    import understands at all — a paste that maps to nothing would create an empty session the
    merchant cannot finish.
    """
    table = _drop_empty(_table(text or ""))
    if len(table) < 2:
        raise ValidationError(
            "الصق الصفوف مع سطر العناوين فوقها: اسم المنتج، السعر، المقاس، اللون…"
        )
    headers = table[0]
    if not any(headers):
        raise ValidationError("سطر العناوين فاضي: اكتب أسماء الأعمدة في أول سطر")
    rows = table[1:]
    if len(rows) > MAX_PASTED_ROWS:
        raise ValidationError(f"عدد الصفوف الملصوقة أكبر من الحد ({MAX_PASTED_ROWS})")

    product_map = suggest_mapping(SHEET_PRODUCTS, headers)
    variant_map = suggest_mapping(SHEET_VARIANTS, headers)
    stock_map = suggest_mapping(SHEET_STOCK, headers)

    product_keys = {k for k in product_map.values() if k}
    variant_keys = {k for k in variant_map.values() if k}
    if not product_keys and not variant_keys:
        raise ValidationError(
            "مفيش عمود مفهوم في اللصق. لازم يكون فيه على الأقل «اسم المنتج» أو «SKU»."
        )

    as_dicts = [dict(zip(headers, row, strict=False)) for row in rows]
    is_variant_paste = bool(variant_keys & _VARIANT_ONLY)

    if not is_variant_paste:
        return {SHEET_PRODUCTS: as_dicts}

    # A variant line: one Products row per distinct product name, and one Variants row per line.
    # A variant row must say which product it belongs to, and the paste only carries the name, so
    # the handle is derived here exactly as the validator derives it for a product row — otherwise
    # the sheet would stop at "map the required columns first" for a column the merchant never had.
    has_ref = _header_for(product_map, "product_ref") is not None
    products: list[dict[str, str]] = []
    seen: dict[str, str] = {}
    for row in as_dicts:
        name = _first_mapped(row, product_map, "title")
        if not name:
            continue
        if name not in seen:
            seen[name] = name
            line = {header: row.get(header, "") for header in headers}
            if not has_ref:
                line[REF_HEADER] = slugify(name)
            products.append(line)
    for row in as_dicts:
        name = _first_mapped(row, product_map, "title")
        if name and not has_ref:
            row[REF_HEADER] = slugify(name)

    sheets: dict[str, list[dict[str, str]]] = {SHEET_PRODUCTS: products, SHEET_VARIANTS: as_dicts}
    if any(k for k in stock_map.values() if k) and variant_keys:
        sheets[SHEET_STOCK] = as_dicts
    return sheets


REF_HEADER = "معرّف المنتج"


def _header_for(mapping: dict[str, str | None], key: str) -> str | None:
    for header, field in mapping.items():
        if field == key:
            return header
    return None


def _first_mapped(row: dict[str, str], mapping: dict[str, str | None], key: str) -> str:
    for header, field in mapping.items():
        if field == key:
            return (row.get(header) or "").strip()
    return ""
