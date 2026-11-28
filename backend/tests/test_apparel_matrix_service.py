"""Writing and reading a garment's size x colour matrix on a real database."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.applications.apparel.modules.catalog.apparel.matrix import COLOR_AXIS, SIZE_AXIS
from app.applications.apparel.modules.catalog.apparel.service import ApparelMatrixService as M
from app.applications.apparel.modules.catalog.models import ProductOption, ProductVariant, ProductVariantOptionValue
from app.applications.apparel.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.applications.apparel.modules.inventory.service import InventoryService
from tests.test_pos_returns import _warehouse

pytestmark = pytest.mark.asyncio


async def _garment(db, tenant_ctx):
    return await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="قميص", slug=f"s-{uuid.uuid4().hex[:10]}"
    )


async def _count(db, tenant_ctx, product_id) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(ProductVariant)
            .where(
                ProductVariant.tenant_id == tenant_ctx.tenant_id,
                ProductVariant.product_id == product_id,
            )
        )
    ).scalar_one()


async def test_it_creates_every_combination_with_the_option_graph_filled(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    product = await _garment(db, tenant_ctx)
    result = await M.generate(
        db,
        t,
        product.id,
        sizes=["S", "M", "L"],
        colors=["أسود", "أبيض"],
        price="250.00",
        sku_prefix="SH24",
    )
    assert len(result.created) == 6 and result.skipped == []
    # the relational graph is written too, not just the JSON: one link per axis per variant
    links = (
        await db.execute(
            select(func.count())
            .select_from(ProductVariantOptionValue)
            .where(ProductVariantOptionValue.tenant_id == t)
        )
    ).scalar_one()
    assert links == 12
    axes = (
        (await db.execute(select(ProductOption.name).where(ProductOption.product_id == product.id)))
        .scalars()
        .all()
    )
    assert sorted(axes) == sorted([SIZE_AXIS, COLOR_AXIS])


async def test_adding_a_colour_later_leaves_the_existing_variants_alone(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    product = await _garment(db, tenant_ctx)
    first = await M.generate(
        db, t, product.id, sizes=["S", "M"], colors=["أسود"], price="100", sku_prefix="SH"
    )
    old_ids = {v.id for v in first.created}
    # a new colour, with a different price: the old rows must keep theirs
    again = await M.generate(
        db, t, product.id, sizes=["S", "M"], colors=["أسود", "أحمر"], price="999", sku_prefix="SH"
    )
    assert len(again.created) == 2 and len(again.skipped) == 2
    assert await _count(db, tenant_ctx, product.id) == 4
    kept = (
        (await db.execute(select(ProductVariant).where(ProductVariant.id.in_(old_ids))))
        .scalars()
        .all()
    )
    from decimal import Decimal

    assert {Decimal(str(v.price)) for v in kept} == {Decimal("100")}


async def test_running_it_twice_changes_nothing(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    product = await _garment(db, tenant_ctx)
    args = {"sizes": ["M", "L"], "colors": ["x"], "price": "10", "sku_prefix": "P"}
    await M.generate(db, t, product.id, **args)
    second = await M.generate(db, t, product.id, **args)
    assert second.created == [] and len(second.skipped) == 2
    assert await _count(db, tenant_ctx, product.id) == 2


async def test_a_sku_owned_by_another_garment_refuses_everything(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    a = await _garment(db, tenant_ctx)
    b = await _garment(db, tenant_ctx)
    await M.generate(db, t, a.id, sizes=["M"], colors=["أسود"], price="10", sku_prefix="SH")
    with pytest.raises(ConflictError):
        # same prefix and colour: the M variant would clash, and S and L must not be left behind
        await M.generate(
            db, t, b.id, sizes=["S", "M", "L"], colors=["أسود"], price="10", sku_prefix="SH"
        )
    assert await _count(db, tenant_ctx, b.id) == 0


async def test_an_unknown_product_and_bad_input_write_nothing(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    with pytest.raises(NotFoundError):
        await M.generate(db, t, uuid.uuid4(), sizes=["M"], colors=["x"], price="1", sku_prefix="P")
    product = await _garment(db, tenant_ctx)
    with pytest.raises(ValidationError):
        await M.generate(db, t, product.id, sizes=[], colors=["x"], price="1", sku_prefix="P")
    with pytest.raises(ValidationError):
        await M.generate(db, t, product.id, sizes=["M"], colors=["x"], price="-5", sku_prefix="P")
    assert await _count(db, tenant_ctx, product.id) == 0


async def test_the_grid_shows_stock_per_cell_and_marks_gaps(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    warehouse = await _warehouse(db, tenant_ctx)
    product = await _garment(db, tenant_ctx)
    made = await M.generate(
        db,
        t,
        product.id,
        sizes=["L", "S", "M"],
        colors=["أسود", "أبيض"],
        price="100",
        sku_prefix="G",
    )
    by_sku = {v.sku: v for v in made.created}
    await InventoryService.move(
        db, t, by_sku["G-أسو-M"].id, warehouse.id, direction="in", quantity=7, reason="purchase"
    )
    await InventoryService.move(
        db, t, by_sku["G-أبي-S"].id, warehouse.id, direction="in", quantity=3, reason="purchase"
    )
    grid = await M.view(db, t, product.id)
    assert grid["sizes"] == ["S", "M", "L"]  # rack order, not the order they were typed
    assert grid["colors"] == ["أسود", "أبيض"]
    assert grid["cells"]["أسود"]["M"]["available"] == 7
    assert grid["cells"]["أبيض"]["S"]["available"] == 3
    assert grid["cells"]["أسود"]["L"]["available"] == 0  # created, nothing in stock
    assert grid["total_available"] == 10


async def test_a_reserved_unit_is_not_available_on_the_grid(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    warehouse = await _warehouse(db, tenant_ctx)
    product = await _garment(db, tenant_ctx)
    made = await M.generate(
        db, t, product.id, sizes=["M"], colors=["x"], price="10", sku_prefix="R"
    )
    variant = made.created[0]
    await InventoryService.move(
        db, t, variant.id, warehouse.id, direction="in", quantity=5, reason="purchase"
    )
    await InventoryService.reserve(db, t, variant.id, warehouse.id, quantity=2)
    grid = await M.view(db, t, product.id)
    assert grid["cells"]["x"]["M"]["available"] == 3


async def test_a_plain_one_size_variant_is_not_forced_onto_the_grid(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    product = await _garment(db, tenant_ctx)
    await CatalogService.add_variant(db, t, product.id, title="فري سايز", price="50")
    await M.generate(db, t, product.id, sizes=["M"], colors=["x"], price="10", sku_prefix="Q")
    grid = await M.view(db, t, product.id)
    assert grid["colors"] == ["x"] and grid["sizes"] == ["M"]


async def test_one_shop_cannot_build_on_anothers_garment(db, tenant_ctx) -> None:
    product = await _garment(db, tenant_ctx)
    with pytest.raises(NotFoundError):
        await M.generate(
            db, uuid.uuid4(), product.id, sizes=["M"], colors=["x"], price="1", sku_prefix="P"
        )


async def test_availability_applies_the_quarantine_and_reservation_rules(db, tenant_ctx) -> None:
    from app.applications.apparel.modules.inventory.service import InventoryService as Inv

    t = tenant_ctx.tenant_id
    warehouse = await _warehouse(db, tenant_ctx)
    product = await _garment(db, tenant_ctx)
    made = await M.generate(
        db, t, product.id, sizes=["M", "L"], colors=["x"], price="10", sku_prefix="AV"
    )
    m_var, l_var = made.created
    await Inv.move(db, t, m_var.id, warehouse.id, direction="in", quantity=10, reason="purchase")
    await Inv.reserve(db, t, m_var.id, warehouse.id, quantity=3)
    got = await Inv.available_for_many(db, t, [m_var.id, l_var.id, uuid.uuid4()])
    assert got[m_var.id] == 7  # 10 on hand - 3 held for an order
    assert l_var.id not in got  # never stocked: absent, the caller reads that as 0
    assert await Inv.available_for_many(db, t, []) == {}


async def test_one_shop_never_sees_anothers_stock_levels(db, tenant_ctx) -> None:
    from app.applications.apparel.modules.inventory.service import InventoryService as Inv

    t = tenant_ctx.tenant_id
    warehouse = await _warehouse(db, tenant_ctx)
    product = await _garment(db, tenant_ctx)
    made = await M.generate(
        db, t, product.id, sizes=["M"], colors=["x"], price="10", sku_prefix="TN"
    )
    await Inv.move(
        db, t, made.created[0].id, warehouse.id, direction="in", quantity=4, reason="purchase"
    )
    assert await Inv.available_for_many(db, uuid.uuid4(), [made.created[0].id]) == {}
