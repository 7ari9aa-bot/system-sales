"""Spreadsheet reading and column matching for the import center (no database needed)."""

from __future__ import annotations

import io
import zipfile

import pytest
from openpyxl import Workbook

from app.core.errors import ValidationError
from app.modules.imports import reader
from app.modules.imports.fields import SHEET_PRODUCTS, SHEET_STOCK, SHEET_VARIANTS
from app.modules.imports.mapping import missing_required, normalize_header, suggest_mapping


def _xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- reader --------------------


def test_reads_every_sheet_of_a_workbook_with_arabic_text():
    data = _xlsx(
        {
            "Products": [["اسم المنتج", "التصنيف"], ["تيشيرت Basic", "ملابس"]],
            "Variants": [["SKU", "السعر"], ["TS-R-M", 150], ["TS-R-L", 150.5]],
        }
    )
    sheets = {s.name: s for s in reader.read_workbook("t.xlsx", data)}
    assert sheets["Products"].rows == [{"اسم المنتج": "تيشيرت Basic", "التصنيف": "ملابس"}]
    # 150 prints as "150", not "150.0"; 150.5 keeps its fraction
    assert [r["السعر"] for r in sheets["Variants"].rows] == ["150", "150.5"]


def test_blank_rows_and_trailing_empty_columns_are_dropped():
    data = _xlsx({"S": [[], ["a", "b", None], [], ["1", "2", None], [None, None, None]]})
    (sheet,) = reader.read_workbook("t.xlsx", data)
    assert sheet.headers == ["a", "b"]
    assert sheet.rows == [{"a": "1", "b": "2"}]


def test_duplicate_and_blank_headers_get_unique_names():
    data = _xlsx({"S": [["Size", "Size", None, "Price"], ["M", "L", "x", "5"]]})
    (sheet,) = reader.read_workbook("t.xlsx", data)
    assert sheet.headers == ["Size", "Size_2", "column_3", "Price"]


def test_a_formula_cell_is_never_evaluated_and_never_returned_as_a_formula():
    # openpyxl writes the formula with no cached value; reading with data_only=True must give
    # blank, not the formula text (which a spreadsheet app would later execute on re-export).
    wb = Workbook()
    ws = wb.active
    ws.append(["a", "b"])
    ws.append(["=1+1", "ok"])
    buf = io.BytesIO()
    wb.save(buf)
    (sheet,) = reader.read_workbook("t.xlsx", buf.getvalue())
    assert sheet.rows == [{"a": "", "b": "ok"}]


def test_csv_utf8_bom_semicolon_delimiter():
    raw = "﻿اسم المنتج;السعر\nقميص;99\n".encode()
    (sheet,) = reader.read_workbook("t.csv", raw)
    assert sheet.headers == ["اسم المنتج", "السعر"]
    assert sheet.rows == [{"اسم المنتج": "قميص", "السعر": "99"}]


def test_csv_windows_arabic_cp1256_is_decoded():
    raw = "الاسم,السعر\nقميص,99\n".encode("cp1256")
    (sheet,) = reader.read_workbook("t.csv", raw)
    assert sheet.rows == [{"الاسم": "قميص", "السعر": "99"}]


def test_macro_workbook_is_refused_by_name_and_by_content():
    with pytest.raises(ValidationError):
        reader.read_workbook("a.xlsm", b"PK\x03\x04")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<x/>")
        zf.writestr("xl/vbaProject.bin", b"evil")
    with pytest.raises(ValidationError, match="macros"):
        reader.read_workbook("a.xlsx", buf.getvalue())


def test_zip_bomb_is_refused_before_openpyxl_opens_it(monkeypatch):
    monkeypatch.setattr(reader, "MAX_UNCOMPRESSED_BYTES", 1000)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", "0" * 50_000)
    with pytest.raises(ValidationError, match="too large once unpacked"):
        reader.read_workbook("a.xlsx", buf.getvalue())


def test_garbage_named_xlsx_is_a_validation_error_not_a_crash():
    with pytest.raises(ValidationError):
        reader.read_workbook("a.xlsx", b"this is not a zip")


def test_empty_and_oversize_files_are_refused(monkeypatch):
    with pytest.raises(ValidationError, match="empty"):
        reader.read_workbook("a.csv", b"")
    monkeypatch.setattr(reader, "MAX_FILE_BYTES", 10)
    with pytest.raises(ValidationError, match="larger"):
        reader.read_workbook("a.csv", b"x" * 11)


def test_row_limit_is_enforced_while_reading(monkeypatch):
    monkeypatch.setattr(reader, "MAX_ROWS", 3)
    raw = ("a\n" + "\n".join(str(i) for i in range(1, 6))).encode()
    with pytest.raises(ValidationError, match="more than 3 rows"):
        reader.read_workbook("a.csv", raw)


def test_too_many_columns_is_refused(monkeypatch):
    monkeypatch.setattr(reader, "MAX_COLUMNS", 2)
    with pytest.raises(ValidationError, match="columns"):
        reader.read_workbook("a.csv", b"a,b,c\n1,2,3\n")


# --------------------------------------------------------------- mapping --------------------


def test_normalize_header_folds_case_spaces_diacritics_and_arabic_variants():
    assert normalize_header("  Product Name ") == normalize_header("product_name")
    assert normalize_header("أسم") == normalize_header("اسم")
    assert normalize_header("السِّعر") == normalize_header("السعر")
    assert normalize_header("سعر ١") == normalize_header("سعر 1")


def test_arabic_and_english_headers_map_to_the_same_fields():
    headers = ["اسم المنتج", "Item Code", "اللون", "المقاس", "سعر البيع", "Barcode", "Notes"]
    got = suggest_mapping(SHEET_VARIANTS, ["Item Code", "اللون", "المقاس", "سعر البيع", "Barcode"])
    assert got == {
        "Item Code": "sku",
        "اللون": "color",
        "المقاس": "size",
        "سعر البيع": "price",
        "Barcode": "barcode",
    }
    products = suggest_mapping(SHEET_PRODUCTS, headers)
    assert products["اسم المنتج"] == "title"
    assert products["Notes"] is None


def test_a_field_is_claimed_by_one_column_only():
    got = suggest_mapping(SHEET_VARIANTS, ["Price", "Sale Price", "Retail Price"])
    assert list(got.values()).count("price") == 1
    assert got["Price"] == "price"  # the leftmost wins
    assert got["Sale Price"] is None


def test_missing_required_lists_what_the_merchant_still_has_to_map():
    mapping = suggest_mapping(SHEET_STOCK, ["SKU", "Notes"])
    assert missing_required(SHEET_STOCK, mapping) == ["quantity"]
    full = suggest_mapping(SHEET_STOCK, ["SKU", "الكمية", "المخزن"])
    assert missing_required(SHEET_STOCK, full) == []


def test_unknown_sheet_maps_nothing():
    assert suggest_mapping("Nope", ["a"]) == {"a": None}
