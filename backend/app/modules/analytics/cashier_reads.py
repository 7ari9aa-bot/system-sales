"""The till's cash records, read as a projection for the owner assistant.

The cashier is no longer only a sales ledger. A shift opens with a float PER PAYMENT METHOD
(``pos_session_floats``), books every drawer movement (``pos_cash_movements``), counts the drawer
at close and at every hand-off, and writes one expected-versus-counted row per method
(``pos_session_reconciliations``, ``pos_session_handovers``). The owner assistant has to be able
to read all of it, and it may not import ``app.modules.pos``: the cross-module import ratchet is
already at its ceiling, an ``si_*`` handler may not import another module's service (that is
where the writes live — see ``tests/test_si_tools_are_read_only.py``), and ``pos`` already
imports ``analytics`` (``analytics.timekit.merchant_day``), so the reverse edge would close a
cycle the boundary guard refuses.

So this is a READ MODEL, the same shape as ``customers/timeline.py``: parameter-bound SQL over
another domain's tables, no model import, no service import, no write. It reads the LEDGERS, never
the ``pos_daily_sales`` projection, for anything the projection does not really hold: its upsert
writes ``variance_total = 0`` and ``by_method = []``, so those two are not a measurement there.
Per-device daily sales, returns, tax and counts ARE the projection's job and are read from it.

**Where the arithmetic runs.** Every figure the answer quotes is grouped and summed by PostgreSQL,
in the same statement that selects the rows: a drawer's expected cash is
``opening_float + SUM(in) - SUM(out)`` evaluated by the database, not a Python loop over every
movement of the window. That is not a style choice. A busy shop closes dozens of shifts a day and
books a movement for every cash sale, so the earlier shape — read the whole ledger into Python,
then slice ``rows[:limit]`` for display — paid for every row in the window to show twenty-five of
them, and its cost grew with the shop's success. Two rules follow, and both are pinned by
``tests/test_si_cashier_reads.py``:

* a *list* read is bounded by SQL (``LIMIT``) and is never longer than the caller's ``limit``;
* a *total* is computed by SQL over the whole window, so a bounded list never shortens a sum.

The one exception is deliberate: ``expected_cash``/``drawer_rows`` keep the till's own Python
arithmetic as the reference the SQL is checked against, and they are what the cross-check test
compares with ``pos.tender.expected_drawer_cash``. ``SUM`` over ``NUMERIC(14,2)`` columns is
exact, so the two agree to the cent — which the DB-backed test asserts on a real shift.

Money leaves as a ``Decimal`` rounded half-up to the cent. A difference is returned as a positive
MAGNITUDE plus a ``shortage``/``overage`` label, because the evidence store refuses negative
numbers and a shortage of 25 should never be quotable as "-25".
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import text as _sql
from sqlalchemy.ext.asyncio import AsyncSession

#: The scale of every MONEY column, so a sum here and a stored figure agree to the cent.
_CENT = Decimal("0.01")

#: Every payment status that means the money was actually taken. Mirrors
#: ``orders.money.COLLECTED_PAYMENT_STATUSES``: a refunded payment still put money in the till on
#: that tender, and the terminal slip the cashier compares against is the day's takings. Duplicated
#: here on purpose — importing ``orders`` from this read model would be the very cross-module edge
#: it exists to avoid; ``tests/test_cashier_reads.py`` pins the two tuples together.
COLLECTED_PAYMENT_STATUSES: tuple[str, ...] = ("captured", "partially_refunded", "refunded")

#: A closed shift in the window with the drawer figures the close stored, and the expected cash
#: the database computes from the ledger. The movements are summed in a subquery keyed on the
#: SAME window, so the join touches the ledger of these shifts and nothing else. ``m.cash_in`` is
#: NULL for a shift with no movements, hence the COALESCE: a float-only drawer is not unknown.
_DRAWER_CTE = (
    "WITH closed AS ("
    "  SELECT s.id::text AS session_id, s.register_id::text AS register_id, "
    "  COALESCE(r.name, '') AS register_name, s.cashier_user_id::text AS cashier_user_id, "
    "  s.opening_float AS opening_float, s.counted_cash AS counted_cash, "
    "  s.opened_at AS opened_at, s.closed_at AS closed_at, "
    "  s.opening_float + COALESCE(m.cash_in, 0) - COALESCE(m.cash_out, 0) AS expected_cash "
    "  FROM pos_sessions s "
    "  LEFT JOIN pos_registers r ON r.id = s.register_id AND r.tenant_id = s.tenant_id "
    "  LEFT JOIN ("
    "    SELECT mv.session_id, "
    "    SUM(CASE WHEN mv.direction = 'in' THEN mv.amount ELSE 0 END) AS cash_in, "
    "    SUM(CASE WHEN mv.direction = 'out' THEN mv.amount ELSE 0 END) AS cash_out "
    "    FROM pos_cash_movements mv "
    "    WHERE mv.tenant_id = :tenant_id AND mv.session_id IN ("
    "      SELECT w.id FROM pos_sessions w "
    "      WHERE w.tenant_id = :tenant_id AND w.status = 'CLOSED' "
    "      AND w.closed_at >= :start AND w.closed_at < :end"
    "    ) GROUP BY mv.session_id"
    "  ) m ON m.session_id = s.id "
    "  WHERE s.tenant_id = :tenant_id AND s.status = 'CLOSED' "
    "  AND s.closed_at >= :start AND s.closed_at < :end"
    ") "
)

#: The drawer of each closed shift, newest first, bounded by the caller's limit.
_DRAWER_PAGE_SQL = _sql(
    _DRAWER_CTE + "SELECT session_id, register_id, register_name, cashier_user_id, opening_float, "
    "counted_cash, expected_cash, opened_at, closed_at FROM closed "
    "ORDER BY closed_at DESC, session_id LIMIT :limit"
)

#: Every window total at once: closed shifts, the ones that counted the drawer, expected, counted
#: and the two sides of the gap. Computed over the WHOLE window, so the bounded page above can
#: never make a total look smaller than it is.
_DRAWER_TOTALS_SQL = _sql(
    _DRAWER_CTE + "SELECT COUNT(*) AS shifts_closed, "
    "COUNT(counted_cash) AS shifts_counted, "
    "COALESCE(SUM(CASE WHEN counted_cash IS NOT NULL THEN expected_cash ELSE 0 END), 0) "
    "AS total_expected, "
    "COALESCE(SUM(counted_cash), 0) AS total_counted, "
    "COALESCE(SUM(CASE WHEN counted_cash < expected_cash "
    "THEN expected_cash - counted_cash ELSE 0 END), 0) AS shortage_total, "
    "COALESCE(SUM(CASE WHEN counted_cash > expected_cash "
    "THEN counted_cash - expected_cash ELSE 0 END), 0) AS overage_total, "
    "COUNT(*) FILTER (WHERE counted_cash IS NOT NULL AND counted_cash <> expected_cash) "
    "AS shifts_with_a_difference FROM closed"
)

#: Only the shifts whose count did not match, biggest gap first. The ordering and the LIMIT are the
#: database's: ranking in Python would need every shift of the window in memory to show ten.
_DRAWER_DIFFERENCES_SQL = _sql(
    _DRAWER_CTE + "SELECT session_id, register_id, register_name, cashier_user_id, opening_float, "
    "counted_cash, expected_cash, opened_at, closed_at FROM closed "
    "WHERE counted_cash IS NOT NULL AND counted_cash <> expected_cash "
    "ORDER BY abs(counted_cash - expected_cash) DESC, closed_at DESC, session_id LIMIT :limit"
)

#: Drawer movements grouped by reason and direction: a closed set (six reasons, two directions), so
#: this is at most twelve rows however many movements the window holds. ``ORDER BY SUM(amount)``
#: keeps the biggest reason first, then the reason and direction as a stable tie-break.
_CASH_MOVEMENT_GROUPS_SQL = _sql(
    "SELECT m.direction AS direction, m.reason AS reason, COUNT(*) AS movements, "
    "SUM(m.amount) AS total "
    "FROM pos_cash_movements m "
    "WHERE m.tenant_id = :tenant_id AND m.created_at >= :start AND m.created_at < :end "
    "GROUP BY m.direction, m.reason "
    "ORDER BY SUM(m.amount) DESC, m.reason, m.direction"
)

#: The same window as two totals and a count, so a shortened reason list never understates cash in.
_CASH_MOVEMENT_TOTALS_SQL = _sql(
    "SELECT COUNT(*) AS movement_count, "
    "COALESCE(SUM(CASE WHEN m.direction = 'in' THEN m.amount ELSE 0 END), 0) AS cash_in, "
    "COALESCE(SUM(CASE WHEN m.direction = 'out' THEN m.amount ELSE 0 END), 0) AS cash_out "
    "FROM pos_cash_movements m "
    "WHERE m.tenant_id = :tenant_id AND m.created_at >= :start AND m.created_at < :end"
)

#: Expected versus counted per payment method, summed by the database over the window's shifts.
#: Grouped by method: four rows at most, whatever the shop's volume.
_RECONCILIATIONS_BY_METHOD_SQL = _sql(
    "SELECT c.method AS method, COUNT(*) AS reconciliations, "
    "SUM(c.expected_amount) AS expected_amount, SUM(c.counted_amount) AS counted_amount, "
    "SUM(c.variance) AS variance "
    "FROM pos_session_reconciliations c "
    "WHERE c.tenant_id = :tenant_id AND c.session_id IN ("
    "  SELECT w.id FROM pos_sessions w "
    "  WHERE w.tenant_id = :tenant_id AND w.status = 'CLOSED' "
    "  AND w.closed_at >= :start AND w.closed_at < :end"
    ") GROUP BY c.method ORDER BY c.method"
)

#: The float each method opened with, summed over the same shifts.
_FLOATS_BY_METHOD_SQL = _sql(
    "SELECT f.method AS method, SUM(f.amount) AS amount "
    "FROM pos_session_floats f "
    "WHERE f.tenant_id = :tenant_id AND f.session_id IN ("
    "  SELECT w.id FROM pos_sessions w "
    "  WHERE w.tenant_id = :tenant_id AND w.status = 'CLOSED' "
    "  AND w.closed_at >= :start AND w.closed_at < :end"
    ") GROUP BY f.method"
)

#: How many shifts closed in the window, so a per-method answer can say what it covers.
_CLOSED_SHIFT_COUNT_SQL = _sql(
    "SELECT COUNT(*) AS shifts_closed FROM pos_sessions s "
    "WHERE s.tenant_id = :tenant_id AND s.status = 'CLOSED' "
    "AND s.closed_at >= :start AND s.closed_at < :end"
)

#: One page of drawer hand-offs, newest first, with the names joined in so a per-person answer can
#: name them without a second module's model.
_HANDOVERS_SQL = _sql(
    "SELECT h.session_id::text AS session_id, h.from_user_id::text AS from_user_id, "
    "COALESCE(fu.full_name, '') AS from_name, h.to_user_id::text AS to_user_id, "
    "COALESCE(tu.full_name, '') AS to_name, h.expected_cash AS expected_cash, "
    "h.counted_cash AS counted_cash, h.variance AS variance, h.note AS note, "
    "h.created_at AS created_at "
    "FROM pos_session_handovers h "
    "LEFT JOIN users fu ON fu.id = h.from_user_id "
    "LEFT JOIN users tu ON tu.id = h.to_user_id "
    "WHERE h.tenant_id = :tenant_id AND h.created_at >= :start AND h.created_at < :end "
    "ORDER BY h.created_at DESC, h.session_id LIMIT :limit"
)

#: How many hand-offs the window holds and how far off they were, over ALL of them.
_HANDOVER_TOTALS_SQL = _sql(
    "SELECT COUNT(*) AS handover_count, "
    "COALESCE(SUM(CASE WHEN h.variance < 0 THEN -h.variance ELSE 0 END), 0) AS shortage_total, "
    "COALESCE(SUM(CASE WHEN h.variance > 0 THEN h.variance ELSE 0 END), 0) AS overage_total "
    "FROM pos_session_handovers h "
    "WHERE h.tenant_id = :tenant_id AND h.created_at >= :start AND h.created_at < :end"
)

#: Per-device daily sales. Only the columns the projection really holds: the upsert writes
#: ``variance_total = 0`` and ``by_method = []``, so those are deliberately not selected.
_DAILY_SQL = _sql(
    "SELECT d.business_date AS business_date, d.register_id::text AS register_id, "
    "COALESCE(r.name, '') AS register_name, d.session_count AS session_count, "
    "d.invoice_count AS invoice_count, d.returns_count AS returns_count, "
    "d.sales_total AS sales_total, d.returns_total AS returns_total, "
    "d.taxes_total AS taxes_total "
    "FROM pos_daily_sales d "
    "LEFT JOIN pos_registers r ON r.id = d.register_id AND r.tenant_id = d.tenant_id "
    "WHERE d.tenant_id = :tenant_id AND d.business_date >= :start_day "
    "AND d.business_date <= :end_day "
    "ORDER BY d.business_date DESC, COALESCE(r.name, '') LIMIT :limit"
)

#: The window's own totals for the same projection, over every till and day in it.
_DAILY_TOTALS_SQL = _sql(
    "SELECT COUNT(DISTINCT d.business_date) AS days, "
    "COALESCE(SUM(d.sales_total), 0) AS sales_total, "
    "COALESCE(SUM(d.returns_total), 0) AS returns_total, "
    "COALESCE(SUM(d.taxes_total), 0) AS taxes_total "
    "FROM pos_daily_sales d "
    "WHERE d.tenant_id = :tenant_id AND d.business_date >= :start_day "
    "AND d.business_date <= :end_day"
)

#: What each payment method took on the till's SALE receipts in the window. The receipts are the
#: filter (a payment belongs to an order, and only the till's sale receipts are the till's
#: takings), so an exchange's second receipt cannot count the same payment twice. Grouped by
#: method — four rows at most — and summed by the database.
_SALES_BY_METHOD_SQL = _sql(
    "SELECT p.method AS method, SUM(p.amount) AS amount, COUNT(*) AS payment_count "
    "FROM order_payments p "
    "WHERE p.tenant_id = :tenant_id AND p.status = ANY(:statuses) "
    "AND p.order_id IN ("
    "  SELECT r.order_id FROM pos_receipts r "
    "  WHERE r.tenant_id = :tenant_id AND r.kind = 'sale' "
    "  AND r.issued_at >= :start AND r.issued_at < :end"
    ") GROUP BY p.method ORDER BY SUM(p.amount) DESC, p.method"
)


def _money(value: object) -> Decimal:
    """A finite amount rounded half-up to the cent, the scale of every MONEY column."""
    return Decimal(str(value if value is not None else 0)).quantize(_CENT, rounding=ROUND_HALF_UP)


def money_str(value: object) -> str:
    """A figure ready to quote: ``1234.50``, never ``1234.5`` or a float artefact."""
    return format(_money(value), "f")


def difference_side(value: object) -> tuple[str, Decimal]:
    """A signed difference as ``(label, positive magnitude)``.

    ``counted - expected``: positive is an overage, negative a shortage. The magnitude is what a
    fact may carry (the evidence store drops negatives); the label is what says which way it went.
    """
    amount = _money(value)
    if amount < 0:
        return "shortage", -amount
    if amount > 0:
        return "overage", amount
    return "matched", amount


def expected_cash(opening_float: object, movements) -> Decimal:
    """The cash a drawer should hold: its opening float plus every ``in`` row minus every ``out``.

    The same rule the till closes with (``pos.tender.expected_drawer_cash``), recomputed from the
    ledger rather than trusted from a stored column, so a hand-edited expectation cannot pass.

    The reads below compute this in SQL instead, because a Python loop needs the whole ledger in
    memory to answer one question. This function stays as the reference that arithmetic is checked
    against (``tests/test_si_cashier_reads.py``), and the DB-backed test asserts the two agree on a
    real shift. ``SUM`` over ``NUMERIC(14,2)`` is exact, so they cannot drift apart at the cent.
    """
    total = _money(opening_float)
    for movement in movements:
        amount = _money(movement.amount)
        if movement.direction == "in":
            total += amount
        else:
            total -= amount
    return _money(total)


def drawer_row(row) -> dict:
    """One closed shift, as an answer quotes it: expected, counted and the difference.

    A shift that did not count its drawer (the till takes no cash) has no counted figure and
    therefore no difference: it is listed as not counted instead of reading as a perfect zero.
    """
    expected = _money(row.expected_cash)
    counted = row.counted_cash
    difference = None if counted is None else _money(counted) - expected
    label, magnitude = difference_side(difference) if difference is not None else (None, None)
    return {
        "session_id": row.session_id,
        "register_id": row.register_id,
        "register_name": row.register_name,
        "cashier_user_id": row.cashier_user_id,
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "opening_float": money_str(row.opening_float),
        "expected_cash": money_str(expected),
        "counted": counted is not None,
        "counted_cash": money_str(counted) if counted is not None else None,
        "difference": money_str(magnitude) if magnitude is not None else None,
        "difference_kind": label,
    }


def drawer_rows(sessions, movements_by_session: dict[str, list]) -> list[dict]:
    """Expected, counted and the difference for each closed shift, from the ledger.

    The Python reference for ``drawer_row``: it takes raw session rows and their movements, the
    shape the database used to hand back. Kept for the cross-check test, not for the reads.
    """
    out: list[dict] = []
    for row in sessions:
        expected = expected_cash(row.opening_float, movements_by_session.get(row.session_id, []))
        counted = row.counted_cash
        difference = None if counted is None else _money(counted) - expected
        label, magnitude = difference_side(difference) if difference is not None else (None, None)
        out.append(
            {
                "session_id": row.session_id,
                "register_id": row.register_id,
                "register_name": row.register_name,
                "cashier_user_id": row.cashier_user_id,
                "opened_at": row.opened_at.isoformat() if row.opened_at else None,
                "closed_at": row.closed_at.isoformat() if row.closed_at else None,
                "opening_float": money_str(row.opening_float),
                "expected_cash": money_str(expected),
                "counted": counted is not None,
                "counted_cash": money_str(counted) if counted is not None else None,
                "difference": money_str(magnitude) if magnitude is not None else None,
                "difference_kind": label,
            }
        )
    return out


def _window(tenant_id: uuid.UUID, start: datetime, end: datetime) -> dict:
    return {"tenant_id": str(tenant_id), "start": start, "end": end}


async def _drawer_totals(session: AsyncSession, tenant_id: uuid.UUID, start, end):
    """The window's drawer totals, computed by the database over every closed shift in it."""
    row = (await session.execute(_DRAWER_TOTALS_SQL, _window(tenant_id, start, end))).one()
    return row


