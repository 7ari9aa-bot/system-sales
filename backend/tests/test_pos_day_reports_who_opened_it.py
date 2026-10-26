"""A started day reports WHO started it.

A day has no shift holder any more, but the API still has to say whose day it is. It used to answer
only ``cashier_user_id`` -- always empty for a day started without a shift -- so the screen showed
nobody. ``opened_by_user_id`` is the truth for those days.
"""

from __future__ import annotations

import pytest

from app.modules.pos.router import _session_out
from app.modules.pos.service import PosService
from tests._pos_helpers import till

pytestmark = pytest.mark.asyncio


async def test_a_started_day_reports_the_user_who_started_it(db, tenant_ctx) -> None:
    shift, _v, _c = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)
    day = await PosService.open_day(
        db,
        tenant_ctx.tenant_id,
        shift.register_id,
        opening_float="0",
        actor_user_id=tenant_ctx.user.id,
    )
    out = _session_out(day)
    assert out["opened_by_user_id"] == str(tenant_ctx.user.id)
    # With no shift holder, the person shown as the cashier is the one who started the day.
    assert out["cashier_user_id"] == str(tenant_ctx.user.id)
