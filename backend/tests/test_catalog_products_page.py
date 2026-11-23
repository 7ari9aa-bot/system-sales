"""صفحة المنتجات: البحث والفلترة والترتيب والعدّ على السيرفر، مش على أول 500 في المتصفح."""

from __future__ import annotations

import uuid

import pytest

from app.modules.catalog.service import CatalogService
from tests._pos_helpers import ctx_for
from tests.test_catalog_product_intake import _call

pytestmark = pytest.mark.asyncio


async def _seed(db, tenant_ctx, count=12):
    t = tenant_ctx.tenant_id
    made = []
    for i in range(count):
        product = await CatalogService.create_product(
            db, t, title=f"تيشيرت {i:02d}", slug=f"tee-{uuid.uuid4().hex[:8]}"
        )
        await CatalogService.update_product(db, t, product.id, status="active")
        variant = await CatalogService.add_variant(
            db, t, product.id, sku=f"PAGE-{uuid.uuid4().hex[:6]}", price=100 + i
        )
        made.append((product, variant))
    return made


async def test_a_page_carries_its_rows_and_the_total(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    await _seed(db, tenant_ctx, 12)

    first = await _call(owner, "GET", "/api/v1/products/page?limit=5&offset=0")
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["items"]) == 5
    assert body["total"] == 12
    assert body["has_more"] is True

    last = await _call(owner, "GET", "/api/v1/products/page?limit=5&offset=10")
    body = last.json()
    assert len(body["items"]) == 2
    assert body["has_more"] is False


async def test_the_search_reaches_past_the_first_page(db, tenant_ctx):
    """المنتج رقم 11 مش في أول صفحة، وبحثه لازم يلاقيه: ده بالظبط اللي كان مستحيل."""
    owner = await ctx_for(db, tenant_ctx, "owner")
    made = await _seed(db, tenant_ctx, 12)
    target, variant = made[0]
    await CatalogService.update_product(
        db, tenant_ctx.tenant_id, target.id, title="تيشيرت ZZQ مميز"
    )

    # الكتالوج أكبر من الصفحة اللي الشاشة بتحمّلها، والبحث لازم يلاقي المنتج بره الصفحة دي
    first = (await _call(owner, "GET", "/api/v1/products/page?limit=5")).json()
    assert len(first["items"]) == 5 and first["total"] == 12

    found = await _call(owner, "GET", "/api/v1/products/page?q=ZZQ&limit=5")
    assert [item["id"] for item in found.json()["items"]] == [str(target.id)]

    by_sku = await _call(owner, "GET", f"/api/v1/products/page?q={variant.sku}&limit=5")
    assert [item["id"] for item in by_sku.json()["items"]] == [str(target.id)]


async def test_the_status_filter_and_the_count_agree(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    made = await _seed(db, tenant_ctx, 6)
    archived = made[0][0]
    await CatalogService.update_product(db, tenant_ctx.tenant_id, archived.id, status="archived")

    active = (await _call(owner, "GET", "/api/v1/products/page?status=active&limit=50")).json()
    assert active["total"] == 5
    assert all(item["status"] == "active" for item in active["items"])

    only_archived = (await _call(owner, "GET", "/api/v1/products/page?status=archived")).json()
    assert only_archived["total"] == 1
    assert only_archived["items"][0]["id"] == str(archived.id)


async def test_the_sort_is_applied_on_the_server(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    await _seed(db, tenant_ctx, 4)

    by_name = (await _call(owner, "GET", "/api/v1/products/page?sort=name&limit=50")).json()
    titles = [item["title"] for item in by_name["items"]]
    assert titles == sorted(titles)

    by_name_desc = (
        await _call(owner, "GET", "/api/v1/products/page?sort=name_desc&limit=50")
    ).json()
    assert [item["title"] for item in by_name_desc["items"]] == sorted(titles, reverse=True)


async def test_a_page_never_grows_past_its_ceiling(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    r = await _call(owner, "GET", "/api/v1/products/page?limit=5000")
    assert r.status_code == 200
    assert len(r.json()["items"]) <= 200


async def test_a_typed_percent_or_underscore_is_searched_literally_not_as_a_wildcard(
    db, tenant_ctx
):
    """التاجر بيكتب "50%" أو "a_b": العلامة دي حرف عادي في البحث، مش «أي حاجة»."""
    owner = await ctx_for(db, tenant_ctx, "owner")
    t = tenant_ctx.tenant_id
    for title, slug in (
        ("خصم 50% على الكل", "sale-half"),
        ("تيشيرت عادي", "plain-tee"),
        ("شنطة a_b", "bag-a-underscore-b"),
        ("شنطة aXb", "bag-axb"),
    ):
        p = await CatalogService.create_product(db, t, title=title, slug=slug)
        await CatalogService.update_product(db, t, p.id, status="active")

    percent = await _call(owner, "GET", "/api/v1/products/page?q=50%25&limit=20")
    assert percent.status_code == 200, percent.text
    assert [i["title"] for i in percent.json()["items"]] == ["خصم 50% على الكل"]

    underscore = await _call(owner, "GET", "/api/v1/products/page?q=a_b&limit=20")
    assert [i["title"] for i in underscore.json()["items"]] == ["شنطة a_b"]

    bare = await _call(owner, "GET", "/api/v1/products/page?q=%25&limit=20")
    assert bare.json()["total"] == 1  # only the title that really contains a "%"
