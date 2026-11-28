"""The cashier read model against a REAL database.

``tests/test_si_cashier_reads.py`` proves the numbers with a fake session, which cannot tell a
working statement from one Postgres would refuse. This file runs the same reads on a real
Postgres, so a broken join, a wrong ``GROUP BY`` or a ``LIMIT`` in the wrong place fails here
instead of in production.

What it pins, in the order the observations were raised:

* the drawer arithmetic the database computes (``opening_float + SUM(in) - SUM(out)``) equals the
  till's own ``pos.tender.expected_drawer_cash`` to the cent, on a real shift with real movements;
* a bounded page never shortens a window total: three closed shifts, ``limit=2``, and the totals
  still describe all three;
* every grouped read answers the same shape the tool consumes (per reason, per method).

DB-backed by design: skipped without ``DATABASE_URL_APP_ADMIN`` (CI is their first real run).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.applications.apparel.modules.analytics import cashier_reads as reads
from app.applications.apparel.modules.pos.models import (
    PosCashMovement,
    PosSession,
    PosSessionHandover,
    PosSessionReconciliation,
)
from tests._pos_helpers import _register

pytestmark = pytest.mark.asyncio

D = Decimal
NOW = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
START = NOW - timedelta(days=1)
END = NOW + timedelta(days=1)


async def _closed_shift(db, ctx, register_id, *, opening, counted, closed_at, movements):
    """A closed shift written the way ``close_session`` leaves it, with its drawer ledger."""
    session = PosSession(
        tenant_id=ctx.tenant_id,
        register_id=register_id,
        status="CLOSED",
        opening_float=D(opening),
        cashier_user_id=ctx.user.id,
        opened_at=closed_at - timedelta(hours=8),
        closed_at=closed_at,
        expected_cash=None,
        counted_cash=None if counted is None else D(counted),
        variance=None,
    )
    db.add(session)
    await db.flush()
    for direction, reason, amount in movements:
        db.add(
            PosCashMovement(
                tenant_id=ctx.tenant_id,
                session_id=session.id,
                direction=direction,
                reason=reason,
                amount=D(amount),
                created_by_user_id=ctx.user.id,
                created_at=closed_at,
            )
        )
    await db.flush()
    return session


async def test_the_database_drawer_arithmetic_is_the_tills_own(db, tenant_ctx) -> None:
    from app.applications.apparel.modules.pos.tender import expected_drawer_cash

    register = await _register(db, tenant_ctx)
    movements = [
        ("in", "cash_sale", "50.00"),
        ("out", "cash_drop", "30.00"),
        ("in", "pay_in", "12.34"),
        ("out", "float_adjust", "0.05"),
    ]
    await _closed_shift(
        db,
        tenant_ctx,
        register.id,
        opening="100.00",
        counted="127.29",
        closed_at=NOW,
        movements=movements,
    )
    summary = await reads.expected_vs_counted(
        db, tenant_ctx.tenant_id, start=START, end=END, limit=10
    )
    expected = expected_drawer_cash(
        opening_float=D("100.00"),
        movements=[(d, r, D(a)) for d, r, a in movements],
    )
    assert expected == D("132.29")
    assert summary["shifts"][0]["expected_cash"] == "132.29"
    assert summary["total_expected"] == "132.29"
    assert summary["shifts_counted"] == 1
    # counted 127.29 against 132.29 expected: a 5.00 shortage, quoted as a magnitude
    assert summary["shifts"][0]["difference"] == "5.00"
    assert summary["shifts"][0]["difference_kind"] == "shortage"
    assert summary["shortage_total"] == "5.00"


async def test_a_shift_with_no_movements_still_reads_its_float(db, tenant_ctx) -> None:
    """The movements subquery returns nothing for a float-only drawer: that is not "unknown"."""
    register = await _register(db, tenant_ctx)
    await _closed_shift(
        db, tenant_ctx, register.id, opening="200.00", counted="200.00", closed_at=NOW, movements=[]
    )
    summary = await reads.expected_vs_counted(
        db, tenant_ctx.tenant_id, start=START, end=END, limit=10
    )
    assert summary["shifts"][0]["expected_cash"] == "200.00"
    assert summary["shifts"][0]["difference_kind"] == "matched"


async def test_a_bounded_page_never_shortens_the_window_totals(db, tenant_ctx) -> None:
    register = await _register(db, tenant_ctx)
    for hours, counted in ((3, "95.00"), (2, "100.00"), (1, "90.00")):
        await _closed_shift(
            db,
            tenant_ctx,
            register.id,
            opening="100.00",
            counted=counted,
            closed_at=NOW - timedelta(hours=hours),
            movements=[],
        )
    summary = await reads.expected_vs_counted(
        db, tenant_ctx.tenant_id, start=START, end=END, limit=2
    )
    assert len(summary["shifts"]) == 2, "the page honours the limit"
    assert summary["shifts_closed"] == 3, "the count covers the window"
    assert summary["shifts_counted"] == 3
    assert summary["total_expected"] == "300.00"
    assert summary["shortage_total"] == "15.00", "two shortages: 5.00 and 10.00"
    assert summary["overage_total"] == "0.00"


async def test_drawer_differences_ranks_by_the_biggest_gap_in_the_database(db, tenant_ctx) -> None:
    register = await _register(db, tenant_ctx)
    await _closed_shift(
        db,
        tenant_ctx,
        register.id,
        opening="100.00",
        counted="97.00",
        closed_at=NOW - timedelta(hours=3),
        movements=[],
    )
    await _closed_shift(
        db,
        tenant_ctx,
        register.id,
        opening="100.00",
        counted="80.00",
        closed_at=NOW - timedelta(hours=2),
        movements=[],
    )
    await _closed_shift(
        db,
        tenant_ctx,
        register.id,
        opening="100.00",
        counted="100.00",
        closed_at=NOW - timedelta(hours=1),
        movements=[],
    )
    summary = await reads.drawer_differences(
        db, tenant_ctx.tenant_id, start=START, end=END, limit=1
    )
    assert summary["shifts_closed"] == 3
    assert summary["shifts_with_a_difference"] == 2
    assert len(summary["differences"]) == 1, "the page honours the limit"
    # the largest gap is first even though only one row is shown
    assert summary["differences"][0]["difference"] == "20.00"
    assert summary["shortage_total"] == "23.00", "the total covers both gaps"


async def test_cash_in_out_groups_by_reason_in_the_database(db, tenant_ctx) -> None:
    register = await _register(db, tenant_ctx)
    await _closed_shift(
        db,
        tenant_ctx,
        register.id,
        opening="0",
        counted="0",
        closed_at=NOW,
        movements=[
            ("in", "cash_sale", "50.00"),
            ("in", "cash_sale", "25.00"),
            ("out", "cash_drop", "30.00"),
        ],
    )
    summary = await reads.cash_in_out(db, tenant_ctx.tenant_id, start=START, end=END, limit=10)
    assert summary["movement_count"] == 3
    assert summary["cash_in_total"] == "75.00"
    assert summary["cash_out_total"] == "30.00"
    assert summary["net_cash"] == "45.00"
    by_reason = {(line["reason"], line["direction"]): line for line in summary["by_reason"]}
    assert by_reason[("cash_sale", "in")]["movements"] == 2
    assert by_reason[("cash_sale", "in")]["total"] == "75.00"
    assert by_reason[("cash_drop", "out")]["total"] == "30.00"


async def test_reconciliation_reads_the_floats_and_the_gaps_per_method(db, tenant_ctx) -> None:
    register = await _register(db, tenant_ctx)
    shift = await _closed_shift(
        db,
        tenant_ctx,
        register.id,
        opening="100.00",
        counted="115.00",
        closed_at=NOW,
        movements=[("in", "cash_sale", "50.00")],
    )
    for method, expected, counted in (("cash", "120.00", "115.00"), ("card", "200.00", "200.00")):
        db.add(
            PosSessionReconciliation(
                tenant_id=tenant_ctx.tenant_id,
                session_id=shift.id,
                method=method,
                expected_amount=D(expected),
                counted_amount=D(counted),
                variance=D(counted) - D(expected),
            )
        )
    await db.flush()
    summary = await reads.reconciliation_by_method(
        db, tenant_ctx.tenant_id, start=START, end=END, limit=10
    )
    assert summary["sessions"] == 1
    methods = {row["method"]: row for row in summary["methods"]}
    assert methods["cash"]["expected"] == "120.00"
    assert methods["cash"]["difference"] == "5.00"
    assert methods["cash"]["difference_kind"] == "shortage"
    assert methods["card"]["difference_kind"] == "matched"
    assert summary["shortage_total"] == "5.00"


async def test_handovers_are_one_bounded_page_with_totals_over_all_of_them(db, tenant_ctx) -> None:
    register = await _register(db, tenant_ctx)
    shift = await _closed_shift(
        db,
        tenant_ctx,
        register.id,
        opening="100.00",
        counted="100.00",
        closed_at=NOW,
        movements=[],
    )
    giver = await _other_user(db)
    for hours, counted in ((3, "95.00"), (2, "100.00")):
        db.add(
            PosSessionHandover(
                tenant_id=tenant_ctx.tenant_id,
                session_id=shift.id,
                from_user_id=giver,
                to_user_id=tenant_ctx.user.id,
                expected_cash=D("100.00"),
                counted_cash=D(counted),
                variance=D(counted) - D("100.00"),
                note=None,
                created_at=NOW - timedelta(hours=hours),
            )
        )
    await db.flush()
    summary = await reads.shift_handovers(db, tenant_ctx.tenant_id, start=START, end=END, limit=1)
    assert summary["handover_count"] == 2
    assert len(summary["handovers"]) == 1
    assert summary["shortage_total"] == "5.00"


async def test_a_window_with_no_shifts_answers_zero_and_reads_no_rows(db, tenant_ctx) -> None:
    summary = await reads.expected_vs_counted(
        db, tenant_ctx.tenant_id, start=START, end=END, limit=5
    )
    assert summary == {
        "shifts_closed": 0,
        "shifts_counted": 0,
        "total_expected": "0.00",
        "total_counted": "0.00",
        "shortage_total": "0.00",
        "overage_total": "0.00",
        "shifts": [],
    }
    per_method = await reads.reconciliation_by_method(
        db, tenant_ctx.tenant_id, start=START, end=END, limit=5
    )
    assert per_method["methods"] == [] and per_method["sessions"] == 0


async def _other_user(db):
    """A second real user: a hand-off's giver is a foreign key, so a random uuid is refused."""
    from app.core.security import hash_password
    from app.modules.identity.models import User

    user = User(
        email=f"h-{uuid.uuid4().hex[:8]}@test.local",
        password_hash=hash_password("x-secret-pw"),
        full_name="Sara",
    )
    db.add(user)
    await db.flush()
    return user.id
