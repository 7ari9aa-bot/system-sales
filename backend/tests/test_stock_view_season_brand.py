"""The stock screen can be narrowed to one season or one brand, and each row says which it is.

Season is the owner's own label, so SS26, ss26 and ' SS26' are one season (the same rule as the
product list). Brand is matched by id. Without either, every active variant is still listed.
"""

from __future__ import annotations

import uuid

import pytest

from app.applications.apparel.modules.catalog.models import Brand
from app.applications.apparel.modules.pos.stock_view import StockViewService
from tests.test_inventory_stock_view import _variant

pytestmark = pytest.mark.asyncio


async def _brand(db, tenant_ctx, name):
    b = Brand(tenant_id=tenant_ctx.tenant_id, name=name)
    db.add(b)
    await db.flush()
    return b


async def _shop(db, tenant_ctx):
    nile = await _brand(db, tenant_ctx, "نيل")
    delta = await _brand(db, tenant_ctx, "دلتا")
    made = {}
    for key, title, season, brand in (
        ("shirt", "قميص صيفي", "SS26", nile),
        ("tee", "تيشيرت صيفي", "SS26", delta),
        ("coat", "جاكت شتوي", "AW26", delta),
        ("belt", "حزام", None, None),
    ):
        product, variant, _w = await _variant(db, tenant_ctx, stock=5, title=title)
        product.season = season
        product.brand_id = brand.id if brand else None
        made[key] = variant
    await db.flush()
    return {"nile": nile, "delta": delta, **made}


async def _ids(db, tenant_ctx, **kw):
    rows = await StockViewService.list_stock(db, tenant_ctx.tenant_id, **kw)
    return {r["variant_id"] for r in rows}


def _of(shop, *keys):
    return {str(shop[k].id) for k in keys}


async def test_without_a_filter_every_variant_is_listed(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    assert await _ids(db, tenant_ctx) == _of(shop, "shirt", "tee", "coat", "belt")


async def test_a_season_keeps_only_that_seasons_variants(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    assert await _ids(db, tenant_ctx, season="SS26") == _of(shop, "shirt", "tee")
    assert await _ids(db, tenant_ctx, season="AW26") == _of(shop, "coat")


async def test_a_season_ignores_case_and_outer_spaces(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    for typed in ("ss26", "  SS26 ", "Ss26"):
        assert await _ids(db, tenant_ctx, season=typed) == _of(shop, "shirt", "tee"), typed


async def test_a_season_is_not_matched_by_a_part_of_it(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    assert await _ids(db, tenant_ctx, season="SS2") == set()
    assert await _ids(db, tenant_ctx, season="SS261") == set()


async def test_a_blank_season_means_no_filter(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    assert await _ids(db, tenant_ctx, season="   ") == _of(shop, "shirt", "tee", "coat", "belt")


async def test_a_brand_keeps_only_that_brands_variants(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    assert await _ids(db, tenant_ctx, brand_id=shop["delta"].id) == _of(shop, "tee", "coat")
    assert await _ids(db, tenant_ctx, brand_id=shop["nile"].id) == _of(shop, "shirt")


async def test_season_and_brand_together_must_both_match(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    assert await _ids(db, tenant_ctx, season="SS26", brand_id=shop["delta"].id) == _of(shop, "tee")
    assert await _ids(db, tenant_ctx, season="AW26", brand_id=shop["nile"].id) == set()


async def test_they_combine_with_the_other_filters(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    assert await _ids(db, tenant_ctx, season="SS26", term="قميص") == _of(shop, "shirt")
    assert await _ids(db, tenant_ctx, season="SS26", status="out") == set()
    assert await _ids(db, tenant_ctx, season="SS26", status="in") == _of(shop, "shirt", "tee")


async def test_an_unknown_season_or_brand_is_an_empty_list_not_an_error(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    assert await _ids(db, tenant_ctx, season="SS99") == set()
    assert await _ids(db, tenant_ctx, brand_id=uuid.uuid4()) == set()


async def test_each_row_names_its_season_and_brand(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    rows = {r["variant_id"]: r for r in await StockViewService.list_stock(db, tenant_ctx.tenant_id)}
    coat = rows[str(shop["coat"].id)]
    assert coat["season"] == "AW26"
    assert coat["brand_id"] == str(shop["delta"].id)
    belt = rows[str(shop["belt"].id)]
    assert belt["season"] is None and belt["brand_id"] is None


async def test_another_shops_stock_never_matches(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    elsewhere = await StockViewService.list_stock(db, uuid.uuid4(), season="SS26")
    assert elsewhere == []
    elsewhere = await StockViewService.list_stock(db, uuid.uuid4(), brand_id=shop["nile"].id)
    assert elsewhere == []


async def test_the_route_passes_season_and_brand_to_the_read(db, tenant_ctx) -> None:
    """The live route, not just the service: a filter the route drops would do nothing."""
    from app.applications.apparel.modules.pos.router import list_stock
    from tests._pos_helpers import ctx_for

    shop = await _shop(db, tenant_ctx)
    staff = await ctx_for(db, tenant_ctx, "staff")
    rows = await list_stock(staff, season="ss26", brand_id=shop["delta"].id, status=None,
                            term=None, category_id=None, limit=500, offset=0)  # fmt: skip
    assert {r["variant_id"] for r in rows} == _of(shop, "tee")
