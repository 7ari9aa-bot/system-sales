"""An EAN/GTIN with a wrong check digit is refused when it is filed (it could never print)."""

from __future__ import annotations

import uuid

import pytest

from app.modules.catalog.services import CatalogService
from app.modules.errors import ValidationError


async def _variant(db, tenant_ctx):
    product = await CatalogService.create_product(
        db,
        tenant_ctx.tenant_id,
        title="بنطلون",
        slug=f"pants-{uuid.uuid4().hex[:10]}",
    )
    return await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="كحلي / L", price="650.00"
    )


@pytest.mark.parametrize("kind", ["ean", "gtin"])
async def test_wrong_check_digit_is_refused(db, tenant_ctx, kind):
    variant = await _variant(db, tenant_ctx)
    with pytest.raises(ValidationError, match="غير صحيح"):
        await CatalogService.add_identifier(
            db, tenant_ctx.tenant_id, variant.id, kind, "2991000102947"
        )


@pytest.mark.parametrize("kind", ["ean", "gtin"])
async def test_right_check_digit_is_accepted(db, tenant_ctx, kind):
    variant = await _variant(db, tenant_ctx)
    row = await CatalogService.add_identifier(
        db, tenant_ctx.tenant_id, variant.id, kind, "2000000000015"
    )
    assert row.value == "2000000000015"


@pytest.mark.parametrize("kind", ["barcode", "external", "qr_token"])
async def test_free_form_types_are_not_checked(db, tenant_ctx, kind):
    """The shop's own free-form codes keep working, even a 13-digit one that is not an EAN."""
    variant = await _variant(db, tenant_ctx)
    row = await CatalogService.add_identifier(
        db, tenant_ctx.tenant_id, variant.id, kind, "2991000102947"
    )
    assert row.value == "2991000102947"


async def test_short_or_lettered_ean_is_not_mistaken_for_a_checksum_error(db, tenant_ctx):
    """Only a 13-digit code is judged; anything else keeps its existing behaviour."""
    variant = await _variant(db, tenant_ctx)
    row = await CatalogService.add_identifier(
        db, tenant_ctx.tenant_id, variant.id, "ean", "EAN-ONLY"
    )
    assert row.value == "EAN-ONLY"


@pytest.mark.parametrize("kind", ["ean", "gtin"])
async def test_a_manufacturer_or_older_code_is_kept_whatever_its_check_digit(db, tenant_ctx, kind):
    """The shop files what is on its stock; the till finds a filed code before judging it."""
    variant = await _variant(db, tenant_ctx)
    row = await CatalogService.add_identifier(
        db, tenant_ctx.tenant_id, variant.id, kind, "6221234567890"
    )
    assert row.value == "6221234567890"


# ---- correcting a wrongly filed code: delete it from ITS variant, then file the right one ----


async def test_a_wrong_code_is_removed_from_its_variant_and_the_right_one_filed(db, tenant_ctx):
    variant = await _variant(db, tenant_ctx)
    bad = await CatalogService.add_identifier(
        db, tenant_ctx.tenant_id, variant.id, "barcode", "2991000102947"
    )
    await CatalogService.remove_identifier(db, tenant_ctx.tenant_id, bad.id, variant_id=variant.id)
    good = await CatalogService.add_identifier(
        db, tenant_ctx.tenant_id, variant.id, "ean", "2991000102949"
    )
    kept = await CatalogService.list_identifiers(db, tenant_ctx.tenant_id, variant.id)
    assert [r.value for r in kept] == ["2991000102949"]
    assert good.id != bad.id


async def test_a_code_cannot_be_removed_through_another_variants_url(db, tenant_ctx):
    """The id alone is not enough: it has to belong to the variant named in the URL."""
    from app.core.errors import NotFoundError

    mine = await _variant(db, tenant_ctx)
    other = await _variant(db, tenant_ctx)
    row = await CatalogService.add_identifier(
        db, tenant_ctx.tenant_id, mine.id, "barcode", "SHOP-ONLY-1"
    )
    with pytest.raises(NotFoundError):
        await CatalogService.remove_identifier(
            db, tenant_ctx.tenant_id, row.id, variant_id=other.id
        )
    assert len(await CatalogService.list_identifiers(db, tenant_ctx.tenant_id, mine.id)) == 1


async def test_removing_with_no_variant_named_keeps_the_old_behaviour(db, tenant_ctx):
    variant = await _variant(db, tenant_ctx)
    row = await CatalogService.add_identifier(
        db, tenant_ctx.tenant_id, variant.id, "barcode", "OLD-STYLE-1"
    )
    await CatalogService.remove_identifier(db, tenant_ctx.tenant_id, row.id)
    assert await CatalogService.list_identifiers(db, tenant_ctx.tenant_id, variant.id) == []
