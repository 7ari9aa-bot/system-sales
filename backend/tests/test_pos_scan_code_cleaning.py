"""A scanned code is cleaned before it is looked up, and a code that is fine must not be lost.

Found by attacking the generic scan: the same valid barcode was "not found" when it arrived with
Arabic-Indic or full-width digits (an Arabic keyboard), behind an AIM prefix such as ``]E0`` (some
scanners add it), with a zero-width character, or as the other leading-zero spelling of the same
product (UPC-A 12 digits vs EAN-13 vs GTIN-14). A named type stays exact, and a code that is not a
plain barcode (a SKU, free text) is never reshaped.
"""

from __future__ import annotations

import pytest

from app.modules.pos.service import PosService
from tests._pos_helpers import ctx_for, till
from tests.test_pos_scan_generic_barcode import _register, _scan

pytestmark = pytest.mark.asyncio

EAN13 = "6221234567891"
UPC12 = "036000291452"


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("٦٢٢١٢٣٤٥٦٧٨٩١", EAN13),
        ("６２２１２３４５６７８９１", EAN13),
        ("]E06221234567891", EAN13),
        ("]C1" + EAN13, EAN13),
        (EAN13 + "\u200b", EAN13),
        ("\x1d" + EAN13 + "\r\n", EAN13),
        ("SKU-ABC-1", "SKU-ABC-1"),
        ("]x", "]x"),
        ("sku ٣", "sku 3"),
    ],
)
def test_the_code_is_cleaned_and_nothing_else_is_reshaped(raw, clean):
    assert PosService._clean_scanned_code(raw) == clean


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (UPC12, {"0" + UPC12, "00" + UPC12}),
        ("0" + UPC12, {UPC12, "00" + UPC12}),
        ("SKU-1", set()),
        ("12345", set()),
        ("٣٦٠٠٠٢٩١٤٥٢", set()),
    ],
)
def test_zero_padded_spellings_only_for_plain_barcode_lengths(code, expected):
    assert set(PosService._zero_padded_forms(code)) == expected


@pytest.mark.parametrize(
    "scanned",
    [
        "٦٢٢١٢٣٤٥٦٧٨٩١",
        "６２２１٢٣٤٥٦٧٨٩١",
        "]E0" + EAN13,
        EAN13 + "\u200b",
        "  " + EAN13 + "\r\n",
        "0" + EAN13,
    ],
)
async def test_a_registered_code_is_found_however_it_arrives(db, tenant_ctx, scanned) -> None:
    shift, variant, _ = await till(db, tenant_ctx)
    owner = await ctx_for(db, tenant_ctx, "owner")
    staff = await ctx_for(db, tenant_ctx, "staff")
    await _register(owner, variant.id, "ean", EAN13)

    found = await _scan(staff, shift.id, "barcode", scanned)

    assert found["found"] is True
    assert found["variant_id"] == str(variant.id)


async def test_the_same_product_is_found_under_either_leading_zero_spelling(db, tenant_ctx) -> None:
    shift, variant, _ = await till(db, tenant_ctx)
    owner = await ctx_for(db, tenant_ctx, "owner")
    staff = await ctx_for(db, tenant_ctx, "staff")
    await _register(owner, variant.id, "upc", UPC12)

    for scanned in (UPC12, "0" + UPC12, "00" + UPC12):
        found = await _scan(staff, shift.id, "barcode", scanned)
        assert found["found"] is True, scanned


async def test_a_named_type_is_not_widened(db, tenant_ctx) -> None:
    shift, variant, _ = await till(db, tenant_ctx)
    owner = await ctx_for(db, tenant_ctx, "owner")
    staff = await ctx_for(db, tenant_ctx, "staff")
    await _register(owner, variant.id, "ean", EAN13)

    found = await _scan(staff, shift.id, "ean", "]E0" + EAN13)

    assert found["found"] is False


async def test_a_wrong_check_digit_is_still_refused_after_cleaning(db, tenant_ctx) -> None:
    shift, _variant, _ = await till(db, tenant_ctx)
    staff = await ctx_for(db, tenant_ctx, "staff")

    refused = await _scan(staff, shift.id, "barcode", "٦٢٢١٢٣٤٥٦٧٨٩٠")

    assert refused["found"] is False
    assert refused["refusal"] == "invalid_barcode"


async def test_a_valid_unknown_code_in_arabic_digits_is_not_called_wrong(db, tenant_ctx) -> None:
    shift, _variant, _ = await till(db, tenant_ctx)
    staff = await ctx_for(db, tenant_ctx, "staff")

    missing = await _scan(staff, shift.id, "barcode", "٥٩٠١٢٣٤١٢٣٤٥٧")

    assert missing == {"found": False}
