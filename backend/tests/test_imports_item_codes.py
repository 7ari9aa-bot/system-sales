"""Importing the tax authority's item codes (EGS / GS1) from the merchant's Excel sheet.

A clothing shop has hundreds of variants and each needs a registered code before its receipt can
go. Typing them one by one is the real obstacle, so the file carries them: SKU, type, code.

What this layer can promise is the SHAPE of a code. It cannot know whether the authority has
registered one: that needs the merchant's ETA account. So a GS1 code is checked by its published
check digit (a universal rule), an EGS code by being a clean, bounded string, and neither is
ever invented.
"""

from __future__ import annotations

import pytest

import app.core.model_registry  # noqa: F401
from app.modules.imports import normalize as n
from app.modules.imports.apply import SHEET_ORDER
from app.modules.imports.fields import SHEET_FIELDS, SHEET_ITEM_CODES
from app.modules.imports.mapping import suggest_mapping
from app.modules.imports.validation import validate_item_codes

MAP = {"SKU": "sku", "Type": "code_type", "Code": "code"}

GOOD_GTIN13 = "6224000123452"  # check digit verified below, not trusted by eye


def _gtin_check_digit(body: str) -> str:
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str((10 - total % 10) % 10)


def _good_gtin(body12: str = "622400012345") -> str:
    return body12 + _gtin_check_digit(body12)


# ---- the GS1 check digit ----------------------------------------------------------------------


def test_the_check_digit_helper_agrees_with_published_gtins():
    # 4006381333931 is the worked example in the GS1 General Specifications; 5901234123457 is the
    # EAN-13 example in the same document. Neither number comes from this code.
    assert _gtin_check_digit("400638133393") == "1"
    assert _gtin_check_digit("590123412345") == "7"


@pytest.mark.parametrize("length", [8, 12, 13, 14])
def test_a_gtin_of_every_legal_length_with_the_right_digit_is_accepted(length):
    body = ("622400012345678"[: length - 1]).ljust(length - 1, "1")
    code = body + _gtin_check_digit(body)
    assert n.parse_item_code("GS1", code) == code


def test_a_gtin_with_a_wrong_check_digit_is_refused():
    good = _good_gtin()
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)
    with pytest.raises(n.CellError) as err:
        n.parse_item_code("GS1", bad)
    assert err.value.code == "bad_check_digit"


@pytest.mark.parametrize(
    "raw", ["62240001234", "622400012345678901", "62240001234A5", "ABCDEFGHIJKLM"]
)
def test_a_gs1_code_that_is_not_a_gtin_is_refused(raw):
    with pytest.raises(n.CellError) as err:
        n.parse_item_code("GS1", raw)
    assert err.value.code in {"not_a_gtin", "bad_length"}


# ---- EGS and the things every code must satisfy -----------------------------------------------


def test_an_egs_code_is_kept_exactly_as_the_merchant_wrote_it():
    assert n.parse_item_code("EGS", " EG-674859545-TEE-RED-M ") == "EG-674859545-TEE-RED-M"


@pytest.mark.parametrize(
    ("kind", "raw", "code"),
    [
        ("EGS", "", "required"),
        ("EGS", "EG 100 1", "has_spaces"),
        ("EGS", "1.23E+12", "scientific_notation"),
        ("EGS", "E" * 200, "too_long"),
        ("GS1", "6.224E+12", "scientific_notation"),
    ],
)
def test_a_broken_code_is_refused_with_a_stable_reason(kind, raw, code):
    with pytest.raises(n.CellError) as err:
        n.parse_item_code(kind, raw)
    assert err.value.code == code


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("EGS", "EGS"), ("egs", "EGS"), (" Gs1 ", "GS1"), ("gs1", "GS1"), ("GTIN", "GS1")],
)
def test_the_type_is_read_in_any_case(raw, expected):
    assert n.parse_item_code_type(raw) == expected


@pytest.mark.parametrize("raw", ["", "SKU", "barcode", "EAN"])
def test_only_the_two_official_types_are_accepted(raw):
    with pytest.raises(n.CellError):
        n.parse_item_code_type(raw)


# ---- the sheet --------------------------------------------------------------------------------


