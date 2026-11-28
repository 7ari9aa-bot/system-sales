"""Cell parsing and row validation for the import center (pure, no database)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.platform.imports.fields import SHEET_PRODUCTS, SHEET_STOCK, SHEET_VARIANTS
from app.platform.imports.normalize import (
    CellError,
    parse_code,
    parse_cost,
    parse_price,
    parse_quantity,
    parse_status,
    slugify,
)
from app.platform.imports.validation import (
    Existing,
    summarize,
    validate_products,
    validate_stock,
    validate_variants,
)

# ------------------------------------------------------------------ prices ------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("125", "125.00"),
        ("125.5", "125.50"),
        ("1,250.50", "1250.50"),
        ("1.250,50", "1250.50"),
        ("1,250", "1250.00"),  # a lone comma before 3 digits groups thousands
        ("12,5", "12.50"),  # a lone comma before 1-2 digits is a decimal mark
        ("١٢٥٫٥٠", "125.50"),  # Arabic-Indic digits and decimal separator
        ("1.250.000", "1250000.00"),
        ("125 ج.م", "125.00"),
        ("EGP 99", "99.00"),
        ("  75  ", "75.00"),
    ],
)
def test_price_formats_a_merchant_actually_types(raw, expected):
    assert parse_price(raw) == Decimal(expected)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", "required"),
        ("0", "not_positive"),
        ("-5", "not_positive"),
        ("abc", "not_a_number"),
        ("12abc", "not_a_number"),
        ("1" * 15, "too_large"),
    ],
)
def test_bad_prices_are_refused_with_a_stable_code(raw, code):
    with pytest.raises(CellError) as exc:
        parse_price(raw)
    assert exc.value.code == code


def test_cost_may_be_blank_or_zero_but_never_negative():
    assert parse_cost("") is None
    assert parse_cost("0") == Decimal("0.00")
    with pytest.raises(CellError) as exc:
        parse_cost("-1")
    assert exc.value.code == "negative"


# ---------------------------------------------------------------- quantity ------------------


def test_quantity_is_a_whole_non_negative_number():
    assert parse_quantity("12") == 12
    assert parse_quantity("٠") == 0
    assert parse_quantity("12.0") == 12
    for raw, code in [
        ("", "required"),
        ("-1", "negative"),
        ("2.5", "not_whole"),
        ("9" * 9, "too_large"),
    ]:
        with pytest.raises(CellError) as exc:
            parse_quantity(raw)
        assert exc.value.code == code


# ------------------------------------------------------------------- codes ------------------


def test_code_is_trimmed_and_invisible_characters_removed():
    assert parse_code("  AB-1\u200b ", field="sku", max_len=63) == "AB-1"
    assert parse_code("", field="sku", max_len=63) is None


def test_excel_scientific_notation_barcode_is_refused_not_repaired():
    with pytest.raises(CellError) as exc:
        parse_code("6.22E+12", field="barcode", max_len=127)
    assert exc.value.code == "scientific_notation"


def test_code_with_inner_space_or_too_long_is_refused():
    with pytest.raises(CellError) as exc:
        parse_code("AB 1", field="sku", max_len=63)
    assert exc.value.code == "has_spaces"
    with pytest.raises(CellError) as exc:
        parse_code("x" * 64, field="sku", max_len=63)
    assert exc.value.code == "too_long"


def test_status_accepts_arabic_words_and_rejects_unknown():
    assert parse_status("نشط") == "active"
    assert parse_status("Draft") == "draft"
    assert parse_status("") is None
    with pytest.raises(CellError):
        parse_status("maybe")


def test_slug_keeps_arabic_letters():
    assert slugify("تيشيرت Basic  #1") == "تيشيرت-basic-1"


# --------------------------------------------------------------- variants -------------------

VMAP = {
    "Ref": "product_ref",
    "SKU": "sku",
    "Barcode": "barcode",
    "Price": "price",
    "Color": "color",
    "Size": "size",
}


def _v(*rows: dict[str, str]):
    return [(i + 2, r) for i, r in enumerate(rows)]


def _variant(**kw) -> dict[str, str]:
    base = {"Ref": "tee", "SKU": "TEE-1", "Barcode": "", "Price": "100", "Color": "", "Size": ""}
    base.update(kw)
    return base


def _run_variants(rows, existing=None, refs=("tee",), policy="update"):
    return validate_variants(
        _v(*rows),
        VMAP,
        existing or Existing(),
        product_refs_in_file=set(refs),
        duplicate_policy=policy,
    )


def test_a_clean_variant_is_valid_and_would_be_created():
    (v,) = _run_variants([_variant()])
    assert v.ok and v.action == "create"
    assert v.values["price"] == Decimal("100.00") and v.values["sku"] == "TEE-1"


def test_variant_without_price_is_an_error_not_a_zero_price():
    (v,) = _run_variants([_variant(Price="")])
    assert [e.code for e in v.errors] == ["required"] and v.errors[0].field == "price"


def test_variant_pointing_at_a_missing_product_is_refused():
    (v,) = _run_variants([_variant(Ref="ghost")])
    assert [e.code for e in v.errors] == ["unknown_product"]


def test_variant_may_point_at_a_product_already_in_the_shop():
    (v,) = _run_variants([_variant(Ref="old")], Existing(product_slugs={"old"}), refs=())
    assert v.ok


def test_duplicate_sku_inside_the_file_flags_the_second_row_only():
    a, b = _run_variants([_variant(), _variant(Barcode="1")])
    assert a.ok
    assert [e.code for e in b.errors] == ["duplicate_in_file"] and "row 2" in b.errors[0].message


def test_sku_owned_by_another_product_is_refused_but_own_sku_is_an_update():
    ex = Existing(product_slugs={"tee", "hat"}, sku_owner={"TEE-1": "hat"})
    (bad,) = _run_variants([_variant()], ex)
    assert [e.code for e in bad.errors] == ["sku_belongs_to_other_product"]
    ex = Existing(product_slugs={"tee"}, sku_owner={"TEE-1": "tee"})
    (ok,) = _run_variants([_variant()], ex)
    assert ok.ok and ok.action == "update"


def test_duplicate_policy_decides_what_an_existing_sku_does():
    ex = Existing(product_slugs={"tee"}, sku_owner={"TEE-1": "tee"})
    assert _run_variants([_variant()], ex, policy="skip")[0].action == "skip"
    assert _run_variants([_variant()], ex, policy="create_only")[0].action == "skip"


def test_barcode_already_on_another_sku_is_refused():
    ex = Existing(barcode_owner={"6221": "OTHER"})
    (v,) = _run_variants([_variant(Barcode="6221")], ex)
    assert [e.code for e in v.errors] == ["barcode_taken"]


def test_variants_without_sku_are_told_apart_by_colour_and_size():
    rows = [
        _variant(SKU="", Color="Red", Size="M"),
        _variant(SKU="", Color="red", Size="m"),  # same combo, different case
        _variant(SKU="", Color="Red", Size="L"),
    ]
    a, b, c = _run_variants(rows)
    assert a.ok and c.ok
    assert [e.code for e in b.errors] == ["duplicate_in_file"]


def test_variant_with_no_identity_at_all_is_refused():
    (v,) = _run_variants([_variant(SKU="")])
    assert [e.code for e in v.errors] == ["no_identity"]


def test_one_bad_cell_does_not_hide_the_others():
    (v,) = _run_variants([_variant(Price="abc", Barcode="6.2E+12")])
    assert {e.field for e in v.errors} == {"price", "barcode"}


# ---------------------------------------------------------------- products ------------------

PMAP = {"Ref": "product_ref", "Name": "title", "Status": "status"}


def test_products_duplicate_ref_flags_the_second_and_existing_is_an_update():
    rows = [
        (2, {"Ref": "tee", "Name": "Tee", "Status": ""}),
        (3, {"Ref": "TEE", "Name": "Tee 2", "Status": ""}),
    ]
    a, b = validate_products(rows, PMAP, Existing(product_slugs={"tee"}), duplicate_policy="update")
    assert a.ok and a.action == "update"
    assert [e.code for e in b.errors] == ["duplicate_in_file"]


def test_product_without_a_name_or_with_bad_status_reports_each_field():
    (v,) = validate_products(
        [(2, {"Ref": "x", "Name": "", "Status": "maybe"})],
        PMAP,
        Existing(),
        duplicate_policy="update",
    )
    assert {e.field for e in v.errors} == {"title", "status"}


def test_product_ref_falls_back_to_a_slug_of_the_name():
    (v,) = validate_products(
        [(2, {"Ref": "", "Name": "قميص أزرق", "Status": ""})],
        PMAP,
        Existing(),
        duplicate_policy="update",
    )
    assert v.ok and v.values["product_ref"] == "قميص-أزرق"


# ------------------------------------------------------------------- stock ------------------

SMAP = {"SKU": "sku", "Qty": "quantity", "WH": "warehouse"}


def _stock(rows, existing=None, in_file=(), known=("A",), default="MAIN"):
    ex = existing or Existing(warehouse_codes={"MAIN", "B2"})
    return validate_stock(
        _v(*rows),
        SMAP,
        ex,
        skus_in_file=set(in_file),
        known_skus=set(known),
        default_warehouse=default,
    )


def test_stock_row_uses_the_default_warehouse_when_the_cell_is_blank():
    (v,) = _stock([{"SKU": "A", "Qty": "5", "WH": ""}])
    assert v.ok and v.values == {"sku": "A", "warehouse": "MAIN", "quantity": Decimal(5)}


def test_stock_for_an_unknown_sku_or_warehouse_is_refused():
    a, b = _stock([{"SKU": "Z", "Qty": "1", "WH": "MAIN"}, {"SKU": "A", "Qty": "1", "WH": "NOPE"}])
    assert [e.code for e in a.errors] == ["unknown_sku"]
    assert [e.code for e in b.errors] == ["unknown_warehouse"]


def test_stock_may_reference_a_sku_that_is_created_by_the_same_file():
    (v,) = _stock([{"SKU": "NEW", "Qty": "1", "WH": "MAIN"}], in_file={"NEW"}, known=())
    assert v.ok


def test_same_sku_and_warehouse_twice_in_one_file_is_refused():
    a, b = _stock([{"SKU": "A", "Qty": "1", "WH": "MAIN"}, {"SKU": "A", "Qty": "2", "WH": "MAIN"}])
    assert a.ok and [e.code for e in b.errors] == ["duplicate_in_file"]


def test_opening_stock_is_never_applied_twice_for_the_same_sku_and_warehouse():
    ex = Existing(warehouse_codes={"MAIN"}, opening_stock_done={("A", "MAIN")})
    (v,) = _stock([{"SKU": "A", "Qty": "1", "WH": "MAIN"}], ex)
    assert [e.code for e in v.errors] == ["opening_stock_already_set"]


# ----------------------------------------------------------------- summary ------------------


def test_summary_counts_actions_and_ranks_error_codes():
    ex = Existing(product_slugs={"tee"}, sku_owner={"T1": "tee"})
    verdicts = _run_variants(
        [
            _variant(SKU="T1"),
            _variant(SKU="T2"),
            _variant(SKU="T3", Price="x"),
            _variant(SKU="T4", Price=""),
        ],
        ex,
    )
    s = summarize(verdicts)
    assert (s["total"], s["valid"], s["invalid"]) == (4, 2, 2)
    assert (s["create"], s["update"]) == (1, 1)
    assert s["error_codes"] == {"not_a_number": 1, "required": 1}


def test_sheet_names_match_the_template_contract():
    assert (SHEET_PRODUCTS, SHEET_VARIANTS, SHEET_STOCK) == (
        "Products",
        "Variants",
        "Opening Stock",
    )
