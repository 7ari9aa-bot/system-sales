"""``si_cashier`` and the analytics read model behind it, without a database.

Two things are proven here, with a fake session that returns the rows Postgres would:

* each view returns the ORIGINAL numbers — the expected drawer cash is compared to the till's own
  arithmetic (``pos.tender.expected_drawer_cash``), the payment-method split to the statuses
  ``orders.money.COLLECTED_PAYMENT_STATUSES`` calls collected, and every money string to the
  cent-rounded figure the ledger rows add up to;
* a drawer difference is a POSITIVE MAGNITUDE labelled ``shortage`` or ``overage``: the evidence
  store drops negatives, so a shortage must never be returned as "-5".

Plus the gates: each view refuses an asker without its permission (fail closed with no permissions
at all), the handler's source passes the read-only guard that scans every ``si_*`` tool, and the
read model's own source contains no write statement.
"""

from __future__ import annotations

import textwrap
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errors import ValidationError
from app.modules.ai.agents.sales_intelligence import cashier as tool
from app.modules.ai.agents.sales_intelligence.permissions import asking_with
from app.modules.analytics import cashier_reads as reads
from app.modules.analytics.cashier_reads import (
    COLLECTED_PAYMENT_STATUSES,
    difference_side,
    money_str,
)
from app.modules.analytics.contracts import AnalysisPeriod, MaturityPolicy, MaturityStatus

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
SESSION = "22222222-2222-2222-2222-222222222222"
REGISTER = "33333333-3333-3333-3333-333333333333"
CASHIER = "44444444-4444-4444-4444-444444444444"
FROM_USER = "55555555-5555-5555-5555-555555555555"
TO_USER = "66666666-6666-6666-6666-666666666666"
DAY = datetime(2026, 11, 27, tzinfo=UTC)

#: The fixture shop, as the ledgers would hold it: one closed shift that came up 5.00 short.
OPENING_FLOAT = Decimal("100.00")
MOVEMENTS = [
    SimpleNamespace(
        session_id=SESSION, direction="in", reason="cash_sale", amount=Decimal("50.00")
    ),
    SimpleNamespace(
        session_id=SESSION, direction="out", reason="cash_drop", amount=Decimal("30.00")
    ),
]
COUNTED = Decimal("115.00")  # 120 expected -> a 5.00 shortage
EXPECTED = Decimal("120.00")


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    """Answers each read model statement with the rows the fixture shop would produce.

    The statements are matched on a fragment of their own SQL, so a read that starts selecting
    something else fails loudly here instead of silently returning nothing.
    """

    def __init__(self):
        self.calls: list[str] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append(sql)
        if "FROM pos_sessions s" in sql:
            return _Result(
                [
                    SimpleNamespace(
                        session_id=SESSION,
                        register_id=REGISTER,
                        register_name="Front till",
                        cashier_user_id=CASHIER,
                        opening_float=OPENING_FLOAT,
                        counted_cash=COUNTED,
                        opened_at=DAY,
                        closed_at=DAY + timedelta(hours=8),
                    )
                ]
            )
        if "FROM pos_cash_movements m" in sql and "created_at" in sql:
            return _Result(MOVEMENTS)
        if "FROM pos_cash_movements m" in sql:
            return _Result(MOVEMENTS)
        if "FROM pos_session_reconciliations c" in sql:
            return _Result(
                [
                    SimpleNamespace(
                        method="cash",
                        expected_amount=Decimal("120.00"),
                        counted_amount=Decimal("115.00"),
                        variance=Decimal("-5.00"),
                    ),
                    SimpleNamespace(
                        method="card",
                        expected_amount=Decimal("200.00"),
                        counted_amount=Decimal("200.00"),
                        variance=Decimal("0.00"),
                    ),
                ]
            )
        if "FROM pos_session_floats f" in sql:
            return _Result(
                [
                    SimpleNamespace(method="cash", amount=Decimal("100.00")),
                    SimpleNamespace(method="card", amount=Decimal("20.00")),
                ]
            )
        if "FROM pos_session_handovers h" in sql:
            return _Result(
                [
                    SimpleNamespace(
                        session_id=SESSION,
                        from_user_id=FROM_USER,
                        from_name="Sara",
                        to_user_id=TO_USER,
                        to_name="Omar",
                        expected_cash=Decimal("70.00"),
                        counted_cash=Decimal("65.00"),
                        variance=Decimal("-5.00"),
                        note="change for the evening",
                        created_at=DAY + timedelta(hours=4),
                    )
                ]
            )
        if "FROM pos_daily_sales d" in sql:
            return _Result(
                [
                    SimpleNamespace(
                        business_date=DAY.date(),
                        register_id=REGISTER,
                        register_name="Front till",
                        session_count=1,
                        invoice_count=3,
                        returns_count=1,
                        sales_total=Decimal("250.00"),
                        returns_total=Decimal("10.00"),
                        taxes_total=Decimal("12.50"),
                    )
                ]
            )
        if "FROM order_payments p" in sql:
            return _Result(
                [
                    SimpleNamespace(method="cash", amount=Decimal("50.00")),
                    SimpleNamespace(method="card", amount=Decimal("200.00")),
                ]
            )
        raise AssertionError(f"the read model ran an unexpected statement: {sql}")


