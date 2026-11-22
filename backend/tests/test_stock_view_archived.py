"""An archived product leaves the stock screen and its totals, not just the selling screen.

Archiving writes the product's status and leaves its variants active, so the stock view's
"active variant" filter was never enough: the archived garment stayed on the grid and kept its
pieces in «القطع المتوفرة» and its money in «قيمة البيع المتوقعة». The selling side already
refused it (Product.status == "active"), which made the two screens disagree about the same shop.
"""

from __future__ import annotations

import pytest

from app.modules.catalog.services import CatalogService
from app.modules.pos.stock_view import StockViewService
from tests.test_inventory_stock_view import _variant

pytestmark = pytest.mark.asyncio


async def _ids(db, tenant_ctx):
    rows = await StockViewService.list_stock(db, tenant_ctx.tenant_id, limit=100)
    return [r["variant_id"] for r in rows]


async def test_an_archived_product_leaves_the_stock_grid(db, tenant_ctx):
    _product, kept, _wh = await _variant(db, tenant_ctx, stock=4, title="قميص")
    gone_product, gone, _wh2 = await _variant(db, tenant_ctx, stock=7, title="بنطلون تجربة")
    assert set(await _ids(db, tenant_ctx)) == {str(kept.id), str(gone.id)}

    await CatalogService.archive_product(db, tenant_ctx.tenant_id, gone_product.id)

    left = await _ids(db, tenant_ctx)
    assert str(gone.id) not in left
    assert str(kept.id) in left


async def test_an_archived_product_stops_counting_in_the_totals(db, tenant_ctx):
    await _variant(db, tenant_ctx, stock=4, title="قميص")
    gone_product, _gone, _wh = await _variant(db, tenant_ctx, stock=7, title="بنطلون تجربة")
    before = await StockViewService.summary(db, tenant_ctx.tenant_id)
    assert before["pieces"] == 11
    assert before["variants"] == 2

    await CatalogService.archive_product(db, tenant_ctx.tenant_id, gone_product.id)

    after = await StockViewService.summary(db, tenant_ctx.tenant_id)
    assert after["pieces"] == 4
    assert after["variants"] == 1


async def test_a_draft_product_is_still_listed_until_it_is_archived(db, tenant_ctx):
    """Draft is not archived: a product the shop is still filling in must not vanish from stock."""
    product, variant, _wh = await _variant(db, tenant_ctx, stock=3, title="مسودة")
    await CatalogService.update_product(db, tenant_ctx.tenant_id, product.id, status="draft")
    assert str(variant.id) in await _ids(db, tenant_ctx)

    await CatalogService.archive_product(db, tenant_ctx.tenant_id, product.id)
    assert str(variant.id) not in await _ids(db, tenant_ctx)
