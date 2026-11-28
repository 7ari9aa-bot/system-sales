"""``si_cashier``: the till's cash, its drawer and its payment methods, for the owner assistant.

``si_shop`` view=cashier answers what the till SOLD (sales, returns, net, per cashier, open
shifts). This tool answers the other half, the money itself: what went in and out of the drawer,
what should have been there versus what was counted, which shifts did not match, the per-method
reconciliation, the hand-offs between cashiers, the daily figure per device, and what each payment
method collected.

It lives in its own file because ``tools.py`` is 3,200 lines and a new tool does not have to grow
it. It reads through ``analytics.cashier_reads`` (a read model) and never imports
``app.applications.apparel.modules.pos``: an ``si_*`` handler may not import another module's service, and the
cross-module import ratchet is at its ceiling. The handler itself runs no SQL, so the read-only
guard (``tests/test_si_tools_are_read_only.py``) sees nothing but calls.

Every figure arrives already formatted by the read model. The model never computes: it quotes.
Each view checks the asker's permission AT RUN TIME, the way ``si_shop`` does, because one tool
that covers several reads must not let an asker read what one of them was closed to. The views
that name a cashier who was short (expected vs counted, drawer differences, hand-offs) need
``pos:override`` — the same permission the till's own cashier-custody report uses; the aggregate
views need ``orders:read``, the same permission the till's reports use.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.applications.apparel.modules.ai.agents.sales_intelligence.permissions import require
from app.applications.apparel.modules.analytics import cashier_reads as reads

#: Each view: (the permission THAT view needs, default limit, highest limit, highest days).
#: The ceilings are the till's own report caps (366 days), so folding these reads into one tool
#: widens nothing. ``pos:override`` marks the views that name a person who was short.
_CASHIER_VIEWS: dict[str, tuple[str, int, int, int]] = {
    "cash_in_out": ("orders:read", 10, 25, 366),
    "expected_vs_counted": ("pos:override", 10, 25, 366),
    "drawer_differences": ("pos:override", 8, 25, 366),
    "reconciliation_by_method": ("orders:read", 8, 25, 366),
    "shift_handovers": ("pos:override", 8, 25, 366),
    "daily_by_device": ("orders:read", 10, 25, 366),
    "sales_by_method": ("orders:read", 8, 25, 366),
}

#: What each view is called when the asker is refused, in words the model can relay.
_VIEW_WORDS: dict[str, str] = {
    "cash_in_out": "drawer movements",
    "expected_vs_counted": "who was short and by how much",
    "drawer_differences": "who was short and by how much",
    "reconciliation_by_method": "payment-method reconciliations",
    "shift_handovers": "who handed the drawer to whom",
    "daily_by_device": "daily sales per till",
    "sales_by_method": "sales per payment method",
}

CASHIER_VIEW_NAMES = tuple(_CASHIER_VIEWS)


class SICashierArgs(BaseModel):
    """One read of the till's cash records. ``view`` says which."""

    view: Literal[
        "cash_in_out",
        "expected_vs_counted",
        "drawer_differences",
        "reconciliation_by_method",
        "shift_handovers",
        "daily_by_device",
        "sales_by_method",
    ]
    #: The window. A till records a sale the moment it happens, so the window includes today
    #: up to now (the same rule si_shop view=cashier uses).
    days: int = Field(default=30, ge=1, le=366)
    #: The most rows to list; each view keeps its own default and ceiling.
    limit: int | None = Field(default=None, ge=1, le=25)


def _decimal(value: object) -> Decimal:
    """A figure the read model formatted, back as a Decimal so it can become a fact."""
    return Decimal(str(value))


def _limits(*extra: str) -> list[str]:
    return [
        "the window runs up to now, today included: the till records a sale the moment it happens",
        *extra,
    ]


def _cash_in_out(summary: dict, view: str) -> list[tuple]:
    net = _decimal(summary["net_cash"])
    return [
        ("cash_movements", summary["movement_count"], "count", {}),
        ("cash_in_total", _decimal(summary["cash_in_total"]), "money", {"direction": "in"}),
        ("cash_out_total", _decimal(summary["cash_out_total"]), "money", {"direction": "out"}),
        (
            "cash_net_moved",
            abs(net),
            "money",
            {"direction": "in" if net >= 0 else "out"},
        ),
    ]


def _expected_vs_counted(summary: dict, view: str) -> list[tuple]:
    return [
        ("shifts_closed", summary["shifts_closed"], "count", {}),
        ("shifts_counted", summary["shifts_counted"], "count", {}),
        ("cash_expected_total", _decimal(summary["total_expected"]), "money", {}),
        ("cash_counted_total", _decimal(summary["total_counted"]), "money", {}),
        ("cash_shortage_total", _decimal(summary["shortage_total"]), "money", {"kind": "shortage"}),
        ("cash_overage_total", _decimal(summary["overage_total"]), "money", {"kind": "overage"}),
    ]


