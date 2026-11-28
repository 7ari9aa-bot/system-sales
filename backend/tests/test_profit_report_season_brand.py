"""The profit report can be read for one season or one brand.

A season is the owner's own label (SS26, AW26), matched exactly. Without a filter the report is
what it always was; with one it keeps only that season's or brand's models, and the totals follow.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.profit_report import ProfitReportService
from app.applications.apparel.modules.catalog.models import Brand, Product
from tests.test_profit_report import DAY, _sale, _variant, _wh

pytestmark = pytest.mark.asyncio


async def _set(db, product, **fields):
    for k, v in fields.items():
        setattr(product, k, v)
    await db.flush()


async def _report(db, tid, **kw):
    return await ProfitReportService.by_variant(
        db, tid, start=DAY - timedelta(days=1), end=DAY + timedelta(days=1), **kw
    )


async def _brand(db, tid, name):
    b = Brand(tenant_id=tid, name=name)
    db.add(b)
    await db.flush()
    return b


async def _shop(db, tenant_ctx):
    """Two summer shirts of one brand, one winter coat of another, one product with neither."""
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    nile = await _brand(db, tid, "نيل")
    delta = await _brand(db, tid, "دلتا")
    shirt, v1 = await _variant(db, tid, title="قميص صيفي", size="M")
    _, v2 = await _variant(db, tid, title="تيشيرت صيفي", size="L")
    coat, v3 = await _variant(db, tid, title="جاكت شتوي", size="M")
    plain, v4 = await _variant(db, tid, title="حزام", size="M")
    t2 = await db.get(Product, v2.product_id)
    await _set(db, shirt, season="SS26", brand_id=nile.id)
    await _set(db, t2, season="SS26", brand_id=nile.id)
    await _set(db, coat, season="AW26", brand_id=delta.id)
    for v, net in ((v1, "100"), (v2, "200"), (v3, "400"), (v4, "50")):
        await _sale(db, tenant_ctx, wh, v, qty=1, net=net, cost="10")
    return {"nile": nile, "delta": delta}


def _models(rep):
    return sorted(r["model"] for r in rep["rows"])


async def test_without_a_filter_every_sale_is_in_and_each_row_names_its_season_and_brand(
    db, tenant_ctx
) -> None:
    b = await _shop(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id)
    assert _models(rep) == ["تيشيرت صيفي", "جاكت شتوي", "حزام", "قميص صيفي"]
    coat = next(r for r in rep["rows"] if r["model"] == "جاكت شتوي")
    assert coat["season"] == "AW26"
    assert coat["brand_id"] == str(b["delta"].id)
    belt = next(r for r in rep["rows"] if r["model"] == "حزام")
    assert belt["season"] is None and belt["brand_id"] is None
    assert rep["totals"]["revenue"] == "750.00"


async def test_a_season_keeps_only_that_seasons_models_and_the_totals_follow(
    db, tenant_ctx
) -> None:
    await _shop(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id, season="SS26")
    assert _models(rep) == ["تيشيرت صيفي", "قميص صيفي"]
    assert rep["totals"]["revenue"] == "300.00"
    assert rep["totals"]["units_sold"] == 2


async def test_a_brand_keeps_only_that_brands_models(db, tenant_ctx) -> None:
    b = await _shop(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id, brand_id=b["delta"].id)
    assert _models(rep) == ["جاكت شتوي"]
    assert rep["totals"]["revenue"] == "400.00"


async def test_season_and_brand_together_must_both_match(db, tenant_ctx) -> None:
    b = await _shop(db, tenant_ctx)
    both = await _report(db, tenant_ctx.tenant_id, season="SS26", brand_id=b["nile"].id)
    assert _models(both) == ["تيشيرت صيفي", "قميص صيفي"]
    none = await _report(db, tenant_ctx.tenant_id, season="AW26", brand_id=b["nile"].id)
    assert none["rows"] == []
    assert none["totals"]["revenue"] == "0.00"


async def test_a_season_ignores_case_and_outer_spaces_like_the_product_list(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    both = ["تيشيرت صيفي", "قميص صيفي"]
    for typed in ("SS26", "  SS26 ", "ss26", "Ss26"):
        assert _models(await _report(db, tenant_ctx.tenant_id, season=typed)) == both, typed


async def test_a_season_is_not_matched_by_a_part_of_it(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    assert (await _report(db, tenant_ctx.tenant_id, season="SS2"))["rows"] == []
    assert (await _report(db, tenant_ctx.tenant_id, season="SS261"))["rows"] == []


async def test_an_unknown_season_or_brand_is_an_empty_report_not_an_error(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id, season="SS99")
    assert rep["rows"] == []
    rep = await _report(db, tenant_ctx.tenant_id, brand_id=uuid.uuid4())
    assert rep["rows"] == []


async def test_another_shops_report_never_sees_this_shops_brand_or_season(db, tenant_ctx) -> None:
    """Asking another shop's report for this shop's brand id or season finds none of its sales."""
    b = await _shop(db, tenant_ctx)
    elsewhere = uuid.uuid4()
    assert (await _report(db, elsewhere, brand_id=b["nile"].id))["rows"] == []
    assert (await _report(db, elsewhere, season="SS26"))["rows"] == []
    assert (await _report(db, elsewhere))["rows"] == []
