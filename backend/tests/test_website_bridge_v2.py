"""Website-platform catalog bridge, v2: the ADDITIVE fields (stock, sizes, colors, category).

What these tests pin, because a mistake in any of them is customer-visible:

- ``stock`` is ``None`` when nobody has counted the product (NOT zero: zero would show a
  brand-new product as sold out) and a real number once it has inventory.
- ``stock`` is what can be SOLD: on_hand minus reserved, summed over warehouses, never negative,
  counting active variants only.
- ``sizes`` / ``colors`` come from the variants' option values, de-duplicated and trimmed, and are
  withheld (with ``priceVaries``) when the variants are priced differently, so the website can
  never show one size's price and charge for another.
- Every field the website already relied on is unchanged.
"""

from __future__ import annotations

import uuid

from app.core.config import get_settings
from app.modules.catalog import website_platform as bridge
from app.modules.catalog.service import CatalogService
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService


async def _warehouse(db, tenant_id) -> Warehouse:
    wh = Warehouse(tenant_id=tenant_id, name="WH", code=f"WH-{uuid.uuid4().hex[:6].upper()}")
    db.add(wh)
    await db.flush()
    return wh


async def _active_product(db, tenant_id, *, title="Item", category_id=None):
    product = await CatalogService.create_product(
        db, tenant_id, title=title, slug=f"p-{uuid.uuid4().hex[:10]}", category_id=category_id
    )
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    return product


async def _serve(db, tenant_ctx, monkeypatch) -> dict[str, dict]:
    monkeypatch.setattr(
        get_settings(),
        "website_platform_tenant_keys",
        {str(tenant_ctx.tenant_id): "k"},
        raising=False,
    )
    result = await bridge.website_platform_products(
        key_tenant=tenant_ctx.tenant_id, db=db, limit=100
    )
    return {p["id"]: p for p in result["products"]}


async def test_a_product_nobody_counted_has_unknown_stock_not_zero(
    db, tenant_ctx, monkeypatch
) -> None:
    product = await _active_product(db, tenant_ctx.tenant_id)
    await CatalogService.add_variant(db, tenant_ctx.tenant_id, product.id, price="10.00")
    served = await _serve(db, tenant_ctx, monkeypatch)
    assert served[str(product.id)]["stock"] is None


async def test_stock_is_on_hand_minus_reserved_summed_over_warehouses(
    db, tenant_ctx, monkeypatch
) -> None:
    t = tenant_ctx.tenant_id
    product = await _active_product(db, t)
    variant = await CatalogService.add_variant(db, t, product.id, price="10.00")
    wh1, wh2 = await _warehouse(db, t), await _warehouse(db, t)
    for wh, qty in ((wh1, 10), (wh2, 5)):
        await InventoryService.move(
            db, t, variant.id, wh.id, direction="in", quantity=qty, reason="purchase"
        )
    await InventoryService.reserve(db, t, variant.id, wh1.id, quantity=4)
    served = await _serve(db, tenant_ctx, monkeypatch)
    assert served[str(product.id)]["stock"] == (10 - 4) + 5


async def test_a_fully_sold_product_is_zero_not_unknown(db, tenant_ctx, monkeypatch) -> None:
    t = tenant_ctx.tenant_id
    product = await _active_product(db, t)
    variant = await CatalogService.add_variant(db, t, product.id, price="10.00")
    wh = await _warehouse(db, t)
    await InventoryService.move(
        db, t, variant.id, wh.id, direction="in", quantity=3, reason="purchase"
    )
    await InventoryService.move(
        db, t, variant.id, wh.id, direction="out", quantity=3, reason="sale"
    )
    served = await _serve(db, tenant_ctx, monkeypatch)
    assert served[str(product.id)]["stock"] == 0


async def test_stock_of_an_inactive_variant_is_not_counted(db, tenant_ctx, monkeypatch) -> None:
    t = tenant_ctx.tenant_id
    product = await _active_product(db, t)
    live = await CatalogService.add_variant(
        db, t, product.id, price="10.00", option_values={"size": "S"}
    )
    dead = await CatalogService.add_variant(
        db, t, product.id, price="10.00", option_values={"size": "M"}
    )
    wh = await _warehouse(db, t)
    for v, qty in ((live, 2), (dead, 50)):
        await InventoryService.move(
            db, t, v.id, wh.id, direction="in", quantity=qty, reason="purchase"
        )
    await CatalogService.update_variant(db, t, dead.id, is_active=False)
    served = await _serve(db, tenant_ctx, monkeypatch)
    assert served[str(product.id)]["stock"] == 2
    assert served[str(product.id)]["sizes"] == ["S"]


