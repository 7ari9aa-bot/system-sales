"""The business date of a closed day is the MERCHANT's calendar day, not UTC's.

Cairo is UTC+2 in winter. A close at 23:30 Cairo is 21:30 UTC: the same date, nothing moves. A
close at 00:30 Cairo is 22:30 UTC of the day BEFORE: the shop is already on the new day, but a UTC
date still calls it the old one. The close event, the projection rebuild and the daily report must
all agree on the Cairo date.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.modules.identity.models import Tenant
from app.modules.platform.models import OutboxEvent
from app.modules.pos.models import PosDailySales, PosSession
from app.modules.pos.service import PosService
from tests._pos_helpers import till

pytestmark = pytest.mark.asyncio


async def _closed_day_at(db, tenant_ctx, closed_at_utc: datetime, tz: str | None):
    """A day with one recorded sale, closed, then stamped as closed at the given UTC instant."""
    await db.execute(update(Tenant).where(Tenant.id == tenant_ctx.tenant_id).values(timezone=tz))
    shift, variant, customer = await till(db, tenant_ctx)
    register = await PosService._get_register(db, tenant_ctx.tenant_id, shift.register_id)
    await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        register.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        customer_id=customer.id,
        actor_user_id=tenant_ctx.user.id,
    )
    return shift, closed_at_utc


async def _event_date(db, tenant_ctx, session_id) -> str:
    events = (
        (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_type == "pos_session",
                    OutboxEvent.aggregate_id == session_id,
                )
            )
        )
        .scalars()
        .all()
    )
    mine = [e for e in events if "pos.session.closed" in e.payload]
    assert len(mine) == 1
    return mine[0].payload["business_date"]


async def test_a_close_just_after_cairo_midnight_belongs_to_the_new_cairo_day(
    db, tenant_ctx, monkeypatch
) -> None:
    """00:30 Cairo (UTC+2) is 22:30 UTC the day before: the shop's day is the 25th, not the 24th."""
    shift, _ = await _closed_day_at(
        db, tenant_ctx, datetime(2026, 11, 24, 22, 30, tzinfo=UTC), "Africa/Cairo"
    )
    instant = datetime(2026, 11, 24, 22, 30, tzinfo=UTC)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr("app.modules.pos.service.datetime", _Frozen)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id, closed_by=tenant_ctx.user.id)

    assert await _event_date(db, tenant_ctx, shift.id) == "2026-11-25"

    # The rebuild finds the day under the SAME date, and not under the UTC one.
    written = await PosService.upsert_daily_projection(
        db, tenant_ctx.tenant_id, business_date=date(2026, 11, 25)
    )
    assert written == 1
    assert (
        await PosService.upsert_daily_projection(
            db, tenant_ctx.tenant_id, business_date=date(2026, 11, 24)
        )
        == 0
    )
    row = (
        await db.execute(
            select(PosDailySales).where(PosDailySales.tenant_id == tenant_ctx.tenant_id)
        )
    ).scalar_one()
    assert row.business_date == date(2026, 11, 25)
    assert Decimal(str(row.sales_total)) == Decimal("100.00")


async def test_a_close_before_cairo_midnight_stays_on_the_same_day(
    db, tenant_ctx, monkeypatch
) -> None:
    """23:30 Cairo is 21:30 UTC: same date either way, so nothing moves for the ordinary evening."""
    shift, _ = await _closed_day_at(
        db, tenant_ctx, datetime(2026, 11, 24, 21, 30, tzinfo=UTC), "Africa/Cairo"
    )
    instant = datetime(2026, 11, 24, 21, 30, tzinfo=UTC)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr("app.modules.pos.service.datetime", _Frozen)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id, closed_by=tenant_ctx.user.id)
    assert await _event_date(db, tenant_ctx, shift.id) == "2026-11-24"


async def test_a_shop_with_no_timezone_keeps_counting_in_utc(db, tenant_ctx, monkeypatch) -> None:
    shift, _ = await _closed_day_at(
        db, tenant_ctx, datetime(2026, 11, 24, 22, 30, tzinfo=UTC), None
    )
    instant = datetime(2026, 11, 24, 22, 30, tzinfo=UTC)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr("app.modules.pos.service.datetime", _Frozen)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id, closed_by=tenant_ctx.user.id)
    assert await _event_date(db, tenant_ctx, shift.id) == "2026-11-24"
    assert (
        await db.execute(select(PosSession.status).where(PosSession.id == shift.id))
    ).scalar_one() == "CLOSED"


async def test_the_backfill_moves_a_misfiled_day_to_the_shop_date(
    db, tenant_ctx, monkeypatch
) -> None:
    """A row the OLD code filed under the UTC date is rewritten under the Cairo date, once."""
    shift, _ = await _closed_day_at(
        db, tenant_ctx, datetime(2026, 11, 24, 22, 30, tzinfo=UTC), "Africa/Cairo"
    )
    instant = datetime(2026, 11, 24, 22, 30, tzinfo=UTC)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr("app.modules.pos.service.datetime", _Frozen)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id, closed_by=tenant_ctx.user.id)
    tid = tenant_ctx.tenant_id

    # What the old code left behind: the day filed under the UTC date (the 24th), not the 25th.
    await PosService.upsert_daily_projection(db, tid, business_date=date(2026, 11, 25))
    await db.execute(
        update(PosDailySales)
        .where(PosDailySales.tenant_id == tid)
        .values(business_date=date(2026, 11, 24))
    )
    await db.flush()

    import importlib.util
    import sys
    from pathlib import Path

    scripts = Path(__file__).resolve().parent.parent / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(
        "backfill_pos_daily_sales_under_test", scripts / "backfill_pos_daily_sales.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _plan = module._plan

    wanted, held = await _plan(db, tid, "Africa/Cairo")
    assert wanted == {date(2026, 11, 25)}
    assert held == {date(2026, 11, 24)}

    for day in sorted(held | wanted):
        await PosService.upsert_daily_projection(db, tid, business_date=day)
    rows = (
        (await db.execute(select(PosDailySales).where(PosDailySales.tenant_id == tid)))
        .scalars()
        .all()
    )
    assert [r.business_date for r in rows] == [date(2026, 11, 25)]
    assert Decimal(str(rows[0].sales_total)) == Decimal("100.00")

    # A second run changes nothing (the rebuild is recomputed, never incremented).
    wanted, held = await _plan(db, tid, "Africa/Cairo")
    assert wanted == held == {date(2026, 11, 25)}