def _difference_facts(rows: list[dict]) -> list[tuple]:
    """One shortage/overage fact per row, as a positive magnitude with its label."""
    numbers: list[tuple] = []
    for row in rows:
        kind = row.get("difference_kind")
        if kind not in ("shortage", "overage"):
            continue
        filters = {"session_id": row.get("session_id"), "kind": kind}
        if row.get("register_name"):
            filters["register"] = row["register_name"]
        if row.get("method"):
            filters["method"] = row["method"]
        numbers.append((f"drawer_{kind}", _decimal(row["difference"]), "money", filters))
        if row.get("counted_cash") is not None:
            numbers.append(
                (
                    "cash_counted",
                    _decimal(row["counted_cash"]),
                    "money",
                    {"session_id": row.get("session_id")},
                )
            )
    return numbers


def _drawer_differences(summary: dict, view: str) -> list[tuple]:
    return [
        ("shifts_with_a_difference", summary["shifts_with_a_difference"], "count", {}),
        ("cash_shortage_total", _decimal(summary["shortage_total"]), "money", {"kind": "shortage"}),
        ("cash_overage_total", _decimal(summary["overage_total"]), "money", {"kind": "overage"}),
        *_difference_facts(summary["differences"]),
    ]


def _reconciliation_by_method(summary: dict, view: str) -> list[tuple]:
    numbers: list[tuple] = [
        ("shifts_reconciled", summary["sessions"], "count", {}),
        ("cash_shortage_total", _decimal(summary["shortage_total"]), "money", {"kind": "shortage"}),
        ("cash_overage_total", _decimal(summary["overage_total"]), "money", {"kind": "overage"}),
    ]
    for row in summary["methods"]:
        scope = {"method": row["method"]}
        numbers.extend(
            [
                ("method_opening_float", _decimal(row["opening_float"]), "money", scope),
                ("method_expected", _decimal(row["expected"]), "money", scope),
                ("method_counted", _decimal(row["counted"]), "money", scope),
            ]
        )
        if row["difference_kind"] in ("shortage", "overage"):
            numbers.append(
                (
                    f"method_{row['difference_kind']}",
                    _decimal(row["difference"]),
                    "money",
                    scope,
                )
            )
    return numbers


def _shift_handovers(summary: dict, view: str) -> list[tuple]:
    numbers: list[tuple] = [
        ("handovers", summary["handover_count"], "count", {}),
        ("cash_shortage_total", _decimal(summary["shortage_total"]), "money", {"kind": "shortage"}),
        ("cash_overage_total", _decimal(summary["overage_total"]), "money", {"kind": "overage"}),
    ]
    for row in summary["handovers"]:
        scope = {"session_id": row["session_id"]}
        numbers.extend(
            [
                ("handover_expected", _decimal(row["expected_cash"]), "money", scope),
                ("handover_counted", _decimal(row["counted_cash"]), "money", scope),
            ]
        )
        if row["difference_kind"] in ("shortage", "overage"):
            numbers.append(
                (f"handover_{row['difference_kind']}", _decimal(row["difference"]), "money", scope)
            )
    return numbers


def _daily_by_device(summary: dict, view: str) -> list[tuple]:
    numbers: list[tuple] = [
        ("devices_with_sales", len(summary["devices"]), "count", {}),
        ("till_sales_total", _decimal(summary["sales_total"]), "money", {}),
        ("till_returns_total", _decimal(summary["returns_total"]), "money", {}),
        ("till_taxes_total", _decimal(summary["taxes_total"]), "money", {}),
    ]
    for row in summary["devices"]:
        scope = {"register_id": row["register_id"], "business_date": row["business_date"]}
        numbers.extend(
            [
                ("device_sessions", row["sessions"], "count", scope),
                ("device_invoices", row["invoices"], "count", scope),
                ("device_returns", row["returns"], "count", scope),
                ("device_sales_total", _decimal(row["sales_total"]), "money", scope),
                ("device_returns_total", _decimal(row["returns_total"]), "money", scope),
                ("device_taxes_total", _decimal(row["taxes_total"]), "money", scope),
            ]
        )
    return numbers


def _sales_by_method(summary: dict, view: str) -> list[tuple]:
    numbers: list[tuple] = [
        ("till_payments", summary["payment_count"], "count", {}),
        ("till_collected_total", _decimal(summary["collected_total"]), "money", {}),
    ]
    for row in summary["methods"]:
        numbers.append(
            ("method_collected", _decimal(row["collected"]), "money", {"method": row["method"]})
        )
    return numbers


#: When a view measured nothing at all: no movement, no closed shift, no hand-off, no device.
_EMPTY = {
    "cash_in_out": lambda s: s["movement_count"] == 0,
    "expected_vs_counted": lambda s: s["shifts_closed"] == 0,
    "drawer_differences": lambda s: s["shifts_closed"] == 0,
    "reconciliation_by_method": lambda s: s["sessions"] == 0,
    "shift_handovers": lambda s: s["handover_count"] == 0,
    "daily_by_device": lambda s: not s["devices"],
    "sales_by_method": lambda s: s["payment_count"] == 0,
}