# ------------------------------ the numbers are the originals -------------------------------


async def test_expected_cash_matches_the_till_s_own_arithmetic():
    from app.modules.pos.tender import expected_drawer_cash

    original = expected_drawer_cash(
        opening_float=OPENING_FLOAT,
        movements=[(m.direction, m.reason, m.amount) for m in MOVEMENTS],
    )
    assert reads.expected_cash(OPENING_FLOAT, MOVEMENTS) == original == EXPECTED


def test_expected_cash_agrees_with_the_till_for_every_movement_reason():
    """The same comparison over the reasons the ledger actually holds, and at the cent."""
    from app.modules.pos.tender import expected_drawer_cash

    cases = [
        (Decimal("0"), []),
        (Decimal("100.00"), [("in", "cash_sale", Decimal("50.00"))]),
        (
            Decimal("0"),
            [("in", "pay_in", Decimal("12.34")), ("in", "cash_sale", Decimal("0.01"))],
        ),
        (
            Decimal("250.00"),
            [("out", "pay_out", Decimal("0.10")), ("out", "float_adjust", Decimal("0.05"))],
        ),
        (
            Decimal("80.00"),
            [
                ("in", "cash_sale", Decimal("19.99")),
                ("out", "cash_refund", Decimal("9.99")),
                ("out", "cash_drop", Decimal("40.00")),
            ],
        ),
    ]
    for opening, movements in cases:
        rows = [SimpleNamespace(direction=d, reason=r, amount=a) for d, r, a in movements]
        assert reads.expected_cash(opening, rows) == expected_drawer_cash(
            opening_float=opening, movements=movements
        ), movements


def test_the_difference_sign_is_the_till_s_own_variance_read_as_a_magnitude():
    """``pos.tender.variance`` is counted minus expected; the read must not invent its own sign."""
    from app.modules.pos.tender import variance as till_variance

    cases = [
        (Decimal("115.00"), Decimal("120.00"), "shortage", Decimal("5.00")),
        (Decimal("125.00"), Decimal("120.00"), "overage", Decimal("5.00")),
        (Decimal("120.00"), Decimal("120.00"), "matched", Decimal("0.00")),
    ]
    for counted, expected, label, magnitude in cases:
        signed = till_variance(counted=counted, expected=expected)
        assert difference_side(signed) == (label, magnitude)
        # the magnitude is the absolute value, so a shortage is never quotable as "-5"
        assert difference_side(signed)[1] == abs(signed)


async def test_sales_by_method_totals_equal_what_the_till_settled_at_sale_time():
    """The per-method takings are the tender lines the sale settled, added back up."""
    from app.modules.pos.tender import TenderLine, settle

    settled = settle(
        [TenderLine("cash", Decimal("50.00")), TenderLine("card", Decimal("200.00"))],
        total=Decimal("250.00"),
        allowed_methods=("cash", "card", "wallet", "bank_transfer"),
    )
    summary = await reads.sales_by_method(
        FakeSession(), TENANT, start=DAY, end=DAY + timedelta(days=1), limit=8
    )
    from_read = {row["method"]: Decimal(row["collected"]) for row in summary["methods"]}
    assert from_read == dict(settled.by_method)
    assert Decimal(summary["collected_total"]) == settled.paid


async def test_expected_vs_counted_reports_the_drawer_as_the_close_recorded_it():
    summary = await reads.expected_vs_counted(
        FakeSession(), TENANT, start=DAY, end=DAY + timedelta(days=1), limit=10
    )
    assert summary["shifts_closed"] == 1
    assert summary["shifts_counted"] == 1
    assert summary["total_expected"] == "120.00"
    assert summary["total_counted"] == "115.00"
    assert summary["shortage_total"] == "5.00"
    assert summary["overage_total"] == "0.00"
    shift = summary["shifts"][0]
    assert shift["expected_cash"] == "120.00"
    assert shift["counted_cash"] == "115.00"
    # the negative variance is NOT returned as a negative number
    assert shift["difference"] == "5.00"
    assert shift["difference_kind"] == "shortage"