async def expected_vs_counted(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    start: datetime,
    end: datetime,
    limit: int,
) -> dict:
    """Per closed shift: what the drawer should have held and what was counted.

    Two statements: the totals over the whole window, and one bounded page of shifts. The page is
    ``LIMIT``ed by SQL, so a shop with a year of shifts costs the same to answer as a shop with one.
    """
    params = {**_window(tenant_id, start, end), "limit": limit}
    rows = (await session.execute(_DRAWER_PAGE_SQL, params)).all()
    totals = await _drawer_totals(session, tenant_id, start, end)
    return {
        "shifts_closed": int(totals.shifts_closed or 0),
        "shifts_counted": int(totals.shifts_counted or 0),
        "total_expected": money_str(totals.total_expected),
        "total_counted": money_str(totals.total_counted),
        "shortage_total": money_str(totals.shortage_total),
        "overage_total": money_str(totals.overage_total),
        "shifts": [drawer_row(r) for r in rows],
    }


async def drawer_differences(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    start: datetime,
    end: datetime,
    limit: int,
) -> dict:
    """Only the closed shifts whose count did not match, biggest gap first, as a magnitude.

    The ranking is the database's (``abs(counted - expected)``), so the largest gap in the window
    is the first row even when the window holds more shifts than the limit allows.
    """
    params = {**_window(tenant_id, start, end), "limit": limit}
    rows = (await session.execute(_DRAWER_DIFFERENCES_SQL, params)).all()
    totals = await _drawer_totals(session, tenant_id, start, end)
    return {
        "shifts_closed": int(totals.shifts_closed or 0),
        "shifts_with_a_difference": int(totals.shifts_with_a_difference or 0),
        "shortage_total": money_str(totals.shortage_total),
        "overage_total": money_str(totals.overage_total),
        "differences": [drawer_row(r) for r in rows],
    }


