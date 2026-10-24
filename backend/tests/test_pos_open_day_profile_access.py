"""Starting the day honours the POS profile's operators, like the old open did.

A profile with NO grants is open to every ``orders:write`` holder. The moment one user is
granted, only its grantees may use it: the general permission alone must not start a day on a
restricted profile.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.errors import ConflictError
from app.modules.pos.profiles import PosProfileService
from app.modules.pos.service import PosService
from tests.test_pos_returns import _register, _warehouse
from tests.test_pos_shift_ownership import _user

pytestmark = pytest.mark.asyncio


async def _register_on_profile(db, tenant_ctx, *, grant_to=None):
    register = await _register(db, tenant_ctx)
    wh = await _warehouse(db, tenant_ctx)
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="مقيّد",
        code=f"R{uuid.uuid4().hex[:6]}",
        warehouse_id=wh.id,
        allowed_payment_methods=["cash"],
    )
    if grant_to is not None:
        await PosProfileService.grant_user(db, tenant_ctx.tenant_id, profile.id, grant_to)
    register.profile_id = profile.id
    await db.flush()
    return register


async def test_a_user_not_granted_on_a_restricted_profile_cannot_start_the_day(
    db, tenant_ctx
) -> None:
    someone_else = await _user(db, "someone-else")
    register = await _register_on_profile(db, tenant_ctx, grant_to=someone_else.id)
    with pytest.raises(ConflictError, match="does not operate"):
        await PosService.open_day(
            db,
            tenant_ctx.tenant_id,
            register.id,
            opening_float="100.00",
            actor_user_id=tenant_ctx.user.id,
        )


async def test_a_granted_user_starts_the_day_and_is_recorded_as_its_opener(db, tenant_ctx) -> None:
    register = await _register_on_profile(db, tenant_ctx, grant_to=tenant_ctx.user.id)
    day = await PosService.open_day(
        db,
        tenant_ctx.tenant_id,
        register.id,
        opening_float="100.00",
        actor_user_id=tenant_ctx.user.id,
    )
    assert day.status == "OPEN"
    assert day.opened_by_user_id == tenant_ctx.user.id


async def test_an_ungranted_profile_stays_open_to_any_writer(db, tenant_ctx) -> None:
    register = await _register_on_profile(db, tenant_ctx)
    day = await PosService.open_day(
        db,
        tenant_ctx.tenant_id,
        register.id,
        opening_float="0.00",
        actor_user_id=tenant_ctx.user.id,
    )
    assert day.status == "OPEN"