async def test_drawer_differences_lists_only_the_shift_that_did_not_match():
    summary = await reads.drawer_differences(
        FakeSession(), TENANT, start=DAY, end=DAY + timedelta(days=1), limit=8
    )
    assert summary["shifts_closed"] == 1
    assert summary["shifts_with_a_difference"] == 1
    assert summary["shortage_total"] == "5.00"
    assert summary["differences"][0]["difference"] == "5.00"
    assert summary["differences"][0]["difference_kind"] == "shortage"
    assert summary["differences"][0]["cashier_user_id"] == CASHIER


async def test_cash_in_out_totals_each_direction_from_the_ledger():
    summary = await reads.cash_in_out(
        FakeSession(), TENANT, start=DAY, end=DAY + timedelta(days=1), limit=10
    )
    assert summary["movement_count"] == 2
    assert summary["cash_in_total"] == "50.00"
    assert summary["cash_out_total"] == "30.00"
    assert summary["net_cash"] == "20.00"
    reasons = {line["reason"]: line for line in summary["by_reason"]}
    assert reasons["cash_sale"]["total"] == "50.00"
    assert reasons["cash_drop"]["direction"] == "out"


async def test_reconciliation_by_method_carries_the_float_and_the_shortage():
    summary = await reads.reconciliation_by_method(
        FakeSession(), TENANT, start=DAY, end=DAY + timedelta(days=1), limit=8
    )
    methods = {row["method"]: row for row in summary["methods"]}
    assert methods["cash"]["opening_float"] == "100.00"
    assert methods["cash"]["expected"] == "120.00"
    assert methods["cash"]["counted"] == "115.00"
    assert methods["cash"]["difference"] == "5.00"
    assert methods["cash"]["difference_kind"] == "shortage"
    assert methods["card"]["difference_kind"] == "matched"
    assert summary["shortage_total"] == "5.00"


async def test_shift_handovers_names_both_people_and_the_count():
    summary = await reads.shift_handovers(
        FakeSession(), TENANT, start=DAY, end=DAY + timedelta(days=1), limit=8
    )
    assert summary["handover_count"] == 1
    handover = summary["handovers"][0]
    assert (handover["from_name"], handover["to_name"]) == ("Sara", "Omar")
    assert handover["expected_cash"] == "70.00"
    assert handover["counted_cash"] == "65.00"
    assert handover["difference"] == "5.00"
    assert handover["difference_kind"] == "shortage"
    assert summary["shortage_total"] == "5.00"


async def test_daily_by_device_reads_the_projection_and_never_its_placeholders():
    summary = await reads.daily_by_device(
        FakeSession(), TENANT, start_day=DAY.date(), end_day=DAY.date(), limit=10
    )
    device = summary["devices"][0]
    assert device["register_name"] == "Front till"
    assert (device["sessions"], device["invoices"], device["returns"]) == (1, 3, 1)
    assert device["sales_total"] == "250.00"
    assert device["returns_total"] == "10.00"
    assert device["taxes_total"] == "12.50"
    assert summary["sales_total"] == "250.00"
    # the projection's variance_total / by_method are placeholders: not read, not reported
    assert not {"variance", "variance_total", "by_method"} & set(device)


async def test_sales_by_method_matches_the_collected_statuses_the_orders_module_uses():
    from app.modules.orders.money import COLLECTED_PAYMENT_STATUSES as ORDERS_STATUSES

    assert COLLECTED_PAYMENT_STATUSES == ORDERS_STATUSES
    summary = await reads.sales_by_method(
        FakeSession(), TENANT, start=DAY, end=DAY + timedelta(days=1), limit=8
    )
    methods = {row["method"]: row["collected"] for row in summary["methods"]}
    assert methods == {"card": "200.00", "cash": "50.00"}
    assert summary["collected_total"] == "250.00"


# ------------------------------ the tool over the read model ---------------------------------


def _period() -> AnalysisPeriod:
    return AnalysisPeriod(
        start=DAY,
        end=DAY + timedelta(days=1),
        timezone="UTC",
        attribution_basis="issued_at",
        maturity_policy=MaturityPolicy(kind="immediate"),
        maturity_status=MaturityStatus.MATURE,
        data_as_of=DAY,
    )


@pytest.fixture
def fake_window(monkeypatch):
    """The tool resolves its window through analytics (a DB read); here it is fixed."""
    from app.modules.ai.agents.sales_intelligence.tools import _evidence_store, _typed_facts

    async def resolve_window(session, tenant_id, days):
        return _period()

    monkeypatch.setattr(
        tool, "_period_helpers", lambda: (resolve_window, _evidence_store, _typed_facts)
    )