async def cash_in_out(
    session: AsyncSession, tenant_id: uuid.UUID, *, start: datetime, end: datetime, limit: int
) -> dict:
    """Every drawer movement in the window, totalled per reason and direction.

    Grouped by the database. ``reason`` is a closed set (``cash_sale``, ``cash_refund``, ``pay_in``,
    ``pay_out``, ``cash_drop``, ``float_adjust``) and ``direction`` is in/out, so the grouped read
    is at most twelve rows however many movements the window holds; the totals come from a second
    aggregate so a shortened list can never shorten the cash in figure.
    """
    params = _window(tenant_id, start, end)
    groups = (await session.execute(_CASH_MOVEMENT_GROUPS_SQL, params)).all()
    totals = (await session.execute(_CASH_MOVEMENT_TOTALS_SQL, params)).one()
    lines = [
        {
            "reason": str(row.reason),
            "direction": str(row.direction),
            "movements": int(row.movements or 0),
            "total": money_str(row.total),
        }
        for row in groups
    ]
    return {
        "movement_count": int(totals.movement_count or 0),
        "cash_in_total": money_str(totals.cash_in),
        "cash_out_total": money_str(totals.cash_out),
        "net_cash": money_str(_money(totals.cash_in) - _money(totals.cash_out)),
        "by_reason": lines[:limit],
    }


