"""The till's search must survive the way people actually type Arabic.

A catalogue is entered once, carefully ("أحمر", "حقيبة", "مِعطف"); it is searched all day, quickly,
on any keyboard ("احمر", "حقيبه", "معطف", digits as ٠١٢). A plain ILIKE answered every one of those
with "no result" for a product that exists. These tests drive the REAL services (the sales grid,
the stock view and the receipt picker) with Arabic-titled rows, so the claim is about what the
cashier sees, not about a helper in isolation.
"""

from __future__ import annotations

import re
import uuid

import pytest

from app.core.sql import arabic_regex, normalize_digits
from app.modules.catalog.service import CatalogService
from app.modules.inventory.service import InventoryService
from app.modules.pos.service import PosService
from app.modules.pos.stock_view import StockViewService
from tests.test_pos_receipt_search import _number, _sale_on_a_closed_shift
from tests.test_pos_returns import _register, _warehouse

# (what the catalogue holds, what a cashier types instead)
SPELLINGS = [
    ("فستان أحمر إيطالي", "احمر"),  # hamza on alef
    ("فستان أحمر إيطالي", "ايطالي"),  # hamza under alef
    ("حقيبة يد جلد", "حقيبه"),  # taa marbuta typed as haa
    ("جاكت شتوي", "شتوى"),  # yaa typed as alef maqsura
    ("مِعطف صوف", "معطف"),  # tashkeel stored, not typed
    ("فستان سهرة", "فُستان"),  # tashkeel typed, not stored
    ("Premium Shirt", "premium"),  # latin case
]


@pytest.mark.parametrize(("stored", "typed"), SPELLINGS)
def test_every_common_spelling_matches_its_stored_word(stored, typed):
    assert re.search(arabic_regex(typed), stored, re.IGNORECASE), (stored, typed)


@pytest.mark.parametrize(
    ("stored", "typed"),
    [("فستان أحمر", "اخضر"), ("حقيبة", "حذاء"), ("axb", "a.b"), ("abc", "a|z")],
)
def test_a_different_word_or_a_regex_character_does_not_match(stored, typed):
    # `.` and `|` typed in a search box are text, never regex syntax.
    assert not re.search(arabic_regex(typed), stored, re.IGNORECASE)


def test_a_typed_regex_metacharacter_is_taken_literally():
    assert re.search(arabic_regex("100%_off"), "sale 100%_off today", re.IGNORECASE)
    assert re.search(arabic_regex("(a+)+"), "x (a+)+ y", re.IGNORECASE)
    assert not re.search(arabic_regex("(a+)+"), "aaaa", re.IGNORECASE)


def test_arabic_indic_and_persian_digits_become_ascii():
    assert normalize_digits("R-٠٠٢٩٩٩") == "R-002999"
    assert normalize_digits("۱۲۳٤٥٦") == "123456"


async def _product(db, tenant_ctx, title, *, sku=None):
    warehouse = await _warehouse(db, tenant_ctx)
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title=title, slug=f"p-{uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.update_product(
        db, tenant_ctx.tenant_id, product.id, status="active"
    )
    variant = await CatalogService.add_variant(
        db,
        tenant_ctx.tenant_id,
        product.id,
        sku=sku or f"SKU-{uuid.uuid4().hex[:8]}",
        price="50.00",
    )
    await InventoryService.move(
        db, tenant_ctx.tenant_id, variant.id, warehouse.id,
        direction="in", quantity=5, reason="purchase",
    )  # fmt: skip
    return variant


async def _open_shift(db, tenant_ctx):
    uid = tenant_ctx.user.id
    register = await _register(db, tenant_ctx)
    return await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, opened_by=uid, cashier_user_id=uid
    )


@pytest.mark.asyncio
async def test_the_sales_grid_finds_a_product_typed_with_a_different_spelling(db, tenant_ctx):
    shift = await _open_shift(db, tenant_ctx)
    red = await _product(db, tenant_ctx, "فستان أحمر إيطالي")
    await _product(db, tenant_ctx, "حذاء رياضي")

    for typed in ("احمر", "ايطالي", "فُستان"):
        page = await PosService.browse(db, tenant_ctx.tenant_id, shift.id, q=typed)
        assert [i["variant_id"] for i in page["items"]] == [str(red.id)], typed
    # And a word that is not there still finds nothing.
    nothing = await PosService.browse(db, tenant_ctx.tenant_id, shift.id, q="اخضر")
    assert nothing["items"] == []


@pytest.mark.asyncio
async def test_the_sales_grid_finds_a_variant_by_its_barcode_fragment(db, tenant_ctx):
    from app.modules.catalog.models import ProductIdentifier

    shift = await _open_shift(db, tenant_ctx)
    variant = await _product(db, tenant_ctx, "قميص")
    await _product(db, tenant_ctx, "بنطلون")
    db.add(
        ProductIdentifier(
            tenant_id=tenant_ctx.tenant_id,
            variant_id=variant.id,
            type="barcode",
            value="6221234567890",
        )
    )
    await db.flush()

    page = await PosService.browse(db, tenant_ctx.tenant_id, shift.id, q="٤٥٦٧٨٩٠")
    assert [i["variant_id"] for i in page["items"]] == [str(variant.id)]


@pytest.mark.asyncio
async def test_the_stock_view_finds_the_same_product_the_same_ways(db, tenant_ctx):
    bag = await _product(db, tenant_ctx, "حقيبة يد جلد")
    await _product(db, tenant_ctx, "حذاء رياضي")
    for typed in ("حقيبه", "جلد", "حَقيبة"):
        rows = await StockViewService.list_stock(db, tenant_ctx.tenant_id, term=typed)
        assert [r["variant_id"] for r in rows] == [str(bag.id)], typed


@pytest.mark.asyncio
async def test_a_receipt_is_found_with_arabic_digits_and_without_the_dash(db, tenant_ctx):
    first, _second, _v, sold = await _sale_on_a_closed_shift(db, tenant_ctx)
    number = await _number(db, tenant_ctx, first.id)
    arabic_digits = number.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
    no_dash = number.replace("-", "")

    for typed in (number, number.lower(), arabic_digits, no_dash):
        found = await PosService.search_receipts(db, tenant_ctx.tenant_id, q=typed)
        assert [r["order_id"] for r in found] == [sold["order_id"]], typed
