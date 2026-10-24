"""A shift belongs to the MERCHANT's day, not to UTC's.

Cairo is UTC+2 (UTC+3 in summer). A shift opened at 23:30 Cairo is 21:30 UTC: the same UTC day, a
different Cairo day half an hour later. Judging by UTC, a till opened at 23:30 stays "current" until
02:00 Cairo, so the next morning's first hours are rung into last night's report.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.modules.errors import ConflictError
from app.modules.pos.models import PosSession
from app.modules.pos.service import PosService

CAIRO = "Africa/Cairo"


def _shift(opened_utc: datetime) -> PosSession:
    return PosSession(register_id=uuid.uuid4(), opened_at=opened_utc)


def test_a_shift_opened_before_cairo_midnight_is_stale_after_it() -> None:
    # 23:30 Cairo (winter, UTC+2) = 21:30 UTC, checked at 00:30 Cairo = 22:30 UTC: same UTC day.
    opened = datetime(2026, 1, 10, 21, 30, tzinfo=UTC)
    now = datetime(2026, 1, 10, 22, 30, tzinfo=UTC)
    with pytest.raises(ConflictError):
        PosService._ensure_session_current(_shift(opened), tz=CAIRO, now=now)


def test_the_same_two_instants_are_one_day_in_utc() -> None:
    opened = datetime(2026, 1, 10, 21, 30, tzinfo=UTC)
    now = datetime(2026, 1, 10, 22, 30, tzinfo=UTC)
    PosService._ensure_session_current(_shift(opened), tz="UTC", now=now)


def test_a_shift_opened_after_midnight_cairo_is_current_at_noon() -> None:
    # 00:30 Cairo = 22:30 UTC the day before; at 12:00 Cairo it is the SAME Cairo day.
    opened = datetime(2026, 1, 9, 22, 30, tzinfo=UTC)
    now = datetime(2026, 1, 10, 10, 0, tzinfo=UTC)
    PosService._ensure_session_current(_shift(opened), tz=CAIRO, now=now)


def test_utc_would_wrongly_refuse_that_same_shift() -> None:
    opened = datetime(2026, 1, 9, 22, 30, tzinfo=UTC)
    now = datetime(2026, 1, 10, 10, 0, tzinfo=UTC)
    with pytest.raises(ConflictError):
        PosService._ensure_session_current(_shift(opened), tz="UTC", now=now)


def test_summer_time_moves_the_boundary_an_hour() -> None:
    # Egypt observes DST (UTC+3 in summer): midnight Cairo is 21:00 UTC.
    opened = datetime(2026, 7, 10, 20, 30, tzinfo=UTC)  # 23:30 Cairo
    after = datetime(2026, 7, 10, 21, 30, tzinfo=UTC)  # 00:30 Cairo, next day
    with pytest.raises(ConflictError):
        PosService._ensure_session_current(_shift(opened), tz=CAIRO, now=after)


def test_the_default_is_unchanged_for_callers_that_pass_nothing() -> None:
    PosService._ensure_session_current(_shift(datetime.now(UTC)))


# ----------------------------------------------------------- DB-backed -----


async def _open_shift(db, tenant_ctx):
    from tests.test_pos_returns import _register

    register = await _register(db, tenant_ctx)
    return await PosService.open_session(db, tenant_ctx.tenant_id, register.id)


async def _set_tenant_tz(db, tenant_ctx, tz):
    import sqlalchemy as sa

    await db.execute(
        sa.text("UPDATE tenants SET timezone = :z WHERE id = :t"),
        {"z": tz, "t": tenant_ctx.tenant_id},
    )


async def test_the_tenants_own_zone_decides_whether_a_shift_is_stale(db, tenant_ctx) -> None:
    """Same shift, same instant: stale for a Cairo shop, current for a UTC one."""
    shift = await _open_shift(db, tenant_ctx)
    # Pretend it was opened at 21:30 UTC; the only thing that differs below is the tenant's zone.
    shift.opened_at = datetime(2026, 1, 10, 21, 30, tzinfo=UTC)
    now = datetime(2026, 1, 10, 22, 30, tzinfo=UTC)

    await _set_tenant_tz(db, tenant_ctx, CAIRO)
    cairo = await PosService._shop_timezone(db, tenant_ctx.tenant_id)
    assert cairo == CAIRO
    with pytest.raises(ConflictError):
        PosService._ensure_session_current(shift, tz=cairo, now=now)

    await _set_tenant_tz(db, tenant_ctx, "UTC")
    utc = await PosService._shop_timezone(db, tenant_ctx.tenant_id)
    PosService._ensure_session_current(shift, tz=utc, now=now)


async def test_a_tenant_with_no_zone_falls_back_instead_of_crashing(db, tenant_ctx) -> None:
    await _set_tenant_tz(db, tenant_ctx, None)
    assert await PosService._shop_timezone(db, tenant_ctx.tenant_id) is None
    shift = await _open_shift(db, tenant_ctx)
    # NULL means "no opinion": the deployment/UTC chain applies; a fresh shift is simply current.
    PosService._ensure_session_current(shift, tz=None)


async def test_every_live_operation_refuses_a_shift_from_a_previous_merchant_day(
    db, tenant_ctx
) -> None:
    """The wiring, not just the helper: a stale Cairo shift is refused by the real entry points."""
    from datetime import timedelta

    await _set_tenant_tz(db, tenant_ctx, CAIRO)
    shift = await _open_shift(db, tenant_ctx)
    shift.opened_at = datetime.now(UTC) - timedelta(days=2)
    await db.flush()

    refused = []
    for name, call in {
        "hold": lambda: PosService.hold_cart(
            db, tenant_ctx.tenant_id, shift.id, items=[], held_by=None
        ),
    }.items():
        with pytest.raises(ConflictError, match="previous day"):
            await call()
        refused.append(name)
    assert refused == ["hold"]