async def reconciliation_by_method(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    start: datetime,
    end: datetime,
    limit: int,
) -> dict:
    """Expected versus counted per payment method over the shifts that closed in the window.

    Both sides are grouped by method in SQL — four rows at most — so the totals cover every method
    and only the displayed list honours the caller's limit.
    """
    params = _window(tenant_id, start, end)
    shifts = (await session.execute(_CLOSED_SHIFT_COUNT_SQL, params)).one()
    if not int(shifts.shifts_closed or 0):
        return {"methods": [], "sessions": 0, "shortage_total": "0.00", "overage_total": "0.00"}
    recs = (await session.execute(_RECONCILIATIONS_BY_METHOD_SQL, params)).all()
    floats = (await session.execute(_FLOATS_BY_METHOD_SQL, params)).all()
    opening = {str(row.method): _money(row.amount) for row in floats}
    methods = []
    for row in recs:
        label, magnitude = difference_side(row.variance)
        method = str(row.method)
        methods.append(
            {
                "method": method,
                "reconciliations": int(row.reconciliations or 0),
                "opening_float": money_str(opening.get(method, Decimal(0))),
                "expected": money_str(row.expected_amount),
                "counted": money_str(row.counted_amount),
                "difference": money_str(magnitude),
                "difference_kind": label,
            }
        )
    shortage = sum(
        (Decimal(m["difference"]) for m in methods if m["difference_kind"] == "shortage"),
        Decimal(0),
    )
    overage = sum(
        (Decimal(m["difference"]) for m in methods if m["difference_kind"] == "overage"),
        Decimal(0),
    )
    return {
        "sessions": int(shifts.shifts_closed or 0),
        "methods": methods[:limit],
        "shortage_total": money_str(shortage),
        "overage_total": money_str(overage),
    }


