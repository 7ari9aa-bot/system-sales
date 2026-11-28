"""TAXATION: the seller identity and tax classes. The service explains; the database refuses."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.main import create_app
from app.modules.errors import ConflictError, ValidationError
from app.applications.apparel.modules.taxation.models import BusinessProfile, TaxClass
from app.applications.apparel.modules.taxation.service import TaxationService, normalise_tax_number
from tests._pos_helpers import in_tx as _in_tx
from tests._pos_helpers import make_tenant as _make_tenant
from tests._pos_helpers import purge_test_tenant as _purge_test_tenant


def test_taxation_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {"/api/v1/taxation/profile", "/api/v1/taxation/classes"} <= paths


@pytest.mark.parametrize(
    "typed,stored",
    [
        ("123456789", "123456789"),
        (" 123-456-789 ", "123456789"),
        ("١٢٣٤٥٦٧٨٩", "123456789"),  # Arabic-Indic digits from an Arabic keyboard
        ("۱۲۳۴۵۶۷۸۹", "123456789"),  # Eastern Arabic-Indic
        ("", None),
        (None, None),
    ],
)
def test_tax_number_is_normalised_to_ascii_digits(typed, stored) -> None:
    assert normalise_tax_number(typed) == stored


@pytest.mark.parametrize("bad", ["12345678", "1234567890", "12345678a", "١٢٣", "12 34", "x" * 9])
def test_a_tax_number_that_is_not_nine_digits_is_refused(bad) -> None:
    with pytest.raises(ValidationError):
        normalise_tax_number(bad)


async def test_a_vat_registered_shop_needs_its_number(db, tenant_ctx) -> None:
    with pytest.raises(ValidationError):
        await TaxationService.upsert_profile(
            db, tenant_ctx.tenant_id, legal_name="متجر النور", vat_status="registered"
        )


async def test_profile_is_one_row_edited_in_place(db, tenant_ctx) -> None:
    first = await TaxationService.upsert_profile(
        db, tenant_ctx.tenant_id, legal_name="متجر النور", city="القاهرة"
    )
    again = await TaxationService.upsert_profile(
        db,
        tenant_ctx.tenant_id,
        legal_name="متجر النور للملابس",
        vat_status="registered",
        tax_registration_number="١٢٣٤٥٦٧٨٩",
        city="الجيزة",
    )
    assert again.id == first.id
    rows = (await db.execute(select(BusinessProfile))).scalars().all()
    assert len(rows) == 1
    assert rows[0].tax_registration_number == "123456789"
    assert rows[0].city == "الجيزة"
    # a field the caller did not send is left alone, not blanked
    assert rows[0].branch_code == "0"


async def test_readiness_names_what_is_missing(db, tenant_ctx) -> None:
    assert TaxationService.fiscal_readiness(None) == ["بيانات المنشأة لم تُدخل بعد"]
    row = await TaxationService.upsert_profile(db, tenant_ctx.tenant_id, legal_name="متجر")
    missing = TaxationService.fiscal_readiness(row)
    assert "الرقم الضريبي" in missing
    assert "كود النشاط" in missing
    full = await TaxationService.upsert_profile(
        db,
        tenant_ctx.tenant_id,
        legal_name="متجر",
        vat_status="registered",
        tax_registration_number="123456789",
        activity_code="4771",
        governorate="القاهرة",
        city="مدينة نصر",
        street="شارع عباس العقاد",
    )
    assert TaxationService.fiscal_readiness(full) == []


async def test_unknown_profile_fields_are_refused_not_ignored(db, tenant_ctx) -> None:
    with pytest.raises(ValidationError):
        await TaxationService.upsert_profile(
            db, tenant_ctx.tenant_id, legal_name="متجر", favourite_colour="red"
        )


async def test_every_shop_starts_with_the_three_egyptian_classes(db, tenant_ctx) -> None:
    rows = await TaxationService.ensure_default_classes(db, tenant_ctx.tenant_id)
    by_code = {r.code: r for r in rows}
    assert set(by_code) == {"VAT14", "ZERO", "EXEMPT"}
    assert by_code["VAT14"].rate == Decimal("0.1400")
    assert by_code["VAT14"].is_default is True
    assert by_code["ZERO"].rate == Decimal("0") and by_code["EXEMPT"].rate == Decimal("0")
    # asking again does not duplicate them
    again = await TaxationService.ensure_default_classes(db, tenant_ctx.tenant_id)
    assert len(again) == 3
    assert (await TaxationService.default_class(db, tenant_ctx.tenant_id)).code == "VAT14"


@pytest.mark.parametrize("bad_rate", ["abc", "-0.1", "1.5", "14"])
async def test_a_percentage_typed_as_a_whole_number_is_refused(db, tenant_ctx, bad_rate) -> None:
    # 14 would silently mean 1400%: the API takes a fraction (0.14) and says so.
    with pytest.raises(ValidationError):
        await TaxationService.create_class(
            db, tenant_ctx.tenant_id, code="X", name="خطأ", rate=bad_rate
        )


async def test_a_class_code_cannot_be_reused(db, tenant_ctx) -> None:
    await TaxationService.create_class(
        db, tenant_ctx.tenant_id, code="vat5", name="5%", rate="0.05"
    )
    with pytest.raises(ConflictError):
        await TaxationService.create_class(
            db, tenant_ctx.tenant_id, code="VAT5", name="مكرر", rate="0.05"
        )


# ---- the database is the last line: raw SQL, no service in the way ----


async def _raw_insert_profile(db, tenant_id, **cols) -> None:
    base = {"legal_name": "x", "vat_status": "not_registered", "tax_registration_number": None}
    base.update(cols)
    await db.execute(
        text(
            "INSERT INTO business_profiles (id, tenant_id, legal_name, vat_status, "
            "tax_registration_number) VALUES (:i, :t, :n, :v, :r)"
        ),
        {
            "i": uuid.uuid4(),
            "t": tenant_id,
            "n": base["legal_name"],
            "v": base["vat_status"],
            "r": base["tax_registration_number"],
        },
    )


@pytest.mark.parametrize(
    "cols",
    [
        {"vat_status": "registered", "tax_registration_number": None},
        {"tax_registration_number": "12345"},
        {"tax_registration_number": "12345678a"},
        {"vat_status": "maybe"},
    ],
)
async def test_the_database_refuses_a_bad_profile(db, tenant_ctx, cols) -> None:
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await _raw_insert_profile(db, tenant_ctx.tenant_id, **cols)


async def test_the_database_allows_only_one_default_class(db, tenant_ctx) -> None:
    await TaxationService.ensure_default_classes(db, tenant_ctx.tenant_id)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                TaxClass(
                    tenant_id=tenant_ctx.tenant_id,
                    code="SECOND",
                    name="ثاني",
                    rate=Decimal("0.05"),
                    is_default=True,
                )
            )
            await db.flush()


# ---- isolation ----


@pytest.fixture
async def two_tenants(db_url, admin_url):
    ea, fa, ta, ua = await _make_tenant(db_url, "a")
    eb, fb, tb, ub = await _make_tenant(db_url, "b")
    try:
        yield (fa, ta), (fb, tb)
    finally:
        await ea.dispose()
        await eb.dispose()
        await _purge_test_tenant(admin_url, ta, ua)
        await _purge_test_tenant(admin_url, tb, ub)


async def test_one_shop_never_sees_anothers_tax_identity(two_tenants) -> None:
    (fa, ta), (fb, tb) = two_tenants
    made = await _in_tx(
        fa,
        ta,
        lambda s: TaxationService.upsert_profile(
            s,
            ta,
            legal_name="سري A",
            vat_status="registered",
            tax_registration_number="111222333",
        ),
    )
    assert not isinstance(made, Exception), made
    await _in_tx(fa, ta, lambda s: TaxationService.ensure_default_classes(s, ta))

    # B asking for A's profile by A's tenant id: the tenant guard returns nothing
    seen = await _in_tx(fb, tb, lambda s: TaxationService.get_profile(s, ta))
    assert seen is None
    classes = await _in_tx(fb, tb, lambda s: TaxationService.list_classes(s, ta))
    assert classes == []
    # and B writing into A's tenant is refused by the row policy, not just filtered
    attack = await _in_tx(
        fb,
        tb,
        lambda s: TaxationService.upsert_profile(s, ta, legal_name="اختراق"),
    )
    assert isinstance(attack, Exception)
