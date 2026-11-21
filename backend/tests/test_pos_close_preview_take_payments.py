"""The close screen asks for the drawer count only when the server will demand one.

``close_session`` refuses a counted close on a till that does not take payments and refuses an
uncounted one on a till that does. The preview now says which of the two this close is, so the
screen cannot offer the wrong form. The figure is read from the same setting ``close_session``
reads, never stored.
"""

from __future__ import annotations

import pytest

from app.modules.pos.service import PosService
from app.modules.settings.service import SettingsService
from tests.test_pos_close_variance_discipline import _shop

pytestmark = pytest.mark.asyncio


async def test_a_till_that_takes_payments_says_so(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx, payments=True)
    preview = await PosService.close_preview(db, tenant_ctx.tenant_id, shift.id)
    assert preview["take_payments"] is True


async def test_a_till_that_does_not_says_so(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx, payments=False)
    preview = await PosService.close_preview(db, tenant_ctx.tenant_id, shift.id)
    assert preview["take_payments"] is False


async def test_it_follows_the_setting_when_the_owner_changes_it(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx, payments=False)
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set("pos.take_payments", True)
    assert (await PosService.close_preview(db, tenant_ctx.tenant_id, shift.id))[
        "take_payments"
    ] is True
    await svc.set("pos.take_payments", False)
    assert (await PosService.close_preview(db, tenant_ctx.tenant_id, shift.id))[
        "take_payments"
    ] is False


async def test_the_existing_figures_are_still_there(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx, payments=True)
    preview = await PosService.close_preview(db, tenant_ctx.tenant_id, shift.id)
    for key in ("session_id", "status", "closing_balance", "opening_balance", "sales_total"):
        assert key in preview, key