async def shift_handovers(
    session: AsyncSession, tenant_id: uuid.UUID, *, start: datetime, end: datetime, limit: int
) -> dict:
    """Every drawer hand-off in the window: who gave it, who took it, and how far off the count.

    The list is one bounded page; the count and the two gap totals are a separate aggregate over
    every hand-off in the window, so a shop that hands over between three shifts a day still reads
    the same twenty-five rows as one that does it thirty times.
    """
    params = {**_window(tenant_id, start, end), "limit": limit}
    rows = (await session.execute(_HANDOVERS_SQL, params)).all()
    totals = (await session.execute(_HANDOVER_TOTALS_SQL, _window(tenant_id, start, end))).one()
    handovers = []
    for row in rows:
        label, magnitude = difference_side(row.variance)
        handovers.append(
            {
                "session_id": row.session_id,
                "at": row.created_at.isoformat() if row.created_at else None,
                "from_user_id": row.from_user_id,
                "from_name": row.from_name or None,
                "to_user_id": row.to_user_id,
                "to_name": row.to_name or None,
                "expected_cash": money_str(row.expected_cash),
                "counted_cash": money_str(row.counted_cash),
                "difference": money_str(magnitude),
                "difference_kind": label,
                "note": row.note,
            }
        )
    return {
        "handover_count": int(totals.handover_count or 0),
        "shortage_total": money_str(totals.shortage_total),
        "overage_total": money_str(totals.overage_total),
        "handovers": handovers,
    }