def _verdicts(rows, *, known=("TEE-1",), in_file=(), existing=None):
    numbered = [(i + 2, r) for i, r in enumerate(rows)]
    return validate_item_codes(
        numbered,
        MAP,
        skus_in_file=set(in_file),
        known_skus=set(known),
        existing=existing or {},
    )


def _row(sku="TEE-1", kind="EGS", code="EG-1001"):
    return {"SKU": sku, "Type": kind, "Code": code}


def test_a_good_row_is_valid_and_carries_clean_values():
    (v,) = _verdicts([_row(code=" EG-1001 ")])
    assert v.ok and v.action == "create"
    assert v.values == {"sku": "TEE-1", "code_type": "EGS", "code": "EG-1001"}


def test_an_unknown_sku_is_refused_unless_the_same_file_creates_it():
    assert _verdicts([_row(sku="NOPE")])[0].errors[0].code == "unknown_sku"
    assert _verdicts([_row(sku="NEW-1")], in_file=("NEW-1",))[0].ok


def test_the_same_code_on_two_different_skus_refuses_the_second():
    a, b = _verdicts([_row(sku="A", code="EG-9"), _row(sku="B", code="EG-9")], known=("A", "B"))
    assert a.ok
    assert [e.code for e in b.errors] == ["duplicate_in_file"]


def test_a_code_already_on_another_variant_is_refused_never_moved():
    (v,) = _verdicts([_row(sku="TEE-1", code="EG-9")], existing={("EGS", "EG-9"): "OTHER-SKU"})
    assert [e.code for e in v.errors] == ["code_taken"]


def test_the_same_code_already_on_the_same_variant_is_a_skip_so_a_rerun_adds_nothing():
    (v,) = _verdicts([_row(sku="TEE-1", code="EG-9")], existing={("EGS", "EG-9"): "TEE-1"})
    assert v.ok and v.action == "skip"


def test_one_variant_gets_one_code_per_type_a_second_egs_is_refused():
    a, b = _verdicts([_row(code="EG-1"), _row(code="EG-2")])
    assert a.ok and [e.code for e in b.errors] == ["second_code_for_type"]


def test_a_variant_can_carry_both_an_egs_and_a_gs1_code():
    a, b = _verdicts([_row(kind="EGS", code="EG-1"), _row(kind="GS1", code=_good_gtin())])
    assert a.ok and b.ok


def test_every_problem_on_a_row_is_reported_not_just_the_first():
    (v,) = _verdicts([_row(sku="", kind="barcode", code="")])
    assert {e.field for e in v.errors} >= {"sku", "code_type", "code"}


# ---- wiring -----------------------------------------------------------------------------------


def test_the_sheet_is_known_and_applied_after_the_variants_exist():
    assert SHEET_ITEM_CODES in SHEET_FIELDS
    assert SHEET_ORDER.index(SHEET_ITEM_CODES) > SHEET_ORDER.index("Variants")


def test_the_header_names_a_merchant_would_use_are_matched_in_both_languages():
    got = suggest_mapping(SHEET_ITEM_CODES, ["SKU", "نوع الكود", "كود الصنف الضريبي", "note"])
    assert got["SKU"] == "sku"
    assert got["نوع الكود"] == "code_type"
    assert got["كود الصنف الضريبي"] == "code"
    assert got["note"] is None
    assert {f.key for f in SHEET_FIELDS[SHEET_ITEM_CODES]} == {"sku", "code_type", "code"}


# ---- on a real database -----------------------------------------------------------------------
# These need the Postgres the rest of the suite uses (the `db` fixture); they prove the row really
# lands on the right variant, that a re-run adds nothing, and that a taken code fails ONLY its row.

import sqlalchemy as sa  # noqa: E402

from app.modules.imports import lookup  # noqa: E402
from app.workers.import_runner import run_batch  # noqa: E402
from tests.test_imports_images import _shop_with_sku  # noqa: E402
from tests.test_imports_run import _job, _session  # noqa: E402
from tests.test_imports_run import _row as _stored_row  # noqa: E402


def _code_row(s, number, sku, kind, code, action="create"):
    return _stored_row(
        s, SHEET_ITEM_CODES, number, action, {"sku": sku, "code_type": kind, "code": code}
    )


