"""A generic `barcode` scan finds a code registered as ean/gtin/upc.

Found by scanning over HTTP: the till always sends ``identifier_type: "barcode"``, but packaged
products are registered as ``ean``. The exact-type lookup returned ``found: false`` for them.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.modules.identity.deps import get_db, get_tenant_ctx
from tests._pos_helpers import ctx_for, till

pytestmark = pytest.mark.asyncio


def _app(ctx):
    app = create_app()
    app.user_middleware = [
        m for m in app.user_middleware if m.cls not in {IdempotencyMiddleware, RateLimitMiddleware}
    ]
    app.middleware_stack = None

    async def _session():
        yield ctx.session

    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _session
    return app


async def _call(ctx, method, path, body):
    async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as c:
        return await c.request(method, path, json=body)


async def _register(owner, variant_id, kind, value):
    r = await _call(
        owner,
        "POST",
        f"/api/v1/variants/{variant_id}/identifiers",
        {"identifier_type": kind, "value": value},
    )
    assert r.status_code == 201, r.text


async def _scan(staff, session_id, kind, value):
    r = await _call(
        staff,
        "POST",
        f"/api/v1/pos/sessions/{session_id}/scan",
        {"identifier_type": kind, "value": value},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("registered_as", ["ean", "gtin", "upc"])
async def test_generic_barcode_scan_finds_a_packaged_code(db, tenant_ctx, registered_as) -> None:
    shift, variant, _ = await till(db, tenant_ctx)
    owner = await ctx_for(db, tenant_ctx, "owner")
    staff = await ctx_for(db, tenant_ctx, "staff")
    await _register(owner, variant.id, registered_as, "6221234567890")

    found = await _scan(staff, shift.id, "barcode", "6221234567890")

    assert found["found"] is True
    assert found["variant_id"] == str(variant.id)


async def test_a_specific_type_stays_exact(db, tenant_ctx) -> None:
    shift, variant, _ = await till(db, tenant_ctx)
    owner = await ctx_for(db, tenant_ctx, "owner")
    staff = await ctx_for(db, tenant_ctx, "staff")
    await _register(owner, variant.id, "ean", "6221234567890")

    assert (await _scan(staff, shift.id, "upc", "6221234567890"))["found"] is False
    assert (await _scan(staff, shift.id, "ean", "6221234567890"))["found"] is True


async def test_a_code_registered_as_barcode_still_wins_and_unknown_is_not_found(
    db, tenant_ctx
) -> None:
    shift, variant, _ = await till(db, tenant_ctx)
    owner = await ctx_for(db, tenant_ctx, "owner")
    staff = await ctx_for(db, tenant_ctx, "staff")
    await _register(owner, variant.id, "barcode", "LOCAL-001")

    assert (await _scan(staff, shift.id, "barcode", "LOCAL-001"))["found"] is True
    assert (await _scan(staff, shift.id, "barcode", "NOPE-404"))["found"] is False


# ---------------------------------------------------------------------------------------------
# A scanned code that is not in the shop AND looks like a packaged barcode whose check digit does
# not add up is a misread, not an unknown product. The cashier is told the barcode is wrong.
# ---------------------------------------------------------------------------------------------

VALID_EAN13 = "6221234567891"  # check digit computed by the GS1 rule
WRONG_EAN13 = "6221234567890"  # same body, wrong check digit
NINE_DIGITS = "963850742"  # no GS1 code has 9 digits


async def test_a_misread_barcode_is_refused_as_wrong_not_just_not_found(db, tenant_ctx) -> None:
    shift, _variant, _ = await till(db, tenant_ctx)
    staff = await ctx_for(db, tenant_ctx, "staff")

    result = await _scan(staff, shift.id, "barcode", WRONG_EAN13)

    assert result["found"] is False
    assert result["refusal"] == "invalid_barcode"


async def test_a_valid_but_unknown_barcode_is_plain_not_found(db, tenant_ctx) -> None:
    shift, _variant, _ = await till(db, tenant_ctx)
    staff = await ctx_for(db, tenant_ctx, "staff")

    result = await _scan(staff, shift.id, "barcode", VALID_EAN13)

    assert result == {"found": False}


async def test_a_code_the_shop_registered_is_found_even_if_its_check_digit_is_wrong(
    db, tenant_ctx
) -> None:
    # Shops register old and internal numbers of barcode length. Finding it comes first, so the
    # check digit never locks a registered product out of the till.
    shift, variant, _ = await till(db, tenant_ctx)
    owner = await ctx_for(db, tenant_ctx, "owner")
    staff = await ctx_for(db, tenant_ctx, "staff")
    await _register(owner, variant.id, "ean", WRONG_EAN13)

    found = await _scan(staff, shift.id, "barcode", WRONG_EAN13)

    assert found["found"] is True
    assert found["variant_id"] == str(variant.id)


@pytest.mark.parametrize(
    "code",
    [
        "NOPE-404",
        "LOCAL-001",
        "12345",
        NINE_DIGITS,
        "62212345678",
        "ABCDEFGHIJKLM",
        "62212345678x0",
    ],
)
async def test_a_code_that_does_not_look_like_a_barcode_is_never_called_invalid(
    db, tenant_ctx, code
) -> None:
    # Only 8, 12, 13 or 14 digits can be a GS1 barcode. Anything else (a SKU, a short internal code,
    # text) stays a plain "not found" so the cashier can still type it into the search.
    shift, _variant, _ = await till(db, tenant_ctx)
    staff = await ctx_for(db, tenant_ctx, "staff")

    assert await _scan(staff, shift.id, "barcode", code) == {"found": False}


@pytest.mark.parametrize(
    ("good", "bad"),
    [
        ("96385074", "96385075"),  # EAN-8
        ("036000291452", "036000291453"),  # UPC-A (12)
        ("5901234123457", "5901234123458"),  # EAN-13
        ("15901234123454", "15901234123455"),  # GTIN-14
    ],
)
async def test_every_gs1_length_is_checked(db, tenant_ctx, good, bad) -> None:
    shift, _variant, _ = await till(db, tenant_ctx)
    staff = await ctx_for(db, tenant_ctx, "staff")

    assert await _scan(staff, shift.id, "barcode", good) == {"found": False}
    assert (await _scan(staff, shift.id, "barcode", bad))["refusal"] == "invalid_barcode"


async def test_a_specific_type_scan_is_not_second_guessed(db, tenant_ctx) -> None:
    # Only the generic `barcode` scan (a hand scanner) is checked; a caller who names a type gets
    # the exact lookup it asked for and nothing else.
    shift, _variant, _ = await till(db, tenant_ctx)
    staff = await ctx_for(db, tenant_ctx, "staff")

    assert await _scan(staff, shift.id, "ean", WRONG_EAN13) == {"found": False}
