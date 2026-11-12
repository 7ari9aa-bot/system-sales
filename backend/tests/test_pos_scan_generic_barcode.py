"""A generic `barcode` scan finds a code registered as ean/gtin/upc.

Found by scanning over HTTP: the till always sends ``identifier_type: "barcode"``, but packaged
products are registered as ``ean``. The exact-type lookup returned ``found: false`` for them.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.modules.identity.deps import get_db, get_tenant_ctx
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


async def _call(ctx, method, path, body):
    async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as c:
        return await c.request(method, path, json=body)


async def _register(owner, variant_id, kind, value):
    r = await _call(
        owner,
        "POST",
        f"/api/v1/variants/{variant_id}/identifiers",
        {"identifier_type": kind, "value": value},
    )
    assert r.status_code == 201, r.text


async def _scan(staff, session_id, kind, value):
    r = await _call(
        staff,
        "POST",
        f"/api/v1/pos/sessions/{session_id}/scan",
        {"identifier_type": kind, "value": value},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("registered_as", ["ean", "gtin", "upc"])
async def test_generic_barcode_scan_finds_a_packaged_code(db, tenant_ctx, registered_as) -> None:
    shift, variant, _ = await till(db, tenant_ctx)
    owner = await ctx_for(db, tenant_ctx, "owner")
    staff = await ctx_for(db, tenant_ctx, "staff")
    await _register(owner, variant.id, registered_as, "6221234567890")

    found = await _scan(staff, shift.id, "barcode", "6221234567890")

    assert found["found"] is True
    assert found["variant_id"] == str(variant.id)


async def test_a_specific_type_stays_exact(db, tenant_ctx) -> None:
    shift, variant, _ = await till(db, tenant_ctx)
    owner = await ctx_for(db, tenant_ctx, "owner")
    staff = await ctx_for(db, tenant_ctx, "staff")
    await _register(owner, variant.id, "ean", "6221234567890")

    assert (await _scan(staff, shift.id, "upc", "6221234567890"))["found"] is False
    assert (await _scan(staff, shift.id, "ean", "6221234567890"))["found"] is True


async def test_a_code_registered_as_barcode_still_wins_and_unknown_is_not_found(
    db, tenant_ctx
) -> None:
    shift, variant, _ = await till(db, tenant_ctx)
    owner = await ctx_for(db, tenant_ctx, "owner")
    staff = await ctx_for(db, tenant_ctx, "staff")
    await _register(owner, variant.id, "barcode", "LOCAL-001")

    assert (await _scan(staff, shift.id, "barcode", "LOCAL-001"))["found"] is True
    assert (await _scan(staff, shift.id, "barcode", "NOPE-404"))["found"] is False
