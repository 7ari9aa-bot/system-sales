"""A prescription-only medicine is sold only against a named prescription.

Through the real sale endpoint. A pharmacy marks a product ``prescription_only`` and turns on the
``prescription_required`` capability for its workspace; a shop that has not, and a product that is
not marked, sell exactly as before.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.applications.apparel.modules.catalog.models import Product
from app.applications.apparel.modules.inventory.models import InventoryBalance
from app.applications.apparel.modules.orders.models import Order
from app.applications.apparel.modules.pos.prescription import clean_reference, is_prescription_only
from app.applications.apparel.modules.pos.service import PosService
from app.modules.settings.service import SettingsService
from tests._pos_helpers import ctx_for, start_day, till
from tests.test_pos_sale_http import _post

pytestmark = pytest.mark.asyncio

RX = {"number": "RX-4471", "name": "منى عبد الله"}


async def _shop(db, tenant_ctx, *, flagged: bool, capability: bool):
    shift, variant, _customer = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)
    await start_day(db, tenant_ctx, shift.register_id)
    if flagged:
        product = (
            await db.execute(select(Product).where(Product.id == variant.product_id))
        ).scalar_one()
        product.attributes = {**(product.attributes or {}), "prescription_only": True}
        await db.flush()
    if capability:
        await SettingsService(db, tenant_ctx.tenant_id).set(
            "capability.prescription_required", True
        )
    return shift.register_id, variant


async def _sell(db, tenant_ctx, register_id, variant, **extra):
    ctx = await ctx_for(db, tenant_ctx, "owner")
    return await _post(
        ctx,
        f"/api/v1/pos/registers/{register_id}/sales",
        {"items": [{"variant_id": str(variant.id), "quantity": 1}], **extra},
    )


async def _extra_of(db, order_id) -> dict:
    return (await db.execute(select(Order.extra).where(Order.id == order_id))).scalar_one() or {}


async def _on_hand(db, variant_id) -> int:
    rows = (
        await db.execute(
            select(InventoryBalance.on_hand).where(InventoryBalance.variant_id == variant_id)
        )
    ).scalars()
    return sum(rows)


async def test_a_prescription_only_sale_without_a_prescription_is_refused(db, tenant_ctx) -> None:
    register_id, variant = await _shop(db, tenant_ctx, flagged=True, capability=True)
    before = await _on_hand(db, variant.id)

    r = await _sell(db, tenant_ctx, register_id, variant)

    assert r.status_code in (400, 422), r.text
    assert "prescription" in r.text.lower()
    assert await _on_hand(db, variant.id) == before  # refused before any stock moved


async def test_a_half_filled_prescription_counts_as_none(db, tenant_ctx) -> None:
    register_id, variant = await _shop(db, tenant_ctx, flagged=True, capability=True)

    r = await _sell(
        db, tenant_ctx, register_id, variant, prescription={"number": "RX-1", "name": " "}
    )

    assert r.status_code in (400, 422), r.text


async def test_a_named_prescription_lets_the_sale_through_and_is_kept(db, tenant_ctx) -> None:
    register_id, variant = await _shop(db, tenant_ctx, flagged=True, capability=True)

    r = await _sell(db, tenant_ctx, register_id, variant, prescription=RX)

    assert r.status_code == 201, r.text
    assert (await _extra_of(db, r.json()["order_id"]))["prescription"] == RX


async def test_the_prescription_is_trimmed_before_it_is_kept(db, tenant_ctx) -> None:
    register_id, variant = await _shop(db, tenant_ctx, flagged=True, capability=True)

    r = await _sell(
        db, tenant_ctx, register_id, variant, prescription={"number": "  RX-9 ", "name": " سلمى "}
    )

    assert r.status_code == 201, r.text
    assert (await _extra_of(db, r.json()["order_id"]))["prescription"] == {
        "number": "RX-9",
        "name": "سلمى",
    }


async def test_a_shop_that_did_not_turn_it_on_sells_the_same_marked_product_freely(
    db, tenant_ctx
) -> None:
    register_id, variant = await _shop(db, tenant_ctx, flagged=True, capability=False)

    r = await _sell(db, tenant_ctx, register_id, variant)

    assert r.status_code == 201, r.text
    assert "prescription" not in await _extra_of(db, r.json()["order_id"])


async def test_a_product_that_is_not_marked_needs_no_prescription(db, tenant_ctx) -> None:
    register_id, variant = await _shop(db, tenant_ctx, flagged=False, capability=True)

    r = await _sell(db, tenant_ctx, register_id, variant)

    assert r.status_code == 201, r.text
    assert "prescription" not in await _extra_of(db, r.json()["order_id"])


async def test_a_prescription_sent_when_none_is_needed_is_still_kept(db, tenant_ctx) -> None:
    register_id, variant = await _shop(db, tenant_ctx, flagged=False, capability=False)

    r = await _sell(db, tenant_ctx, register_id, variant, prescription=RX)

    assert r.status_code == 201, r.text
    assert (await _extra_of(db, r.json()["order_id"]))["prescription"] == RX


async def test_a_sale_with_nothing_to_record_leaves_the_order_extra_as_before(
    db, tenant_ctx
) -> None:
    """The ordinary shop's invoices must not grow a key."""
    register_id, variant = await _shop(db, tenant_ctx, flagged=False, capability=False)

    r = await _sell(db, tenant_ctx, register_id, variant)

    assert r.status_code == 201, r.text
    assert set(await _extra_of(db, r.json()["order_id"])) == {"warehouse_id"}


async def test_an_unknown_field_inside_the_prescription_is_refused(db, tenant_ctx) -> None:
    register_id, variant = await _shop(db, tenant_ctx, flagged=True, capability=True)

    r = await _sell(
        db, tenant_ctx, register_id, variant, prescription={**RX, "doctor_license": "x"}
    )

    assert r.status_code == 422, r.text


async def test_the_mark_and_the_reference_helpers() -> None:
    assert is_prescription_only({"prescription_only": True}) is True
    for not_marked in (None, {}, {"prescription_only": False}, {"prescription_only": "true"}):
        assert is_prescription_only(not_marked) is False
    assert clean_reference(None) is None
    assert clean_reference({}) is None
    assert clean_reference({"number": "1", "name": ""}) is None
    assert clean_reference({"number": " 7 ", "name": " ب "}) == {"number": "7", "name": "ب"}


async def test_only_the_prescription_marked_line_of_a_mixed_cart_triggers_it(
    db, tenant_ctx
) -> None:
    register_id, marked = await _shop(db, tenant_ctx, flagged=True, capability=True)
    from tests._pos_helpers import _sellable_variant

    plain = await _sellable_variant(db, tenant_ctx, price="10.00", stock=5)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    body = {
        "items": [
            {"variant_id": str(plain.id), "quantity": 1},
            {"variant_id": str(marked.id), "quantity": 1},
        ]
    }

    refused = await _post(ctx, f"/api/v1/pos/registers/{register_id}/sales", body)
    assert refused.status_code in (400, 422), refused.text

    only_plain = await _post(
        ctx,
        f"/api/v1/pos/registers/{register_id}/sales",
        {"items": [{"variant_id": str(plain.id), "quantity": 1}]},
    )
    assert only_plain.status_code == 201, only_plain.text