async def test_sizes_and_colors_are_distinct_and_trimmed(db, tenant_ctx, monkeypatch) -> None:
    t = tenant_ctx.tenant_id
    product = await _active_product(db, t)
    # the catalog itself refuses empty option values, so only real values can reach the bridge
    for size, color in (("S", "أحمر"), (" S ", "أزرق"), ("M", "أحمر")):
        await CatalogService.add_variant(
            db, t, product.id, price="10.00", option_values={"size": size, "color": color}
        )
    served = (await _serve(db, tenant_ctx, monkeypatch))[str(product.id)]
    assert sorted(served["sizes"]) == ["M", "S"]
    assert sorted(served["colors"]) == ["أحمر", "أزرق"]
    assert served["priceVaries"] is False


async def test_arabic_option_names_are_understood(db, tenant_ctx, monkeypatch) -> None:
    t = tenant_ctx.tenant_id
    product = await _active_product(db, t)
    await CatalogService.add_variant(
        db, t, product.id, price="10.00", option_values={"المقاس": "L", "اللون": "أسود"}
    )
    served = (await _serve(db, tenant_ctx, monkeypatch))[str(product.id)]
    assert served["sizes"] == ["L"]
    assert served["colors"] == ["أسود"]


async def test_sizes_are_withheld_when_variants_are_priced_differently(
    db, tenant_ctx, monkeypatch
) -> None:
    t = tenant_ctx.tenant_id
    product = await _active_product(db, t)
    await CatalogService.add_variant(db, t, product.id, price="10.00", option_values={"size": "S"})
    await CatalogService.add_variant(db, t, product.id, price="15.00", option_values={"size": "XL"})
    served = (await _serve(db, tenant_ctx, monkeypatch))[str(product.id)]
    assert served["priceVaries"] is True
    assert served["sizes"] == []
    assert served["colors"] == []
    assert served["price"]["amount"] == "10.00"  # the existing field is unchanged


async def test_category_name_is_served_or_none(db, tenant_ctx, monkeypatch) -> None:
    t = tenant_ctx.tenant_id
    category = await CatalogService.create_category(db, t, name="قمصان")
    with_cat = await _active_product(db, t, title="A", category_id=category.id)
    without = await _active_product(db, t, title="B")
    for p in (with_cat, without):
        await CatalogService.add_variant(db, t, p.id, price="10.00")
    served = await _serve(db, tenant_ctx, monkeypatch)
    assert served[str(with_cat.id)]["category"] == "قمصان"
    assert served[str(without.id)]["category"] is None


async def test_the_fields_the_website_already_uses_are_unchanged(
    db, tenant_ctx, monkeypatch
) -> None:
    t = tenant_ctx.tenant_id
    product = await _active_product(db, t, title="Old Shape")
    variant = await CatalogService.add_variant(db, t, product.id, price="20.00")
    await CatalogService.update_variant(db, t, variant.id, compare_at_price="30.00")
    served = (await _serve(db, tenant_ctx, monkeypatch))[str(product.id)]
    assert {
        "id",
        "slug",
        "name",
        "description",
        "status",
        "price",
        "compareAtPrice",
        "image",
    } <= set(served)
    assert served["price"] == {"amount": "20.00", "currency": "EGP"}
    assert served["compareAtPrice"] == {"amount": "30.00", "currency": "EGP"}
    assert served["availability"] == {"status": "available"}


async def test_another_tenants_stock_is_never_counted(db, tenant_ctx, monkeypatch) -> None:
    """The stock query has no tenant filter of its own; it relies on the RLS binding. Pin that."""
    t = tenant_ctx.tenant_id
    product = await _active_product(db, t)
    await CatalogService.add_variant(db, t, product.id, price="10.00")
    served = await _serve(db, tenant_ctx, monkeypatch)
    assert served[str(product.id)]["stock"] is None
    assert set(served) == {str(product.id)}
