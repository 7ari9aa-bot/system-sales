"""Who held how much cash, and how far off each cashier's drawers were.

One row per cashier over a period, built only from the closed shifts that counted their drawer.
A shift that never counted (the till did not take payments) has no cash to account for, so it is
left out of every money figure instead of being read as a zero.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.applications.apparel.modules.pos.models import PosSession
from app.applications.apparel.modules.pos.service import PosService

pytestmark = pytest.mark.asyncio

D = Decimal
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


async def _user(db):
    """A real user row: a shift's cashier is a foreign key, so a random uuid is refused."""
    from app.core.security import hash_password
    from app.modules.identity.models import User

    u = User(
        email=f"c-{uuid.uuid4().hex[:8]}@test.local",
        password_hash=hash_password("x-secret-pw"),
        full_name="Cashier",
    )
    db.add(u)
    await db.flush()
    return u.id


async def _shift(db, ctx, cashier, *, expected, counted, closed_at=NOW, reason=None, approved=None):
    """A closed shift written the way close_session leaves it."""
    from tests._pos_helpers import _register

    reg = await _register(db, ctx)
    s = PosSession(
        tenant_id=ctx.tenant_id,
        register_id=reg.id,
        status="CLOSED",
        opening_float=D("0"),
        cashier_user_id=cashier,
        opened_at=closed_at - timedelta(hours=8),
        closed_at=closed_at,
        expected_cash=None if expected is None else D(expected),
        counted_cash=None if counted is None else D(counted),
        variance=None if counted is None else D(counted) - D(expected),
        variance_reason=reason,
        variance_approved_by_user_id=approved,
    )
    db.add(s)
    await db.flush()
    return s


async def _report(db, tid, **kw):
    return await PosService.cashier_custody(
        db,
        tid,
        start=kw.get("start", NOW - timedelta(days=1)),
        end=kw.get("end", NOW + timedelta(days=1)),
    )


async def test_a_cashier_with_no_closed_shift_is_not_listed(db, tenant_ctx) -> None:
    assert await _report(db, tenant_ctx.tenant_id) == []


