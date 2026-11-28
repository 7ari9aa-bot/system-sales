"""Correcting a wrongly filed scan code over HTTP: who may, and only via its own variant."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.platform.identity.deps import get_db, get_tenant_ctx
from tests._pos_helpers import ctx_for, till

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


async def _file(owner, variant_id, kind, value):
    r = await _call(
        owner,
        "POST",
        f"/api/v1/variants/{variant_id}/identifiers",
        {"identifier_type": kind, "value": value},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_the_owner_corrects_a_code_and_the_till_finds_the_right_one(db, tenant_ctx):
    shift, variant, _ = await till(db, tenant_ctx)
    owner = await ctx_for(db, tenant_ctx, "owner")
    staff = await ctx_for(db, tenant_ctx, "staff")
    wrong = await _file(owner, variant.id, "barcode", "2991000102947")

    gone = await _call(owner, "DELETE", f"/api/v1/variants/{variant.id}/identifiers/{wrong}")
    assert gone.status_code == 204, gone.text
    await _file(owner, variant.id, "ean", "2991000102949")

    scan = f"/api/v1/pos/sessions/{shift.id}/scan"

    def body(value):
        return {"identifier_type": "barcode", "value": value}

    right = await _call(staff, "POST", scan, body("2991000102949"))
    old = await _call(staff, "POST", scan, body("2991000102947"))
    assert right.json()["found"] is True
    assert right.json()["variant_id"] == str(variant.id)
    assert old.json()["found"] is False


async def test_a_cashier_cannot_delete_a_scan_code(db, tenant_ctx):
    _shift, variant, _ = await till(db, tenant_ctx)
    owner = await ctx_for(db, tenant_ctx, "owner")
    staff = await ctx_for(db, tenant_ctx, "staff")
    code = await _file(owner, variant.id, "barcode", "KEEP-ME-1")

    refused = await _call(staff, "DELETE", f"/api/v1/variants/{variant.id}/identifiers/{code}")
    assert refused.status_code == 403
    listed = await _call(owner, "GET", f"/api/v1/variants/{variant.id}/identifiers")
    assert [r["value"] for r in listed.json()] == ["KEEP-ME-1"]


async def test_the_wrong_variant_in_the_url_deletes_nothing(db, tenant_ctx):
    from app.applications.apparel.modules.catalog.services import CatalogService

    _shift, variant, _ = await till(db, tenant_ctx)
    owner = await ctx_for(db, tenant_ctx, "owner")
    code = await _file(owner, variant.id, "barcode", "KEEP-ME-2")
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="تاني", slug="another-one-x"
    )
    other = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="M", price="10.00"
    )

    missed = await _call(owner, "DELETE", f"/api/v1/variants/{other.id}/identifiers/{code}")
    assert missed.status_code == 404
    listed = await _call(owner, "GET", f"/api/v1/variants/{variant.id}/identifiers")
    assert [r["value"] for r in listed.json()] == ["KEEP-ME-2"]
