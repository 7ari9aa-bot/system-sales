"""The stock screen can be narrowed to one fabric, and each row says which it is.

A material is the owner's own label, so Cotton, cotton and ' COTTON ' are one fabric (the same
rule as the season and the product list). Without it every active variant is still listed.
"""

from __future__ import annotations

import pytest

from app.modules.pos.router import StockRow
from app.modules.pos.stock_view import StockViewService
from tests.test_inventory_stock_view import _variant

pytestmark = pytest.mark.asyncio


async def _shop(db, tenant_ctx):
    made = {}
    for key, title, season, material in (
        ("cotton_ss", "قميص قطن صيفي", "SS26", "Cotton"),
        ("cotton_aw", "قميص قطن شتوي", "AW26", "Cotton"),
        ("linen", "قميص كتان", "SS26", "Linen"),
        ("belt", "حزام", None, None),
    ):
        product, variant, _w = await _variant(db, tenant_ctx, stock=5, title=title)
        product.season = season
        product.material = material
        made[key] = variant
    await db.flush()
    return made


async def _ids(db, tenant_ctx, **kw):
    rows = await StockViewService.list_stock(db, tenant_ctx.tenant_id, **kw)
    return {r["variant_id"] for r in rows}


def _of(shop, *keys):
    return {str(shop[k].id) for k in keys}


async def test_without_a_filter_every_variant_is_listed(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    assert await _ids(db, tenant_ctx) == _of(shop, "cotton_ss", "cotton_aw", "linen", "belt")


async def test_a_material_keeps_only_that_fabrics_variants(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    assert await _ids(db, tenant_ctx, material="Cotton") == _of(shop, "cotton_ss", "cotton_aw")
    assert await _ids(db, tenant_ctx, material="Linen") == _of(shop, "linen")


async def test_a_material_ignores_case_and_outer_spaces(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    for typed in ("Cotton", "  Cotton ", "cotton", "COTTON"):
        got = await _ids(db, tenant_ctx, material=typed)
        assert got == _of(shop, "cotton_ss", "cotton_aw"), typed


async def test_a_material_is_not_matched_by_a_part_of_it(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    assert await _ids(db, tenant_ctx, material="Cott") == set()
    assert await _ids(db, tenant_ctx, material="Cotton1") == set()


async def test_a_blank_material_is_no_filter(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    everything = _of(shop, "cotton_ss", "cotton_aw", "linen", "belt")
    assert await _ids(db, tenant_ctx, material="") == everything
    assert await _ids(db, tenant_ctx, material="   ") == everything


async def test_material_and_season_together_must_both_match(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    assert await _ids(db, tenant_ctx, material="Cotton", season="SS26") == _of(shop, "cotton_ss")
    assert await _ids(db, tenant_ctx, material="Linen", season="AW26") == set()


async def test_an_unknown_material_is_an_empty_list_not_an_error(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    assert await _ids(db, tenant_ctx, material="Silk") == set()


async def test_each_row_names_its_material(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    rows = {r["variant_id"]: r for r in await StockViewService.list_stock(db, tenant_ctx.tenant_id)}
    assert rows[str(shop["linen"].id)]["material"] == "Linen"
    assert rows[str(shop["belt"].id)]["material"] is None


async def test_another_shops_stock_never_shows_this_shops_material(db, tenant_ctx) -> None:
    import uuid

    await _shop(db, tenant_ctx)
    rows = await StockViewService.list_stock(db, uuid.uuid4(), material="Cotton")
    assert rows == []


async def test_the_stock_row_the_api_returns_declares_a_material_field() -> None:
    """The route answers through StockRow; a field missing from it would vanish from the reply."""
    assert "material" in StockRow.model_fields
    assert StockRow.model_fields["material"].is_required() is True


async def test_the_route_passes_the_material_through_and_each_row_carries_it(
    db, tenant_ctx
) -> None:
    """The service tests cannot see the route: one that forgot to hand the filter on would
    quietly list everything, and the reply is cut down to the StockRow fields."""
    from tests.test_pos_close_variance_discipline import _call

    shop = await _shop(db, tenant_ctx)
    reader = {"inventory:read"}
    every = await _call(db, tenant_ctx, "GET", "/api/v1/pos/stock", perms=reader)
    assert every.status_code == 200, every.text
    assert len(every.json()) == 4
    only = await _call(db, tenant_ctx, "GET", "/api/v1/pos/stock?material=cotton", perms=reader)
    assert only.status_code == 200, only.text
    rows = only.json()
    assert {r["variant_id"] for r in rows} == _of(shop, "cotton_ss", "cotton_aw")
    assert {r["material"] for r in rows} == {"Cotton"}


async def test_a_material_longer_than_the_limit_is_a_422_on_the_stock_route(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import _call

    r = await _call(
        db,
        tenant_ctx,
        "GET",
        f"/api/v1/pos/stock?material={'x' * 61}",
        perms={"inventory:read"},
    )
    assert r.status_code == 422, r.text