#: How each view reads, how its figures become facts, and what a reader must be told.
_READERS = {
    "cash_in_out": (
        "cash_in_out",
        _cash_in_out,
        lambda: _limits(
            "each line is one reason and direction from the drawer ledger, totalled",
            "a cash sale is booked by the sell flow, so it is not counted twice",
        ),
    ),
    "expected_vs_counted": (
        "expected_vs_counted",
        _expected_vs_counted,
        lambda: _limits(
            "expected cash is recomputed from the opening float plus the drawer ledger, the "
            "same arithmetic the close uses, never a stored expectation",
            "a shift that did not count its drawer is listed as not counted, not as a perfect zero",
        ),
    ),
    "drawer_differences": (
        "drawer_differences",
        _drawer_differences,
        lambda: _limits(
            "a difference is a positive amount labelled shortage or overage, never a negative one",
            "only counted shifts are here; the biggest gap comes first",
        ),
    ),
    "reconciliation_by_method": (
        "reconciliation_by_method",
        _reconciliation_by_method,
        lambda: _limits(
            "one row per payment method the close reconciled; a method a shift never saw is absent",
            "the opening float is the float recorded per method when the shift opened",
        ),
    ),
    "shift_handovers": (
        "shift_handovers",
        _shift_handovers,
        lambda: _limits(
            "a hand-off is recorded when the drawer changes hands mid-shift; "
            "the shift keeps running",
            "the difference is what the count showed against the expected cash at that moment",
        ),
    ),
    "daily_by_device": (
        "daily_by_device",
        _daily_by_device,
        lambda: _limits(
            "read from the daily projection: sessions, invoices, returns, sales, returns and tax",
            "the projection's variance and per-method split are placeholders, so they are NOT "
            "read here: drawer_differences and reconciliation_by_method hold the real figures",
            "a day with no activity is absent, not zero",
        ),
    ),
    "sales_by_method": (
        "sales_by_method",
        _sales_by_method,
        lambda: _limits(
            "what each payment method collected on the till's sale receipts, never netted "
            "against refunds",
            "every collected payment counts, including one later refunded: the money was taken",
        ),
    ),
}


def _period_helpers():
    """The window and fact helpers, imported where they are used.

    ``tools`` imports this module while it registers, so a module-scope import back would be a
    cycle at import time. Inside the call, ``tools`` is fully loaded.
    """
    from app.applications.apparel.modules.ai.agents.sales_intelligence.tools import (
        _evidence_store,
        _resolve_window,
        _typed_facts,
    )

    return _resolve_window, _evidence_store, _typed_facts


async def si_cashier(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    view: str,
    days: int = 30,
    limit: int | None = None,
    context: dict | None = None,
) -> dict:
    """A thin router over the till's cash reads; each checks its own permission at run time."""
    if view not in _CASHIER_VIEWS:
        raise ValidationError(f"view must be one of: {', '.join(_CASHIER_VIEWS)} (got {view!r})")
    needs, default, ceiling, max_days = _CASHIER_VIEWS[view]
    require(needs, what=f"the till's {_VIEW_WORDS[view]}")
    if limit is None:
        limit = default
    elif limit > ceiling:
        raise ValidationError(f"limit for {view} can be at most {ceiling} (got {limit})")
    if days > max_days:
        raise ValidationError(f"days for {view} can be at most {max_days} (got {days})")

    resolve_window, evidence_store, typed_facts = _period_helpers()
    window = await resolve_window(session, tenant_id, days)
    # A till records its money the moment it moves, so the shared window (which stops at
    # midnight) would answer "nothing today" for a drawer that is open right now. Run the same
    # length of window up to now instead.
    window = window.model_copy(
        update={"start": window.start + timedelta(days=1), "end": datetime.now(UTC)}
    )
    key, fact_reader, limitations = _READERS[view]

    if view == "daily_by_device":
        summary = await reads.daily_by_device(
            session,
            tenant_id,
            start_day=window.start.date(),
            end_day=window.end.date(),
            limit=limit,
        )
    else:
        reader = getattr(reads, key)
        summary = await reader(session, tenant_id, start=window.start, end=window.end, limit=limit)
    empty = _EMPTY[view](summary)

    if empty:
        return {
            "capability": "cashier_reads",
            "view": view,
            "status": "no_data",
            "summary": {view: summary},
            "limitations": limitations(),
            "facts": [],
        }

    numbers = fact_reader(summary, view)
    facts = typed_facts(evidence_store(), window, "cashier_reads", numbers)
    return {
        "capability": "cashier_reads",
        "view": view,
        "status": "ok",
        "summary": {view: summary},
        "limitations": limitations(),
        "facts": facts,
    }
