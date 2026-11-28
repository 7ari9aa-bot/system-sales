"""The colour and size a variant carries, whichever spelling its option_values use.

The product form posts English keys ("color"/"size") while the apparel matrix was written with the
Arabic axis names ("اللون"/"المقاس"). Reading one spelling only meant a garment the shopkeeper added
from the form showed up twice in sell-through with no colour or size, and was dropped from the
matrix grid entirely. These tests pin the tolerant reader on both sides: the plain functions and the
SQL expression the reports select with.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.sell_through_report import SellThroughReportService
from app.applications.apparel.modules.catalog.apparel.matrix import color_of, size_of
from app.applications.apparel.modules.catalog.apparel.service import ApparelMatrixService
from app.applications.apparel.modules.catalog.models import ProductVariant
from app.applications.apparel.modules.catalog.service import CatalogService
from app.applications.apparel.modules.inventory.service import InventoryService
from tests.test_profit_report import DAY, _sale, _wh

ARABIC = {"المقاس": "M", "اللون": "أسود"}
ENGLISH = {"size": "M", "color": "أسود"}


def test_both_spellings_read_the_same_size_and_colour():
    for opts in (ARABIC, ENGLISH):
        assert size_of(opts) == "M"
        assert color_of(opts) == "أسود"


def test_a_blank_or_missing_axis_is_none_not_an_empty_string():
    assert size_of({"size": "   ", "color": "أسود"}) is None
    assert color_of({}) is None
    assert size_of(None) is None


def test_a_non_string_value_is_read_as_text():
    # A shop that posted a number ("42") should not lose the size.
    assert size_of({"size": 42}) == "42"


def test_arabic_wins_when_a_variant_carries_both_spellings():
    # The matrix's own names are authoritative if a variant ever has both.
    assert size_of({"المقاس": "L", "size": "M"}) == "L"
    assert color_of({"اللون": "أبيض", "color": "أسود"}) == "أبيض"


async def _variant_with(db, tid, opts):
    prod = await CatalogService.create_product(
        db, tid, title="قميص", slug=f"p-{uuid.uuid4().hex[:8]}"
    )
    return await CatalogService.add_variant(db, tid, prod.id, price="100.00", option_values=opts)


@pytest.mark.asyncio
async def test_a_variant_added_with_english_keys_reaches_sell_through(db, tenant_ctx):
    """The report must name its colour and size, not show the same garment twice with a blank."""
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    variant = await _variant_with(db, tid, ENGLISH)
    await InventoryService.move(
        db, tid, variant.id, wh.id, direction="in", quantity=6, reason="purchase"
    )
    await _sale(db, tenant_ctx, wh, variant, qty=2, net="200", cost="20")

    rep = await SellThroughReportService.by_variant(
        db, tid, start=DAY - timedelta(days=1), end=DAY + timedelta(days=1)
    )
    mine = [r for r in rep["rows"] if r["variant_id"] == str(variant.id)]
    assert len(mine) == 1, rep["rows"]
    assert mine[0]["size"] == "M"
    assert mine[0]["colour"] == "أسود"
    assert mine[0]["units_sold"] == 2


@pytest.mark.asyncio
async def test_the_matrix_grid_keeps_a_variant_added_with_english_keys(db, tenant_ctx):
    """The grid used to `continue` past it, so the garment had no cells at all."""
    tid = tenant_ctx.tenant_id
    product = await CatalogService.create_product(db, tid, title="تيشيرت", slug="p-mixed-keys")
    await CatalogService.add_variant(db, tid, product.id, price="100.00", option_values=ENGLISH)

    grid = await ApparelMatrixService.view(db, tid, product.id)
    cells = [c for row in grid["cells"].values() for c in row.values()]
    assert len(cells) == 1, grid
    assert "M" in grid["sizes"]
    assert "أسود" in grid["colors"]


@pytest.mark.asyncio
async def test_the_sql_reader_sees_english_keys_too(db, tenant_ctx):
    """Reports select the axis in SQL; a coalesce over both spellings must find it."""
    from app.applications.apparel.modules.catalog.apparel.matrix import size_column

    tid = tenant_ctx.tenant_id
    variant = await _variant_with(db, tid, ENGLISH)
    rows = (
        (
            await db.execute(
                select(size_column(ProductVariant.option_values)).where(
                    ProductVariant.id == variant.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == ["M"]
