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

Every figure is computed here, in Python, from the rows the database returned, with the same
arithmetic the till uses at close (``pos.tender.expected_drawer_cash``): expected cash is the
opening float plus every ``in`` row minus every ``out`` row, never a stored number. Money leaves
as a ``Decimal`` rounded half-up to the cent. A difference is returned as a positive MAGNITUDE
plus a ``shortage``/``overage`` label, because the evidence store refuses negative numbers and a
shortage of 25 should never be quotable as "-25".
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

#: A shift that closed in the window, with the drawer figures the close stored. The register name
#: is joined here so a per-device answer can name the till without a second module's model.
_CLOSED_SESSIONS_SQL = _sql(
    "SELECT s.id::text AS session_id, s.register_id::text AS register_id, "
    "COALESCE(r.name, '') AS register_name, s.cashier_user_id::text AS cashier_user_id, "
    "s.opening_float AS opening_float, s.counted_cash AS counted_cash, "
    "s.opened_at AS opened_at, s.closed_at AS closed_at "
    "FROM pos_sessions s "
    "LEFT JOIN pos_registers r ON r.id = s.register_id AND r.tenant_id = s.tenant_id "
    "WHERE s.tenant_id = :tenant_id AND s.status = 'CLOSED' "
    "AND s.closed_at >= :start AND s.closed_at < :end "
    "ORDER BY s.closed_at"
)

#: The drawer ledger rows of the given shifts. A movement is append-only, so a missing row shows
#: up as a variance instead of being hidden.
_SESSION_MOVEMENTS_SQL = _sql(
    "SELECT m.session_id::text AS session_id, m.direction AS direction, m.amount AS amount "
    "FROM pos_cash_movements m "
    "WHERE m.tenant_id = :tenant_id AND m.session_id = ANY(CAST(:session_ids AS uuid[]))"
)

_CASH_MOVEMENTS_SQL = _sql(
    "SELECT m.direction AS direction, m.reason AS reason, m.amount AS amount "
    "FROM pos_cash_movements m "
    "WHERE m.tenant_id = :tenant_id AND m.created_at >= :start AND m.created_at < :end"
)

_RECONCILIATIONS_SQL = _sql(
    "SELECT c.method AS method, c.expected_amount AS expected_amount, "
    "c.counted_amount AS counted_amount, c.variance AS variance "
    "FROM pos_session_reconciliations c "
    "WHERE c.tenant_id = :tenant_id AND c.session_id = ANY(CAST(:session_ids AS uuid[]))"
)

_FLOATS_SQL = _sql(
    "SELECT f.method AS method, f.amount AS amount "
    "FROM pos_session_floats f "
    "WHERE f.tenant_id = :tenant_id AND f.session_id = ANY(CAST(:session_ids AS uuid[]))"
)

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
    "ORDER BY h.created_at DESC"
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
    "ORDER BY d.business_date DESC, COALESCE(r.name, '')"
)

