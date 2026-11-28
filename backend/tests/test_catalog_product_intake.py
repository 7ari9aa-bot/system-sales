"""Creating a whole product in ONE request: one transaction, all of it or none of it.

The add-product screen used to save as a chain: the product, then one request per variant, one per
typed barcode, one per opening balance, then the activation. A 30-variant model meant dozens of
sequential round trips. `POST /products/intake` does the same work inside the request's single
transaction, so the count of requests no longer grows with the number of variants.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.applications.apparel.modules.catalog.service import CatalogService
from app.applications.apparel.modules.catalog.services.variants import ConflictError
from app.modules.identity.deps import get_db, get_tenant_ctx
from tests._pos_helpers import _warehouse, ctx_for

pytestmark = pytest.mark.asyncio


def _app(ctx):
    app = create_app()
    app.user_middleware = [
        m for m in app.user_middleware if m.cls not in {IdempotencyMiddleware, RateLimitMiddleware}
    ]
    app.middleware_stack = None

    async def _session():
        yield ctx.session

    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _session
    return app


async def _call(ctx, method, path, body=None):
    async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as c:
        return await c.request(method, path, json=body)


def _body(**over):
    body = {
        "title": "تيشيرت قطن",
        "slug": f"t-{uuid.uuid4().hex[:10]}",
        "variants": [
            {
                "sku": f"A-{uuid.uuid4().hex[:8]}",
                "price": "250.00",
                "option_values": {"color": "أسود", "size": "M"},
                "stock": 4,
                "auto_barcode": True,
            },
            {
                "sku": f"B-{uuid.uuid4().hex[:8]}",
                "price": "250.00",
                "option_values": {"color": "أسود", "size": "L"},
                "stock": 6,
                "auto_barcode": True,
            },
        ],
    }
    body.update(over)
    return body


async def test_one_request_brings_back_a_sellable_product_with_its_variants(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    wh = await _warehouse(db, tenant_ctx)
    body = _body(warehouse_id=str(wh.id))

    r = await _call(owner, "POST", "/api/v1/products/intake", body)
    assert r.status_code == 201, r.text
    out = r.json()

    assert out["status"] == "active"
    assert [v["option_values"]["size"] for v in out["variants"]] == ["M", "L"]
    # Each variant came back with the shop's own 13-digit code, assigned inside the same request.
    codes = [v["barcode"] for v in out["variants"]]
    assert all(c and len(c) == 13 and c.isdigit() for c in codes), codes
    assert len(set(codes)) == 2

    product = await CatalogService.get_product(db, tenant_ctx.tenant_id, uuid.UUID(out["id"]))
    assert product.status == "active"
    variants = await CatalogService.list_variants(db, tenant_ctx.tenant_id, product.id)
    assert len(variants) == 2


async def test_the_opening_balances_are_in_the_ledger_of_the_named_warehouse(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    wh = await _warehouse(db, tenant_ctx)

    r = await _call(owner, "POST", "/api/v1/products/intake", _body(warehouse_id=str(wh.id)))
    assert r.status_code == 201, r.text
    ids = [v["id"] for v in r.json()["variants"]]

    balances = (await _call(owner, "GET", "/api/v1/inventory/balances")).json()
    on_hand = {b["variant_id"]: b["on_hand"] for b in balances if b["variant_id"] in ids}
    assert on_hand == {ids[0]: 4, ids[1]: 6}


async def test_a_typed_barcode_is_filed_as_given_and_not_replaced(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    body = _body(
        variants=[
            {"sku": f"C-{uuid.uuid4().hex[:8]}", "price": "99.00", "barcode": "6221234567891"},
        ]
    )
    r = await _call(owner, "POST", "/api/v1/products/intake", body)
    assert r.status_code == 201, r.text
    assert r.json()["variants"][0]["barcode"] == "6221234567891"
    assert r.json()["barcodes_assigned"] == 0

    # Filing it is the point: the code must be stored on that exact variant, not just echoed back.
    variant_id = r.json()["variants"][0]["id"]
    filed = await _call(owner, "GET", f"/api/v1/variants/{variant_id}/identifiers")
    assert filed.status_code == 200, filed.text
    rows = filed.json()
    rows = rows if isinstance(rows, list) else rows.get("items", [])
    assert [row["value"] for row in rows] == ["6221234567891"]


async def test_stock_without_a_warehouse_is_refused_before_anything_is_saved(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    slug = f"t-{uuid.uuid4().hex[:10]}"

    r = await _call(owner, "POST", "/api/v1/products/intake", _body(slug=slug, warehouse_id=None))
    assert r.status_code == 400, r.text

    found = await CatalogService.list_products(db, tenant_ctx.tenant_id, limit=500)
    assert [p for p in found if p.slug == slug] == []


async def test_a_variant_that_fails_takes_the_whole_product_down_with_it(db, tenant_ctx):
    """The point of one transaction: no half-saved product that nobody can sell.

    In production the request's own `get_db` opens the transaction and rolls it back when the
    endpoint raises. The test session is already inside the test's transaction, so the rollback
    is proven here with the equivalent savepoint around the endpoint call itself.
    """
    from app.applications.apparel.modules.catalog.routers.products import ProductIntakeRequest, intake_product

    owner = await ctx_for(db, tenant_ctx, "owner")
    slug = f"t-{uuid.uuid4().hex[:10]}"
    twin = f"D-{uuid.uuid4().hex[:8]}"
    body = ProductIntakeRequest(
        **{
            **_body(
                slug=slug,
                variants=[
                    {"sku": twin, "price": "250.00", "stock": 0},
                    {"sku": twin, "price": "250.00", "stock": 0},
                ],
            )
        }
    )

    savepoint = await db.begin_nested()
    with pytest.raises(ConflictError):
        await intake_product(body, owner)
    await savepoint.rollback()

    found = await CatalogService.list_products(db, tenant_ctx.tenant_id, limit=500)
    assert [p for p in found if p.slug == slug] == []


async def test_the_category_brand_season_and_fabric_land_in_the_same_request(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    cat_name = f"فئة-{uuid.uuid4().hex[:6]}"
    brand_name = f"ماركة-{uuid.uuid4().hex[:6]}"
    cat = (await _call(owner, "POST", "/api/v1/categories", {"name": cat_name})).json()
    brand = (await _call(owner, "POST", "/api/v1/brands", {"name": brand_name})).json()

    wh = await _warehouse(db, tenant_ctx)
    r = await _call(
        owner,
        "POST",
        "/api/v1/products/intake",
        _body(
            category_id=cat["id"],
            brand_id=brand["id"],
            season="SS26",
            material="قطن",
            warehouse_id=str(wh.id),
        ),
    )
    assert r.status_code == 201, r.text

    product = await CatalogService.get_product(db, tenant_ctx.tenant_id, uuid.UUID(r.json()["id"]))
    assert str(product.category_id) == cat["id"]
    assert str(product.brand_id) == brand["id"]  # noqa: E501
    assert product.season == "SS26"
    assert product.material == "قطن"


async def test_the_alert_level_the_merchant_typed_is_saved_with_the_variants(db, tenant_ctx):
    """حد التنبيه كان ظاهر في النموذج وبيتبعت للسيرفر ومبيتحفظش: الحقل كان بيترمي في الطلب."""
    from app.applications.apparel.modules.inventory.stock_view import StockLevelService

    owner = await ctx_for(db, tenant_ctx, "owner")
    wh = await _warehouse(db, tenant_ctx)
    body = _body(warehouse_id=str(wh.id))
    body["variants"][0]["reorder_level"] = 5
    body["variants"][1]["reorder_level"] = 0

    r = await _call(owner, "POST", "/api/v1/products/intake", body)
    assert r.status_code == 201, r.text
    ids = [v["id"] for v in r.json()["variants"]]

    levels = [
        await StockLevelService.get_reorder_level(db, tenant_ctx.tenant_id, uuid.UUID(v))
        for v in ids
    ]
    assert levels == [5, 0]


async def test_a_negative_alert_level_is_refused_before_anything_is_saved(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    wh = await _warehouse(db, tenant_ctx)
    body = _body(warehouse_id=str(wh.id))
    body["variants"][0]["reorder_level"] = -1

    r = await _call(owner, "POST", "/api/v1/products/intake", body)
    assert r.status_code == 422, r.text
    assert (
        await db.execute(
            __import__("sqlalchemy").text(
                "select count(*) from products where tenant_id = :t and title = 'تيشيرت قطن'"
            ),
            {"t": tenant_ctx.tenant_id},
        )
    ).scalar_one() == 0


async def test_a_fabric_at_the_limit_is_accepted_and_one_character_more_is_refused(db, tenant_ctx):
    """الخامة كانت 80 في الطلب و60 في الخدمة، فاللي بينهم كان بيعدي الشاشة ويفشل عند الحفظ.

    الحد بقى واحد من catalog/limits.py، فالـAPI بيرفض قبل ما يبدأ أي كتابة، والرسالة واحدة.
    """
    from app.applications.apparel.modules.catalog.limits import MATERIAL_MAX_LENGTH

    owner = await ctx_for(db, tenant_ctx, "owner")
    wh = await _warehouse(db, tenant_ctx)
    longest = "ق" * MATERIAL_MAX_LENGTH
    ok = await _call(
        owner, "POST", "/api/v1/products/intake", _body(material=longest, warehouse_id=str(wh.id))
    )
    assert ok.status_code == 201, ok.text
    saved = await CatalogService.get_product(db, tenant_ctx.tenant_id, uuid.UUID(ok.json()["id"]))
    assert saved.material == longest

    too_long = "ق" * (MATERIAL_MAX_LENGTH + 1)
    refused = await _call(
        owner, "POST", "/api/v1/products/intake", _body(material=too_long, warehouse_id=str(wh.id))
    )
    assert refused.status_code == 422, refused.text
    # ومفيش منتج اتحفظ بالخامة اللي كانت في الطلب المرفوض
    from sqlalchemy import select

    from app.applications.apparel.modules.catalog.models import Product

    rows = (
        await db.execute(
            select(Product).where(
                Product.tenant_id == tenant_ctx.tenant_id, Product.material == too_long
            )
        )
    ).all()
    assert rows == []

    # والخدمة بترفض نفس الطول بنفس الرقم
    from app.applications.apparel.modules.catalog.services.products import _clean_material

    with pytest.raises(ValueError) as exc:
        _clean_material(too_long)
    assert str(MATERIAL_MAX_LENGTH) in str(exc.value)


async def test_the_opening_balance_carries_its_unit_cost(db, tenant_ctx):
    """الإدخال اليدوي كان بيسجل الحركة بلا cost_value، فتقييم المخزون والربح يقرأوا صفر.

    التكلفة اللي التاجر بيدخلها بقت مع الحركة، واللي ميدخلهاش تفضل NULL (مجهولة) مش صفر.
    """
    from decimal import Decimal

    from app.applications.apparel.modules.inventory.models import InventoryMovement

    owner = await ctx_for(db, tenant_ctx, "owner")
    wh = await _warehouse(db, tenant_ctx)
    body = _body(warehouse_id=str(wh.id))
    body["variants"][0]["unit_cost"] = "120.50"
    body["variants"][1].pop("stock")  # بلا رصيد: مفيش حركة خالص

    r = await _call(owner, "POST", "/api/v1/products/intake", body)
    assert r.status_code == 201, r.text
    variant_id = uuid.UUID(r.json()["variants"][0]["id"])

    rows = (
        (
            await db.execute(
                select(InventoryMovement).where(
                    InventoryMovement.tenant_id == tenant_ctx.tenant_id,
                    InventoryMovement.variant_id == variant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].direction == "in"
    assert rows[0].cost_value == Decimal("120.50")


async def test_an_opening_balance_without_a_cost_stays_unknown_not_zero(db, tenant_ctx):
    from app.applications.apparel.modules.inventory.models import InventoryMovement

    owner = await ctx_for(db, tenant_ctx, "owner")
    wh = await _warehouse(db, tenant_ctx)
    r = await _call(owner, "POST", "/api/v1/products/intake", _body(warehouse_id=str(wh.id)))
    assert r.status_code == 201, r.text
    variant_id = uuid.UUID(r.json()["variants"][0]["id"])

    rows = (
        (
            await db.execute(
                select(InventoryMovement).where(
                    InventoryMovement.tenant_id == tenant_ctx.tenant_id,
                    InventoryMovement.variant_id == variant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows and all(m.cost_value is None for m in rows)