@pytest.mark.parametrize(
    ("view", "permission"),
    [
        ("cash_in_out", "orders:read"),
        ("expected_vs_counted", "pos:override"),
        ("drawer_differences", "pos:override"),
        ("reconciliation_by_method", "orders:read"),
        ("shift_handovers", "pos:override"),
        ("daily_by_device", "orders:read"),
        ("sales_by_method", "orders:read"),
    ],
)
async def test_each_view_checks_its_own_permission_at_run_time(fake_window, view, permission):
    with asking_with({permission}):
        result = await tool.si_cashier(FakeSession(), TENANT, view=view)
    assert result["status"] == "ok"
    assert result["capability"] == "cashier_reads"
    assert result["summary"][view]


@pytest.mark.parametrize("view", list(tool.CASHIER_VIEW_NAMES))
async def test_no_permissions_at_all_refuses_every_view(fake_window, view):
    """Fail CLOSED: an unknown asker holds nothing, so every view refuses."""
    with asking_with(None):
        with pytest.raises(ValidationError):
            await tool.si_cashier(FakeSession(), TENANT, view=view)


async def test_orders_read_cannot_read_who_was_short(fake_window):
    """The three views that name a cashier who was short need pos:override."""
    for view in ("expected_vs_counted", "drawer_differences", "shift_handovers"):
        with asking_with({"orders:read"}):
            with pytest.raises(ValidationError) as refused:
                await tool.si_cashier(FakeSession(), TENANT, view=view)
        assert "not allowed" in str(refused.value)


async def test_an_unknown_view_is_refused_with_the_list(fake_window):
    with asking_with({"orders:read", "pos:override"}):
        with pytest.raises(ValidationError) as refused:
            await tool.si_cashier(FakeSession(), TENANT, view="drawer")
    assert "cash_in_out" in str(refused.value)


async def test_the_tool_registers_the_numbers_as_facts_never_as_negatives(fake_window):
    with asking_with({"pos:override"}):
        result = await tool.si_cashier(FakeSession(), TENANT, view="drawer_differences")
    facts = {fact["metric"]: fact for fact in result["facts"]}
    assert facts["drawer_shortage"]["value"] == "5.00"
    assert facts["drawer_shortage"]["filters"]["kind"] == "shortage"
    assert facts["cash_shortage_total"]["value"] == "5.00"
    assert all(Decimal(fact["value"]) >= 0 for fact in result["facts"])


async def test_the_tool_returns_a_shortage_as_a_positive_magnitude(fake_window):
    with asking_with({"pos:override"}):
        result = await tool.si_cashier(FakeSession(), TENANT, view="expected_vs_counted")
    shift = result["summary"]["expected_vs_counted"]["shifts"][0]
    assert shift["difference"] == "5.00"
    assert shift["difference_kind"] == "shortage"
    assert "-5" not in str(result["summary"])


def test_difference_side_is_the_one_place_that_decides_shortage_or_overage():
    assert difference_side(Decimal("-5.00")) == ("shortage", Decimal("5.00"))
    assert difference_side(Decimal("2.50")) == ("overage", Decimal("2.50"))
    assert difference_side(Decimal("0")) == ("matched", Decimal("0.00"))
    assert money_str(Decimal("1234.5")) == "1234.50"


# ------------------------------ the guards --------------------------------------------------


def test_the_handler_passes_the_read_only_guard():
    """The real guard's own scanner, run over this tool's handler source."""
    from tests.test_si_tools_are_read_only import SERVICE_IMPORT, WRITE_API, WRITE_SQL, _source_of

    source = _source_of("si_cashier")
    assert WRITE_SQL.search(source) is None
    assert WRITE_API.search(source) is None
    assert SERVICE_IMPORT.search(source) is None


def test_the_read_model_contains_no_write_and_no_pos_import():
    import ast

    from tests.test_si_tools_are_read_only import WRITE_SQL

    source = textwrap.dedent(open(reads.__file__, encoding="utf-8").read())
    assert WRITE_SQL.search(source) is None
    # no import of the till's module, at any scope: this read model exists to avoid that edge
    imported = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not [name for name in imported if name.split(".")[:3] == ["app", "modules", "pos"]]
    # the tables it reads, and none of the projection's placeholder columns
    for table in (
        "pos_sessions",
        "pos_session_floats",
        "pos_cash_movements",
        "pos_session_reconciliations",
        "pos_session_handovers",
        "pos_daily_sales",
        "order_payments",
    ):
        assert table in source


def test_the_tool_is_registered_low_risk_and_known_to_the_risk_engine():
    import app.modules.ai.agents.sales_intelligence.tools as si
    from app.core.risk import known_actions
    from app.modules.ai.tools import TOOLS

    si.register_si_tools()
    assert "si_cashier" in si.SI_TOOLS
    assert TOOLS["si_cashier"].risk_level == "LOW"
    assert "si_cashier" in known_actions()
    # the tool points the model at tools that exist
    assert "si_shop view=cashier" in TOOLS["si_cashier"].description