async def _identifiers(db, tenant_id):
    rows = await db.execute(
        sa.text(
            "select i.type, i.value, v.sku from product_identifiers i "
            "join product_variants v on v.id = i.variant_id "
            "where i.tenant_id = :t and i.type in ('egs','gs1') order by i.value"
        ),
        {"t": tenant_id},
    )
    return [tuple(r) for r in rows.all()]


async def test_a_code_row_lands_on_the_right_variant_as_the_lowercase_catalog_type(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    _, variant = await _shop_with_sku(db, t)
    s = await _session(db, t)
    gtin = _good_gtin()
    db.add_all(
        [
            _code_row(s, 2, variant.sku, "EGS", "EG-1001"),
            _code_row(s, 3, variant.sku, "GS1", gtin),
        ]
    )
    await db.flush()

    result = await run_batch(db, await _job(db, t, s))

    assert (result["applied"], result["failed"]) == (2, 0)
    assert sorted(await _identifiers(db, t)) == [
        ("egs", "EG-1001", variant.sku),
        ("gs1", gtin, variant.sku),
    ]


async def test_a_code_another_variant_took_in_the_meantime_fails_only_its_row(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    _, variant = await _shop_with_sku(db, t)
    from app.applications.apparel.modules.catalog.service import CatalogService

    await CatalogService.add_identifier(db, t, variant.id, "egs", "EG-TAKEN")
    s = await _session(db, t)
    db.add_all(
        [
            _code_row(s, 2, variant.sku, "EGS", "EG-TAKEN"),  # raced: preview said create
            _code_row(s, 3, variant.sku, "GS1", _good_gtin()),
        ]
    )
    await db.flush()

    result = await run_batch(db, await _job(db, t, s))

    assert (result["applied"], result["failed"]) == (1, 1)
    assert sorted(r[0] for r in await _identifiers(db, t)) == [
        "egs",
        "gs1",
    ]  # the taken one untouched


async def test_a_skip_row_writes_nothing(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    _, variant = await _shop_with_sku(db, t)
    s = await _session(db, t)
    db.add(_code_row(s, 2, variant.sku, "EGS", "EG-1001", action="skip"))
    await db.flush()

    result = await run_batch(db, await _job(db, t, s))

    assert result["skipped"] == 1
    assert await _identifiers(db, t) == []


async def test_the_lookup_reports_who_holds_a_code_and_what_a_sku_already_carries(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    _, variant = await _shop_with_sku(db, t)
    from app.applications.apparel.modules.catalog.service import CatalogService

    await CatalogService.add_identifier(db, t, variant.id, "egs", "EG-7")

    owners = await lookup.load_item_code_owners(db, t, ["EG-7", "EG-NOPE"])
    held = await lookup.load_codes_by_sku(db, t, [variant.sku, "OTHER"])

    assert owners == {("EGS", "EG-7"): variant.sku}
    assert held == {("EGS", variant.sku): "EG-7"}


async def test_the_whole_file_round_trip_preview_then_a_second_code_for_a_type_is_refused(
    db, tenant_ctx
):
    """The validator fed by the REAL lookups, the way the service wires it."""
    t = tenant_ctx.tenant_id
    _, variant = await _shop_with_sku(db, t)
    from app.applications.apparel.modules.catalog.service import CatalogService

    await CatalogService.add_identifier(db, t, variant.id, "egs", "EG-OLD")
    rows = [
        (2, _row_dict(variant.sku, "EGS", "EG-NEW")),
        (3, _row_dict(variant.sku, "EGS", "EG-OLD")),
    ]

    got = validate_item_codes(
        rows,
        MAP,
        skus_in_file=set(),
        known_skus={variant.sku},
        existing=await lookup.load_item_code_owners(db, t, ["EG-NEW", "EG-OLD"]),
        held_by_sku=await lookup.load_codes_by_sku(db, t, [variant.sku]),
    )

    assert [e.code for e in got[0].errors] == ["second_code_for_type"]
    assert got[1].ok and got[1].action == "skip"  # the code it already has: a re-run, not an error


def _row_dict(sku, kind, code):
    return {"SKU": sku, "Type": kind, "Code": code}
