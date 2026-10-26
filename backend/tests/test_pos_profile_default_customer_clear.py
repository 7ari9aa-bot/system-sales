"""A profile's default customer can be cleared, and leaving the field out changes nothing.

``PATCH /pos/profiles/{id}`` used to read ``default_customer_id: null`` as "not sent", so once a
default walk-in customer was set it could only be swapped, never removed.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.modules.pos.profiles import PosProfileService
from tests._pos_helpers import ctx_for, till
from tests.test_pos_open_day_profile_access import _warehouse
from tests.test_pos_sale_http import _app

pytestmark = pytest.mark.asyncio


async def _profile_with_default(db, tenant_ctx):
    _shift, _variant, customer = await till(db, tenant_ctx)
    wh = await _warehouse(db, tenant_ctx)
    import uuid

    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="بروفايل",
        code=f"D{uuid.uuid4().hex[:6]}",
        warehouse_id=wh.id,
        default_customer_id=customer.id,
        allowed_payment_methods=["cash"],
    )
    return profile, customer


async def _patch(ctx, profile_id, body):
    transport = ASGITransport(app=_app(ctx))
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.patch(f"/api/v1/pos/profiles/{profile_id}", json=body)


async def test_sending_null_clears_the_default_customer(db, tenant_ctx) -> None:
    profile, customer = await _profile_with_default(db, tenant_ctx)
    assert profile.default_customer_id == customer.id
    ctx = await ctx_for(db, tenant_ctx, "owner")
    resp = await _patch(ctx, profile.id, {"default_customer_id": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_customer_id"] is None
    await db.refresh(profile)
    assert profile.default_customer_id is None


async def test_leaving_the_field_out_keeps_the_default_customer(db, tenant_ctx) -> None:
    profile, customer = await _profile_with_default(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    resp = await _patch(ctx, profile.id, {"name": "اسم جديد"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_customer_id"] == str(customer.id)
