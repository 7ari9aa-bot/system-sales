"""Reading a till profile (its settings, its granted operators) needs ``orders:read``.

The three read routes only asked for a signed-in tenant user, so any account in the shop,
including one with no POS permission at all, could list the profiles and the names of the people
allowed on a till. Every role that works the till (staff, manager, owner) holds ``orders:read``
and keeps reading; an account without it is refused.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.modules.pos.profiles import PosProfileService
from tests._pos_helpers import ctx_for, till
from tests.test_pos_open_day_profile_access import _warehouse
from tests.test_pos_sale_http import _app

pytestmark = pytest.mark.asyncio


async def _profile(db, tenant_ctx):
    await till(db, tenant_ctx)
    wh = await _warehouse(db, tenant_ctx)
    return await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="بروفايل",
        code=f"R{uuid.uuid4().hex[:6]}",
        warehouse_id=wh.id,
        allowed_payment_methods=["cash"],
    )


async def _get(ctx, path):
    async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as c:
        return await c.get(path)


def _paths(profile_id):
    return [
        "/api/v1/pos/profiles",
        f"/api/v1/pos/profiles/{profile_id}",
        f"/api/v1/pos/profiles/{profile_id}/users",
    ]


@pytest.mark.parametrize("role", ["staff", "manager", "owner"])
async def test_every_till_role_can_read_profiles(db, tenant_ctx, role) -> None:
    profile = await _profile(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, role)
    for path in _paths(profile.id):
        resp = await _get(ctx, path)
        assert resp.status_code == 200, (role, path, resp.text)


async def test_an_account_without_orders_read_is_refused(db, tenant_ctx) -> None:
    profile = await _profile(db, tenant_ctx)
    ctx = dataclasses.replace(
        await ctx_for(db, tenant_ctx, "staff"), role_code="none", permission_codes=set()
    )
    for path in _paths(profile.id):
        resp = await _get(ctx, path)
        assert resp.status_code == 403, (path, resp.status_code, resp.text)
