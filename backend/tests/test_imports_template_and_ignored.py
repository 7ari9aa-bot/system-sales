"""The starter workbook and the warning about columns the import will not read."""

from __future__ import annotations

import io

from openpyxl import load_workbook

from app.platform.imports.fields import (
    SHEET_CUSTOMERS,
    SHEET_FIELDS,
    SHEET_IMAGES,
    SHEET_ITEM_CODES,
    SHEET_PRODUCTS,
    SHEET_STOCK,
    SHEET_VARIANTS,
)
from app.platform.imports.mapping import ignored_columns, suggest_mapping
from app.platform.imports.reader import read_workbook
from app.platform.imports.template import TEMPLATE_SHEETS, build_template
from tests.test_imports_http import BOTH, _upload, _xlsx, api  # noqa: F401, F811  (api: fixture)


def test_the_template_has_one_sheet_per_importable_kind():
    wb = load_workbook(io.BytesIO(build_template()))
    assert wb.sheetnames == [
        SHEET_PRODUCTS,
        SHEET_VARIANTS,
        SHEET_STOCK,
        SHEET_IMAGES,
        SHEET_ITEM_CODES,
        SHEET_CUSTOMERS,
    ]
    assert set(TEMPLATE_SHEETS) == set(wb.sheetnames)


def test_every_template_column_matches_a_field_on_its_own_sheet():
    """A merchant who fills the template in must never see a column left unmapped."""
    for sheet in read_workbook("t.xlsx", build_template()):
        mapping = suggest_mapping(sheet.name, sheet.headers)
        assert all(mapping.values()), (sheet.name, mapping)
        assert set(mapping.values()) == {f.key for f in SHEET_FIELDS[sheet.name]}


def test_the_template_carries_no_data_row_so_uploading_it_blank_creates_nothing():
    for sheet in read_workbook("t.xlsx", build_template()):
        assert sheet.rows == []


def test_required_columns_are_marked_and_examples_live_in_comments():
    wb = load_workbook(io.BytesIO(build_template()))
    ws = wb[SHEET_VARIANTS]
    by_header = {c.value: c for c in ws[1]}
    price = by_header["سعر البيع"]
    assert price.comment is not None and price.comment.text.startswith("مطلوب")
    assert by_header["اللون"].comment is not None
    assert not by_header["اللون"].comment.text.startswith("مطلوب")
    assert ws.max_row == 1


def test_a_quantity_column_on_the_variants_sheet_is_called_out_as_stock_on_the_wrong_sheet():
    headers = ["معرّف المنتج", "SKU", "السعر", "الكمية", "المخزن", "ملاحظات"]
    got = ignored_columns(SHEET_VARIANTS, suggest_mapping(SHEET_VARIANTS, headers))
    assert got == [
        {"column": "الكمية", "reason": "stock_on_wrong_sheet"},
        {"column": "المخزن", "reason": "stock_on_wrong_sheet"},
        {"column": "ملاحظات", "reason": "unmatched"},
    ]


def test_the_same_columns_on_the_stock_sheet_are_not_flagged():
    headers = ["SKU", "الكمية", "المخزن"]
    assert ignored_columns(SHEET_STOCK, suggest_mapping(SHEET_STOCK, headers)) == []


async def test_the_template_downloads_and_the_upload_response_lists_ignored_columns(api):  # noqa: F811
    async with api(BOTH) as client:
        got = await client.get("/api/v1/imports/template.xlsx")
        assert got.status_code == 200
        assert got.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert "fihrist-import-template.xlsx" in got.headers["content-disposition"]

        sheet = [["معرّف المنتج", "SKU", "السعر", "الكمية"], ["tee", "TEE-1", "99.5", "10"]]
        upload = await _upload(client, _xlsx({"Variants": sheet}))
        assert upload.status_code == 201
        variants = upload.json()["sheets"]["Variants"]
        assert variants["ignored_columns"] == [
            {"column": "الكمية", "reason": "stock_on_wrong_sheet"}
        ]
