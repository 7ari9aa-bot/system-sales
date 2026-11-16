"""The downloadable starter workbook: one sheet per importable kind, headed in Arabic.

Built from ``fields.py``, the same table the column matcher reads, so a merchant who fills the
template in gets every column matched automatically and the two can never drift apart.

The Images sheet is left out on purpose: nothing validates or applies it yet, and a template
must not promise a sheet the import would then silently ignore.
"""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.modules.imports.fields import (
    SHEET_FIELDS,
    SHEET_PRODUCTS,
    SHEET_STOCK,
    SHEET_VARIANTS,
    FieldSpec,
)

TEMPLATE_SHEETS = (SHEET_PRODUCTS, SHEET_VARIANTS, SHEET_STOCK)

# One believable value per column, shown as a comment on the header and NEVER as a data row: a
# sample row would be imported as a real product the moment a merchant uploads the file as is.
# The example ties the three sheets together (same ref and SKU), which is the one thing a
# first-time merchant gets wrong.
_EXAMPLES: dict[str, dict[str, str]] = {
    SHEET_PRODUCTS: {
        "product_ref": "tee-cotton",
        "title": "تيشيرت قطن",
        "category": "ملابس رجالي",
        "brand": "",
        "description": "تيشيرت قطن مصري ١٠٠٪",
        "status": "active",
    },
    SHEET_VARIANTS: {
        "product_ref": "tee-cotton",
        "sku": "TEE-RED-M",
        "barcode": "",
        "color": "أحمر",
        "size": "M",
        "price": "149.50",
        "cost": "90",
    },
    SHEET_STOCK: {"sku": "TEE-RED-M", "barcode": "", "warehouse": "", "quantity": "25"},
}

_HEADER_FILL = PatternFill("solid", start_color="1F2937")
_REQUIRED_FILL = PatternFill("solid", start_color="B45309")
_HEADER_FONT = Font(bold=True, color="FFFFFF")


def _header(spec: FieldSpec) -> str:
    return spec.label_ar


def build_template() -> bytes:
    """The workbook as bytes. Required columns are marked in a different colour."""
    wb = Workbook()
    wb.remove(wb.active)
    for sheet in TEMPLATE_SHEETS:
        specs: tuple[FieldSpec, ...] = SHEET_FIELDS[sheet]
        ws = wb.create_sheet(sheet)
        ws.sheet_view.rightToLeft = True
        ws.append([_header(s) for s in specs])
        for col, spec in enumerate(specs, start=1):
            cell = ws.cell(row=1, column=col)
            cell.font = _HEADER_FONT
            cell.fill = _REQUIRED_FILL if spec.required else _HEADER_FILL
            cell.alignment = Alignment(horizontal="center")
            example = _EXAMPLES[sheet].get(spec.key)
            if example:
                note = ("مطلوب. " if spec.required else "") + f"مثال: {example}"
                cell.comment = Comment(note, "Fihrist")
            ws.column_dimensions[get_column_letter(col)].width = max(16, len(_header(spec)) + 6)
        ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
