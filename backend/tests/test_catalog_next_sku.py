"""The add-product screen asks the server for its next SKU base.

It used to download up to 500 products, with every variant, only to count the highest "SKU-0007" in
the browser. That is the wrong end of the wire: the shop may have thousands of variants, and the
number only matters as a starting point. `GET /products/next-sku` answers with one aggregate query.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.applications.apparel.modules.catalog.service import CatalogService
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


def _body(skus: list[str], **over):
    body = {
        "title": "تيشيرت قطن",
        "slug": f"t-{uuid.uuid4().hex[:10]}",
        "variants": [
            {
                "sku": sku,
                "price": "250.00",
                "option_values": {"color": "أسود", "size": "M"},
                "stock": 0,
            }
            for sku in skus
        ],
    }
    body.update(over)
    return body


async def _next_base(ctx) -> str:
    r = await _call(ctx, "GET", "/api/v1/products/next-sku")
    assert r.status_code == 200, r.text
    return r.json()["base"]


async def test_a_shop_with_no_sku_yet_starts_at_one(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    assert await _next_base(owner) == "SKU-0001"


async def test_the_next_base_follows_the_highest_sku_the_shop_uses(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    made = await _call(
        owner,
        "POST",
        "/api/v1/products/intake",
        _body(["SKU-0003-0101", "SKU-0003-0102"]),
    )
    assert made.status_code == 201, made.text

    assert await _next_base(owner) == "SKU-0004"


async def test_codes_that_are_not_the_shop_series_do_not_move_the_counter(db, tenant_ctx):
    """Imported or vendor codes are numbers too: they must never push SKU- to somewhere absurd."""
    owner = await ctx_for(db, tenant_ctx, "owner")
    made = await _call(
        owner,
        "POST",
        "/api/v1/products/intake",
        _body(["SKU-0002-0101", "ADJ-500297", "UI-BELT-D23D", "6221234567891"]),
    )
    assert made.status_code == 201, made.text

    assert await _next_base(owner) == "SKU-0003"


async def test_it_counts_every_variant_not_the_product_title(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    wh = await _warehouse(db, tenant_ctx)
    first = await _call(
        owner,
        "POST",
        "/api/v1/products/intake",
        _body(["SKU-0010-0101"], warehouse_id=str(wh.id)),
    )
    assert first.status_code == 201, first.text

    assert await _next_base(owner) == "SKU-0011"
    # The service is what the screen talks to; the answer is a plain string, padded to four digits.
    assert await CatalogService.next_sku_base(db, tenant_ctx.tenant_id) == "SKU-0011"