async def daily_by_device(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    start_day: date,
    end_day: date,
    limit: int,
) -> dict:
    """The daily projection per till: sessions, invoices, returns, sales, returns money, tax.

    Read from ``pos_daily_sales`` because that IS what the projection holds. Its
    ``variance_total`` and ``by_method`` are placeholders the upsert writes as ``0`` and ``[]``,
    so they are not read here and the caller is told so: drawer differences come from the ledgers.

    One bounded page of till-days plus the window's own totals: a year of days per till cannot make
    the answer slower than a day's.
    """
    params = {"tenant_id": str(tenant_id), "start_day": start_day, "end_day": end_day}
    rows = (await session.execute(_DAILY_SQL, {**params, "limit": limit})).all()
    totals = (await session.execute(_DAILY_TOTALS_SQL, params)).one()
    devices = [
        {
            "business_date": r.business_date.isoformat(),
            "register_id": r.register_id,
            "register_name": r.register_name or None,
            "sessions": int(r.session_count or 0),
            "invoices": int(r.invoice_count or 0),
            "returns": int(r.returns_count or 0),
            "sales_total": money_str(r.sales_total),
            "returns_total": money_str(r.returns_total),
            "taxes_total": money_str(r.taxes_total),
        }
        for r in rows
    ]
    return {
        "days": int(totals.days or 0),
        "devices": devices,
        "sales_total": money_str(totals.sales_total),
        "returns_total": money_str(totals.returns_total),
        "taxes_total": money_str(totals.taxes_total),
    }


async def sales_by_method(
    session: AsyncSession, tenant_id: uuid.UUID, *, start: datetime, end: datetime, limit: int
) -> dict:
    """What each payment method collected on the till's sale receipts in the window.

    Grouped and summed by the database: one row per payment method, so the answer costs the same
    whether the till took ten payments or ten thousand.
    """
    rows = (
        await session.execute(
            _SALES_BY_METHOD_SQL,
            {
                "tenant_id": str(tenant_id),
                "statuses": list(COLLECTED_PAYMENT_STATUSES),
                "start": start,
                "end": end,
            },
        )
    ).all()
    methods = [{"method": str(row.method), "collected": money_str(row.amount)} for row in rows]
    return {
        "methods": methods[:limit],
        "collected_total": money_str(sum((Decimal(m["collected"]) for m in methods), Decimal(0))),
        "payment_count": sum(int(row.payment_count or 0) for row in rows),
    }
