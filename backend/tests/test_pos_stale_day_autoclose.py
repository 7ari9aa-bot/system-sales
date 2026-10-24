"""A day nobody closed is closed by the system WITH its closing balance, like a manual close.

The cashier forgot to close yesterday. The next time the register is asked for "today's" session,
the old one is closed automatically. That close must not lose the figure: the closing balance
(opening balance + invoices - returns) is computed and stored, the ``pos.session.closed`` event is
emitted, and reading the closed session never turns an empty balance into the text "None".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.platform.models import OutboxEvent
from app.modules.pos.router import _session_out
from app.modules.pos.service import PosService
from tests._pos_helpers import till

pytestmark = pytest.mark.asyncio


async def _stale_day_with_one_sale(db, tenant_ctx):
    shift, variant, customer = await till(db, tenant_ctx)
    register = await PosService._get_register(db, tenant_ctx.tenant_id, shift.register_id)
    await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        register.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
        customer_id=customer.id,
        actor_user_id=tenant_ctx.user.id,
    )
    shift.opened_at = datetime.now(UTC) - timedelta(days=2)
    await db.flush()
    return shift, register


async def test_a_forgotten_day_is_closed_with_its_closing_balance(db, tenant_ctx) -> None:
    shift, register = await _stale_day_with_one_sale(db, tenant_ctx)
    expected = (await PosService._day_totals(db, tenant_ctx.tenant_id, shift))["closing_balance"]
    assert expected > shift.opening_float  # the sale is inside the figure

    assert await PosService.working_session(db, tenant_ctx.tenant_id, register.id) is None

    await db.refresh(shift)
    assert shift.status == "CLOSED"
    assert shift.closed_at is not None
    assert shift.expected_cash == expected


async def test_a_forgotten_day_announces_its_close_like_any_other(db, tenant_ctx) -> None:
    shift, register = await _stale_day_with_one_sale(db, tenant_ctx)
    await PosService.working_session(db, tenant_ctx.tenant_id, register.id)

    events = (
        (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_type == "pos_session",
                    OutboxEvent.aggregate_id == shift.id,
                )
            )
        )
        .scalars()
        .all()
    )
    mine = [
        e
        for e in events
        if "pos.session.closed" in e.payload
        and str(e.meta.get("tenant_id")) == str(tenant_ctx.tenant_id)
    ]
    assert len(mine) == 1
    assert Decimal(mine[0].payload["closing_balance"]) == shift.expected_cash
    assert mine[0].payload["invoice_count"] == 1


async def test_a_closed_day_without_a_stored_balance_reads_as_null_not_the_word_none(
    db, tenant_ctx
) -> None:
    """History written by the old auto-close has no balance: it must read as empty, not "None"."""
    shift, _register = await _stale_day_with_one_sale(db, tenant_ctx)
    shift.status = "CLOSED"
    shift.closed_at = datetime.now(UTC)
    shift.expected_cash = None

    assert _session_out(shift)["closing_balance"] is None