async def test_one_row_per_cashier_with_totals_and_split_shortage_and_overage(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    a, b = await _user(db), await _user(db)
    await _shift(db, tenant_ctx, a, expected="200", counted="190", reason="ناقص")
    await _shift(db, tenant_ctx, a, expected="300", counted="305", reason="زيادة")
    await _shift(db, tenant_ctx, a, expected="100", counted="100")
    await _shift(db, tenant_ctx, b, expected="50", counted="50")
    rows = {r["cashier_user_id"]: r for r in await _report(db, tid)}
    ra = rows[str(a)]
    assert ra["shifts"] == 3
    assert ra["expected_cash"] == "600.00"
    assert ra["counted_cash"] == "595.00"
    assert ra["net_variance"] == "-5.00"
    assert ra["shortage_total"] == "10.00"
    assert ra["overage_total"] == "5.00"
    assert ra["shifts_with_variance"] == 2
    assert rows[str(b)]["shifts_with_variance"] == 0


async def test_a_shift_that_never_counted_is_left_out_of_the_money(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    a = await _user(db)
    await _shift(db, tenant_ctx, a, expected="200", counted="200")
    await _shift(db, tenant_ctx, a, expected=None, counted=None)
    ra = (await _report(db, tid))[0]
    assert ra["shifts"] == 2
    assert ra["counted_shifts"] == 1
    assert ra["expected_cash"] == "200.00"


async def test_a_shift_with_no_cashier_is_grouped_under_none(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _shift(db, tenant_ctx, None, expected="10", counted="10")
    rows = await _report(db, tid)
    assert [r["cashier_user_id"] for r in rows] == [None]


async def test_approved_gaps_are_counted(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    a, boss = await _user(db), tenant_ctx.user.id
    await _shift(db, tenant_ctx, a, expected="200", counted="150", reason="x", approved=boss)
    await _shift(db, tenant_ctx, a, expected="200", counted="190", reason="y")
    assert (await _report(db, tid))[0]["approved_variances"] == 1


async def test_only_shifts_closed_inside_the_period_count(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    a = await _user(db)
    await _shift(db, tenant_ctx, a, expected="100", counted="100", closed_at=NOW)
    await _shift(
        db, tenant_ctx, a, expected="100", counted="100", closed_at=NOW - timedelta(days=10)
    )
    r = await _report(db, tid, start=NOW - timedelta(days=1), end=NOW + timedelta(days=1))
    assert r[0]["shifts"] == 1


async def test_the_period_start_is_inclusive_and_the_end_exclusive(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    a = await _user(db)
    await _shift(db, tenant_ctx, a, expected="100", counted="100", closed_at=NOW)
    assert (await _report(db, tid, start=NOW, end=NOW + timedelta(hours=1)))[0]["shifts"] == 1
    assert await _report(db, tid, start=NOW - timedelta(hours=1), end=NOW) == []


async def test_a_shift_still_open_is_not_reported(db, tenant_ctx) -> None:
    from tests._pos_helpers import till

    await till(db, tenant_ctx)
    assert await _report(db, tenant_ctx.tenant_id) == []


async def test_another_shops_shifts_are_never_included(db, tenant_ctx) -> None:
    await _shift(db, tenant_ctx, await _user(db), expected="100", counted="100")
    assert await _report(db, uuid.uuid4()) == []


async def test_an_inverted_period_is_refused(db, tenant_ctx) -> None:
    from app.core.errors import ValidationError

    with pytest.raises(ValidationError):
        await PosService.cashier_custody(
            db, tenant_ctx.tenant_id, start=NOW, end=NOW - timedelta(days=1)
        )


async def test_the_biggest_shortage_comes_first(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    small, big = await _user(db), await _user(db)
    await _shift(db, tenant_ctx, small, expected="100", counted="95", reason="x")
    await _shift(db, tenant_ctx, big, expected="100", counted="40", reason="x")
    assert [r["cashier_user_id"] for r in await _report(db, tid)] == [str(big), str(small)]


async def test_a_matching_drawer_adds_nothing_to_the_overage(db, tenant_ctx) -> None:
    """Zero is neither a shortage nor an overage; counting it as one would hide the real picture."""
    a = await _user(db)
    await _shift(db, tenant_ctx, a, expected="100", counted="100")
    await _shift(db, tenant_ctx, a, expected="100", counted="103", reason="x")
    r = (await _report(db, tenant_ctx.tenant_id))[0]
    assert r["overage_total"] == "3.00"
    assert r["shortage_total"] == "0.00"
    assert r["shifts_with_variance"] == 1


async def test_a_shift_that_never_counted_is_not_a_shift_with_a_variance(db, tenant_ctx) -> None:
    """An uncounted shift carries a NULL gap; whatever an old row holds there is not a finding."""
    a = await _user(db)
    s = await _shift(db, tenant_ctx, a, expected=None, counted=None)
    s.variance = D("7.00")  # stray value on a shift that was never counted
    await db.flush()
    await _shift(db, tenant_ctx, a, expected="100", counted="100")
    r = (await _report(db, tenant_ctx.tenant_id))[0]
    assert r["shifts_with_variance"] == 0
    assert r["net_variance"] == "0.00"
    assert r["shortage_total"] == "0.00" and r["overage_total"] == "0.00"


async def test_expected_cash_of_a_shift_that_never_counted_is_not_added_in(db, tenant_ctx) -> None:
    """The book balance of an uncounted day is not drawer cash and must not inflate the total."""
    a = await _user(db)
    s = await _shift(db, tenant_ctx, a, expected="999", counted=None)
    assert s.counted_cash is None
    await _shift(db, tenant_ctx, a, expected="100", counted="100")
    r = (await _report(db, tenant_ctx.tenant_id))[0]
    assert r["expected_cash"] == "100.00"
    assert r["counted_shifts"] == 1
    assert r["shifts"] == 2


async def test_a_shift_marked_open_is_never_reported_even_with_a_close_time(db, tenant_ctx) -> None:
    a = await _user(db)
    s = await _shift(db, tenant_ctx, a, expected="100", counted="100")
    s.status = "OPEN"
    await db.flush()
    assert await _report(db, tenant_ctx.tenant_id) == []


async def test_the_list_is_ordered_by_shortage_whatever_the_order_they_were_made(
    db, tenant_ctx
) -> None:
    users = [await _user(db) for _ in range(4)]
    for u, counted in zip(users, ["90", "50", "99", "70"], strict=True):
        await _shift(db, tenant_ctx, u, expected="100", counted=counted, reason="x")
    shortages = [r["shortage_total"] for r in await _report(db, tenant_ctx.tenant_id)]
    assert shortages == ["50.00", "30.00", "10.00", "1.00"]
