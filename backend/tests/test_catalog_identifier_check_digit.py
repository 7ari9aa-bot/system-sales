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