#: What each payment method took on the till's SALE receipts in the window. The receipts are the
#: filter (a payment belongs to an order, and only the till's sale receipts are the till's
#: takings), so an exchange's second receipt cannot count the same payment twice.
_SALES_BY_METHOD_SQL = _sql(
    "SELECT p.method AS method, p.amount AS amount "
    "FROM order_payments p "
    "WHERE p.tenant_id = :tenant_id AND p.status = ANY(:statuses) "
    "AND p.order_id IN ("
    "  SELECT r.order_id FROM pos_receipts r "
    "  WHERE r.tenant_id = :tenant_id AND r.kind = 'sale' "
    "  AND r.issued_at >= :start AND r.issued_at < :end"
    ")"
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


async def _session_ids(
    session: AsyncSession, tenant_id: uuid.UUID, start: datetime, end: datetime
) -> list[str]:
    """The shifts that closed in the window. One query, reused by every per-shift read."""
    rows = (
        await session.execute(
            _CLOSED_SESSIONS_SQL, {"tenant_id": str(tenant_id), "start": start, "end": end}
        )
    ).all()
    return [r.session_id for r in rows]


async def closed_sessions(
    session: AsyncSession, tenant_id: uuid.UUID, *, start: datetime, end: datetime
) -> list:
    """The shifts that closed in ``[start, end)``, with the drawer figures the close stored."""
    return (
        await session.execute(
            _CLOSED_SESSIONS_SQL, {"tenant_id": str(tenant_id), "start": start, "end": end}
        )
    ).all()


async def _movements_by_session(
    session: AsyncSession, tenant_id: uuid.UUID, session_ids: list[str]
) -> dict[str, list]:
    """The drawer ledger of each given shift, keyed by session id."""
    if not session_ids:
        return {}
    rows = (
        await session.execute(
            _SESSION_MOVEMENTS_SQL,
            {"tenant_id": str(tenant_id), "session_ids": session_ids},
        )
    ).all()
    out: dict[str, list] = {}
    for row in rows:
        out.setdefault(row.session_id, []).append(row)
    return out


def expected_cash(opening_float: object, movements) -> Decimal:
    """The cash a drawer should hold: its opening float plus every ``in`` row minus every ``out``.

    The same rule the till closes with (``pos.tender.expected_drawer_cash``), recomputed from the
    ledger rather than trusted from a stored column, so a hand-edited expectation cannot pass.
    """
    total = _money(opening_float)
    for movement in movements:
        amount = _money(movement.amount)
        if movement.direction == "in":
            total += amount
        else:
            total -= amount
    return _money(total)


def drawer_rows(sessions, movements_by_session: dict[str, list]) -> list[dict]:
    """Expected, counted and the difference for each closed shift, from the ledger.

    A shift that did not count its drawer (the till takes no cash) has no counted figure and
    therefore no difference: it is listed as not counted instead of reading as a perfect zero.
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


async def expected_vs_counted(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    start: datetime,
    end: datetime,
    limit: int,
) -> dict:
    """Per closed shift: what the drawer should have held and what was counted."""
    sessions = await closed_sessions(session, tenant_id, start=start, end=end)
    movements = await _movements_by_session(session, tenant_id, [r.session_id for r in sessions])
    rows = drawer_rows(sessions, movements)
    counted = [r for r in rows if r["counted"]]
    shortages = [Decimal(r["difference"]) for r in counted if r["difference_kind"] == "shortage"]
    overages = [Decimal(r["difference"]) for r in counted if r["difference_kind"] == "overage"]
    return {
        "shifts_closed": len(rows),
        "shifts_counted": len(counted),
        "total_expected": money_str(
            sum((Decimal(r["expected_cash"]) for r in counted), Decimal(0))
        ),
        "total_counted": money_str(sum((Decimal(r["counted_cash"]) for r in counted), Decimal(0))),
        "shortage_total": money_str(sum(shortages, Decimal(0))),
        "overage_total": money_str(sum(overages, Decimal(0))),
        "shifts": rows[:limit],
    }


async def drawer_differences(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    start: datetime,
    end: datetime,
    limit: int,
) -> dict:
    """Only the closed shifts whose count did not match, biggest gap first, as a magnitude."""
    sessions = await closed_sessions(session, tenant_id, start=start, end=end)
    movements = await _movements_by_session(session, tenant_id, [r.session_id for r in sessions])
    rows = [
        r
        for r in drawer_rows(sessions, movements)
        if r["counted"] and r["difference_kind"] in ("shortage", "overage")
    ]
    rows.sort(key=lambda r: -Decimal(r["difference"]))
    return {
        "shifts_closed": len(sessions),
        "shifts_with_a_difference": len(rows),
        "shortage_total": money_str(
            sum(
                (Decimal(r["difference"]) for r in rows if r["difference_kind"] == "shortage"),
                Decimal(0),
            )
        ),
        "overage_total": money_str(
            sum(
                (Decimal(r["difference"]) for r in rows if r["difference_kind"] == "overage"),
                Decimal(0),
            )
        ),
        "differences": rows[:limit],
    }


async def cash_in_out(
    session: AsyncSession, tenant_id: uuid.UUID, *, start: datetime, end: datetime, limit: int
) -> dict:
    """Every drawer movement in the window, totalled per reason and direction."""
    rows = (
        await session.execute(
            _CASH_MOVEMENTS_SQL, {"tenant_id": str(tenant_id), "start": start, "end": end}
        )
    ).all()
    totals: dict[tuple[str, str], list] = {}
    for row in rows:
        key = (str(row.reason), str(row.direction))
        entry = totals.setdefault(key, [0, Decimal(0)])
        entry[0] += 1
        entry[1] += _money(row.amount)
    lines = [
        {
            "reason": reason,
            "direction": direction,
            "movements": count,
            "total": money_str(total),
        }
        for (reason, direction), (count, total) in sorted(
            totals.items(), key=lambda kv: (-kv[1][1], kv[0])
        )
    ]
    cash_in = sum((_money(r.amount) for r in rows if r.direction == "in"), Decimal(0))
    cash_out = sum((_money(r.amount) for r in rows if r.direction == "out"), Decimal(0))
    return {
        "movement_count": len(rows),
        "cash_in_total": money_str(cash_in),
        "cash_out_total": money_str(cash_out),
        "net_cash": money_str(cash_in - cash_out),
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
    """Expected versus counted per payment method over the shifts that closed in the window."""
    ids = await _session_ids(session, tenant_id, start, end)
    if not ids:
        return {"methods": [], "sessions": 0, "shortage_total": "0.00", "overage_total": "0.00"}
    params = {"tenant_id": str(tenant_id), "session_ids": ids}
    recs = (await session.execute(_RECONCILIATIONS_SQL, params)).all()
    floats = (await session.execute(_FLOATS_SQL, params)).all()
    opening: dict[str, Decimal] = {}
    for row in floats:
        opening[str(row.method)] = opening.get(str(row.method), Decimal(0)) + _money(row.amount)
    totals: dict[str, list] = {}
    for row in recs:
        entry = totals.setdefault(str(row.method), [0, Decimal(0), Decimal(0), Decimal(0)])
        entry[0] += 1
        entry[1] += _money(row.expected_amount)
        entry[2] += _money(row.counted_amount)
        entry[3] += _money(row.variance)
    methods = []
    for method, (count, expected, counted, variance) in sorted(totals.items()):
        label, magnitude = difference_side(variance)
        methods.append(
            {
                "method": method,
                "reconciliations": count,
                "opening_float": money_str(opening.get(method, Decimal(0))),
                "expected": money_str(expected),
                "counted": money_str(counted),
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
        "sessions": len(ids),
        "methods": methods[:limit],
        "shortage_total": money_str(shortage),
        "overage_total": money_str(overage),
    }


async def shift_handovers(
    session: AsyncSession, tenant_id: uuid.UUID, *, start: datetime, end: datetime, limit: int
) -> dict:
    """Every drawer hand-off in the window: who gave it, who took it, and how far off the count."""
    rows = (
        await session.execute(
            _HANDOVERS_SQL, {"tenant_id": str(tenant_id), "start": start, "end": end}
        )
    ).all()
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
        "handover_count": len(handovers),
        "shortage_total": money_str(
            sum(
                (Decimal(h["difference"]) for h in handovers if h["difference_kind"] == "shortage"),
                Decimal(0),
            )
        ),
        "overage_total": money_str(
            sum(
                (Decimal(h["difference"]) for h in handovers if h["difference_kind"] == "overage"),
                Decimal(0),
            )
        ),
        "handovers": handovers[:limit],
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
    """
    rows = (
        await session.execute(
            _DAILY_SQL,
            {"tenant_id": str(tenant_id), "start_day": start_day, "end_day": end_day},
        )
    ).all()
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
        "days": len({d["business_date"] for d in devices}),
        "devices": devices[:limit],
        "sales_total": money_str(sum((Decimal(d["sales_total"]) for d in devices), Decimal(0))),
        "returns_total": money_str(sum((Decimal(d["returns_total"]) for d in devices), Decimal(0))),
        "taxes_total": money_str(sum((Decimal(d["taxes_total"]) for d in devices), Decimal(0))),
    }


async def sales_by_method(
    session: AsyncSession, tenant_id: uuid.UUID, *, start: datetime, end: datetime, limit: int
) -> dict:
    """What each payment method collected on the till's sale receipts in the window."""
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
    totals: dict[str, Decimal] = {}
    for row in rows:
        method = str(row.method)
        totals[method] = totals.get(method, Decimal(0)) + _money(row.amount)
    methods = [
        {"method": method, "collected": money_str(total)}
        for method, total in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {
        "methods": methods[:limit],
        "collected_total": money_str(sum(totals.values(), Decimal(0))),
        "payment_count": len(rows),
    }
