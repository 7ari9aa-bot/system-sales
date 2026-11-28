"""The profit report can be read for one fabric, and each row names its fabric.

A material is the owner's own label (قطن, Cotton), matched whole and without regard to case or
outer spaces. Without a filter the report is what it always was; with one it keeps only that
fabric's models, and the totals follow.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.profit_report import ProfitReportService
from app.applications.apparel.modules.catalog.models import Product
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


async def _shop(db, tenant_ctx):
    """Two cotton shirts (one summer, one winter), one linen shirt, one product with no fabric."""
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    cotton_ss, v1 = await _variant(db, tid, title="قميص قطن صيفي", size="M")
    _, v2 = await _variant(db, tid, title="قميص قطن شتوي", size="L")
    linen, v3 = await _variant(db, tid, title="قميص كتان", size="M")
    _, v4 = await _variant(db, tid, title="حزام", size="M")
    cotton_aw = await db.get(Product, v2.product_id)
    await _set(db, cotton_ss, season="SS26", material="Cotton")
    await _set(db, cotton_aw, season="AW26", material="Cotton")
    await _set(db, linen, season="SS26", material="Linen")
    for v, net in ((v1, "100"), (v2, "200"), (v3, "400"), (v4, "50")):
        await _sale(db, tenant_ctx, wh, v, qty=1, net=net, cost="10")


def _models(rep):
    return sorted(r["model"] for r in rep["rows"])


async def test_without_a_filter_every_sale_is_in_and_each_row_names_its_material(
    db, tenant_ctx
) -> None:
    await _shop(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id)
    assert _models(rep) == ["حزام", "قميص قطن شتوي", "قميص قطن صيفي", "قميص كتان"]
    linen = next(r for r in rep["rows"] if r["model"] == "قميص كتان")
    assert linen["material"] == "Linen"
    belt = next(r for r in rep["rows"] if r["model"] == "حزام")
    assert belt["material"] is None
    assert rep["totals"]["revenue"] == "750.00"


async def test_a_material_keeps_only_that_fabrics_models_and_the_totals_follow(
    db, tenant_ctx
) -> None:
    await _shop(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id, material="Cotton")
    assert _models(rep) == ["قميص قطن شتوي", "قميص قطن صيفي"]
    assert rep["totals"]["revenue"] == "300.00"
    assert rep["totals"]["units_sold"] == 2


async def test_a_material_ignores_case_and_outer_spaces(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    both = ["قميص قطن شتوي", "قميص قطن صيفي"]
    for typed in ("Cotton", "  Cotton ", "cotton", "COTTON"):
        got = await _report(db, tenant_ctx.tenant_id, material=typed)
        assert _models(got) == both, typed


async def test_a_material_is_not_matched_by_a_part_of_it(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    assert (await _report(db, tenant_ctx.tenant_id, material="Cott"))["rows"] == []
    assert (await _report(db, tenant_ctx.tenant_id, material="Cotton1"))["rows"] == []


async def test_material_and_season_together_must_both_match(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    both = await _report(db, tenant_ctx.tenant_id, material="Cotton", season="SS26")
    assert _models(both) == ["قميص قطن صيفي"]
    assert both["totals"]["revenue"] == "100.00"
    none = await _report(db, tenant_ctx.tenant_id, material="Linen", season="AW26")
    assert none["rows"] == []
    assert none["totals"]["revenue"] == "0.00"


async def test_an_unknown_material_is_an_empty_report_not_an_error(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id, material="Silk")
    assert rep["rows"] == []
    assert rep["totals"]["revenue"] == "0.00"


async def test_a_blank_material_filter_is_the_same_as_none_given(db, tenant_ctx) -> None:
    """A text box left empty must not turn into a filter that matches nothing."""
    await _shop(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id, material="")
    assert len(rep["rows"]) == 4


async def test_another_shops_report_never_sees_this_shops_material(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    elsewhere = uuid.uuid4()
    assert (await _report(db, elsewhere, material="Cotton"))["rows"] == []
    assert (await _report(db, elsewhere))["rows"] == []


async def test_the_route_passes_the_material_through_and_each_row_carries_it(
    db, tenant_ctx
) -> None:
    """The service tests cannot see the route: a route that forgot to hand the filter on would
    quietly return everything."""
    from tests.test_pos_close_variance_discipline import MANAGER, _call
    from tests.test_profit_report import _q

    await _shop(db, tenant_ctx)
    everything = await _call(
        db, tenant_ctx, "GET", f"/api/v1/reports/profit/by-variant?{_q()}", perms=MANAGER
    )
    assert everything.status_code == 200, everything.text
    assert len(everything.json()["rows"]) == 4
    only = await _call(
        db,
        tenant_ctx,
        "GET",
        f"/api/v1/reports/profit/by-variant?{_q(material='cotton')}",
        perms=MANAGER,
    )
    assert only.status_code == 200, only.text
    body = only.json()
    assert sorted(r["model"] for r in body["rows"]) == ["قميص قطن شتوي", "قميص قطن صيفي"]
    assert {r["material"] for r in body["rows"]} == {"Cotton"}
    assert body["totals"]["revenue"] == "300.00"
