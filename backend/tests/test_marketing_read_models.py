"""Marketing's dashboard must stop re-deriving numbers the canonical read
models already own (gap register M10 / M3 / M5, spec §167).

Three of its figures were a SECOND implementation of a rule `analytics/service.py`
had already settled, and each divergence was a merchant-visible bug:

* ``daily_orders`` truncated on ``Order.created_at`` with a bare ``date_trunc``
  — a UTC-midnight bucket, so a 23:30 sale lands on the wrong merchant day.
* ``dashboard_summary["low_stock"]`` counted ``on_hand - reserved <= 2``, which
  folds EMPTY shelves into "low stock" and makes the alert noise.
* ``orders_summary["revenue"]`` summed ``orders.grand_total`` (gross of any
  partial refund) and labelled it plain ``revenue``, while the analytics
  dashboard emitted ``gross_revenue`` / ``net_revenue`` for the same window.

The fix is delegation, so these tests pin the DELEGATION and the field NAMES
rather than a re-derivation of the SQL. Money maths is asserted to happen in the
canonical read model: marketing only formats money for the wire, as a Decimal
STRING (ADR-001/§47 — the same shape ``orders/router.py`` ships for
``grand_total``), and the currency label is the tenant's, echoed from the read
model, never a literal.

Pure cases run with no database at all. DB cases seed payments/refunds at
explicit instants and skip locally when ``DATABASE_URL_APP_ADMIN`` is unset.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.analytics import service as analytics_service
from app.modules.customers.service import CustomerService
from app.modules.marketing import analytics
from app.modules.marketing import router as marketing_router
from app.modules.orders.models import Order, OrderPayment, Refund
from app.modules.platform.metrics import MetricRegistry

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")

#: The AMOUNT keys each marketing read model emits. ADR-001/§47: these cross the
#: JSON boundary as Decimal strings, because a client that parses money as a
#: float64 cannot add a column of them up and still trust the cents. Counts
#: (``orders_count``, ``conversions``), ratios (``budget_roas``) and labels
#: (``currency``, ``day``) are not amounts and keep their own types.
_MONEY_KEYS_SUMMARY = (
    "gross_revenue",
    "refunded_amount",
    "net_revenue",
    "refund_excess",
    "gross_aov",
    "net_aov",
)
_MONEY_KEYS_DAILY = ("gross_revenue", "refunded_amount", "net_revenue", "refund_excess")


# --------------------------------------------------------------------------
# Harness: marketing must issue NO money/day-bucketing SQL of its own
# --------------------------------------------------------------------------


class _NoSqlSession:
    """Any query from these read models means marketing re-derived the rule.

    The canonical implementations live in ``app/modules/analytics/service.py``;
    a session that refuses to answer proves marketing asked for nothing.
    """

    async def execute(self, *_args, **_kwargs):
        raise AssertionError(
            "marketing analytics ran its own query for a number the canonical "
            "read model already computes"
        )


class _ZeroCountsSession:
    """Answers the dashboard's plain row counts with 0, nothing else."""

    def __init__(self) -> None:
        self.stmts: list[object] = []

    async def execute(self, stmt, *_args, **_kwargs):
        self.stmts.append(stmt)
        return self

    def scalar_one(self) -> int:
        return 0


def _canonical_rows() -> list[dict]:
    """One merchant day: 70.00 collected, 20.00 refunded, 60.00 owed back extra."""
    return [
        {
            "day": "2026-03-15",
            "gross_revenue": Decimal("70.00"),
            "refunded_amount": Decimal("20.00"),
            "net_revenue": Decimal("50.00"),
            "refund_excess": Decimal("0.00"),
            "orders_count": 3,
        }
    ]


def _zero_money(monkeypatch) -> None:
    """Neutralise the money half so a stock test only ever tests the stock half."""

    async def fake(session, tenant_id, *, since, until, timezone=None):
        return {
            "currency": "EGP",
            "timezone": "UTC",
            "gross_revenue": Decimal("0.00"),
            "refunded_amount": Decimal("0.00"),
            "net_revenue": Decimal("0.00"),
            "refund_excess": Decimal("0.00"),
            "orders_count": 0,
            "gross_aov": Decimal("0.00"),
            "net_aov": Decimal("0.00"),
        }

    monkeypatch.setattr(analytics_service, "revenue_summary", fake)


# --------------------------------------------------------------------------
# 1. daily_orders — the merchant day, not UTC midnight
# --------------------------------------------------------------------------


async def test_daily_orders_delegates_to_the_merchant_day_series(monkeypatch) -> None:
    """The bucketing rule has ONE implementation (gap M10)."""
    seen: dict = {}

    async def fake(session, tenant_id, *, since, until, timezone=None):
        seen.update(tenant_id=tenant_id, since=since, until=until, timezone=timezone)
        return _canonical_rows()

    monkeypatch.setattr(analytics_service, "daily_revenue_series", fake)

    rows = await analytics.daily_orders(_NoSqlSession(), TENANT, days=30)

    assert seen["tenant_id"] == TENANT
    assert seen["until"] - seen["since"] == timedelta(days=30)
    assert rows[0]["day"] == "2026-03-15"
    # The count keeps its name; the money never leaves as a bare "revenue".
    assert rows[0]["orders"] == 3
    assert isinstance(rows[0]["orders"], int)
    # Money is a Decimal string on the wire (ADR-001) — never a float64 a client
    # has to trust its JSON parser to reproduce.
    assert rows[0]["gross_revenue"] == "70.00"
    assert all(isinstance(rows[0][k], str) for k in _MONEY_KEYS_DAILY), rows[0]
    assert Decimal(rows[0]["gross_revenue"]) == Decimal("70.00")
    assert Decimal(rows[0]["net_revenue"]) == Decimal("50.00")
    assert Decimal(rows[0]["refunded_amount"]) == Decimal("20.00")
    assert Decimal(rows[0]["refund_excess"]) == Decimal("0.00")
    assert "revenue" not in rows[0]


async def test_a_day_that_refunded_more_than_it_collected_ships_both_halves(
    monkeypatch,
) -> None:
    """The floored-away money is a string too, so the day still adds up.

    gross - refunded would be -10.00, net is floored to 0.00 and the 10.00 that
    could not be subtracted travels as ``refund_excess``; all three are amounts,
    so all three are Decimal strings.
    """

    async def fake(session, tenant_id, *, since, until, timezone=None):
        return [
            {
                "day": "2026-03-15",
                "gross_revenue": Decimal("70.00"),
                "refunded_amount": Decimal("80.00"),
                "net_revenue": Decimal("0.00"),
                "refund_excess": Decimal("10.00"),
                "orders_count": 3,
            }
        ]

    monkeypatch.setattr(analytics_service, "daily_revenue_series", fake)
    row = (await analytics.daily_orders(_NoSqlSession(), TENANT, days=30))[0]

    assert row["net_revenue"] == "0.00"
    assert row["refund_excess"] == "10.00"
    assert Decimal(row["gross_revenue"]) - Decimal(row["refunded_amount"]) == Decimal(
        row["net_revenue"]
    ) - Decimal(row["refund_excess"])


async def test_daily_orders_forwards_the_callers_zone(monkeypatch) -> None:
    """A caller-resolved zone that marketing drops is a silent UTC bucket again."""
    forwarded: list = []

    async def fake(session, tenant_id, *, since, until, timezone=None):
        forwarded.append(timezone)
        return []

    monkeypatch.setattr(analytics_service, "daily_revenue_series", fake)
    await analytics.daily_orders(_NoSqlSession(), TENANT, days=7, timezone="Asia/Dubai")
    assert forwarded == ["Asia/Dubai"]


def test_daily_orders_exposes_the_zone_as_a_parameter() -> None:
    assert "timezone" in inspect.signature(analytics.daily_orders).parameters


def test_daily_orders_route_publishes_the_zone_parameter() -> None:
    """The rule is only honoured if it can reach the wire."""
    params = create_app().openapi()["paths"]["/api/v1/analytics/daily-orders"]["get"]["parameters"]
    assert "timezone" in {p["name"] for p in params}


# --------------------------------------------------------------------------
# 2. dashboard_summary — an empty shelf is not "low stock"
# --------------------------------------------------------------------------


async def test_dashboard_separates_low_stock_from_out_of_stock(monkeypatch) -> None:
    """``available <= 2`` folded zero balances into the low-stock alert (M10)."""
    asked: list = []

    async def fake(
        session, tenant_id, *, low_stock_threshold=analytics_service.LOW_STOCK_THRESHOLD
    ):
        asked.append((tenant_id, low_stock_threshold))
        return {
            "low_stock_threshold": 2,
            "low_stock_count": 1,
            "out_of_stock_count": 7,
            "healthy_count": 42,
        }

    monkeypatch.setattr(analytics_service, "stock_health", fake)
    _zero_money(monkeypatch)
    session = _ZeroCountsSession()

    summary = await analytics.dashboard_summary(session, TENANT)

    assert asked == [(TENANT, 2)]
    assert summary["low_stock_count"] == 1
    assert summary["out_of_stock_count"] == 7
    # The old single number claimed both, so neither name may survive alone.
    assert "low_stock" not in summary


# --------------------------------------------------------------------------
# 3. orders_summary — a money figure must name its own family
# --------------------------------------------------------------------------


async def test_orders_summary_never_labels_a_number_plain_revenue(monkeypatch) -> None:
    captured: dict = {}

    async def fake(session, tenant_id, *, since, until, timezone=None):
        captured.update(since=since, until=until)
        return {
            "currency": "SAR",
            "timezone": "UTC",
            "since": since.isoformat(),
            "until": until.isoformat(),
            "gross_revenue": Decimal("100.00"),
            "refunded_amount": Decimal("40.00"),
            "net_revenue": Decimal("60.00"),
            "refund_excess": Decimal("0.00"),
            "orders_count": 2,
            "gross_aov": Decimal("50.00"),
            "net_aov": Decimal("30.00"),
        }

    monkeypatch.setattr(analytics_service, "revenue_summary", fake)

    summary = await analytics.orders_summary(_NoSqlSession(), TENANT, days=30)

    assert captured["until"] - captured["since"] == timedelta(days=30)
    for key in ("revenue", "aov"):
        assert key not in summary, f"{key} is ambiguous — say gross or net"
    assert summary["orders_count"] == 2
    assert isinstance(summary["orders_count"], int), "a count is not money"
    for key in _MONEY_KEYS_SUMMARY:
        assert isinstance(summary[key], str), f"{key} is an amount: it ships as a string"
        assert Decimal(summary[key]) == Decimal(summary[key])
    assert Decimal(summary["gross_revenue"]) == Decimal("100.00")
    assert Decimal(summary["net_revenue"]) == Decimal("60.00")
    assert Decimal(summary["refunded_amount"]) == Decimal("40.00")
    assert Decimal(summary["refund_excess"]) == Decimal("0.00")
    assert Decimal(summary["gross_aov"]) == Decimal("50.00")
    assert Decimal(summary["net_aov"]) == Decimal("30.00")
    # gross - refunded and net + excess describe the same window: the money the
    # window could not subtract is on the wire, not dropped.
    assert Decimal(summary["gross_revenue"]) - Decimal(summary["refunded_amount"]) == (
        Decimal(summary["net_revenue"]) - Decimal(summary["refund_excess"])
    )
    assert all(not isinstance(v, Decimal) for v in summary.values()), (
        "marketing's contract is Decimal-free JSON"
    )


async def test_orders_summary_carries_the_tenants_currency_not_a_literal(
    monkeypatch,
) -> None:
    """§47: one currency per tenant, read from the tenant row."""

    async def fake(session, tenant_id, *, since, until, timezone=None):
        return {
            "currency": "AED",
            "timezone": "UTC",
            "gross_revenue": Decimal("0.00"),
            "refunded_amount": Decimal("0.00"),
            "net_revenue": Decimal("0.00"),
            "refund_excess": Decimal("0.00"),
            "orders_count": 0,
            "gross_aov": Decimal("0.00"),
            "net_aov": Decimal("0.00"),
        }

    monkeypatch.setattr(analytics_service, "revenue_summary", fake)
    summary = await analytics.orders_summary(_NoSqlSession(), TENANT)
    assert summary["currency"] == "AED"


async def test_dashboard_orders_block_is_the_same_named_pair(monkeypatch) -> None:
    """The dashboard embeds the summary — it cannot re-ambiguate it."""

    async def fake(session, tenant_id, *, since, until, timezone=None):
        return {
            "currency": "EGP",
            "timezone": "UTC",
            "gross_revenue": Decimal("10.00"),
            "refunded_amount": Decimal("0.00"),
            "net_revenue": Decimal("10.00"),
            "refund_excess": Decimal("0.00"),
            "orders_count": 1,
            "gross_aov": Decimal("10.00"),
            "net_aov": Decimal("10.00"),
        }

    async def health(session, tenant_id, *, low_stock_threshold=2):
        return {
            "low_stock_threshold": 2,
            "low_stock_count": 0,
            "out_of_stock_count": 0,
            "healthy_count": 0,
        }

    monkeypatch.setattr(analytics_service, "revenue_summary", fake)
    monkeypatch.setattr(analytics_service, "stock_health", health)
    summary = await analytics.dashboard_summary(_ZeroCountsSession(), TENANT)

    assert summary["orders"]["gross_revenue"] == "10.00"
    assert isinstance(summary["orders"]["gross_revenue"], str)
    assert "revenue" not in summary["orders"]


# --------------------------------------------------------------------------
# 4. One implementation per rule, statically
# --------------------------------------------------------------------------


def _code_only(path: pathlib.Path) -> str:
    """The module's executable text, docstrings dropped.

    Prose is allowed to name the bug it explains; code is not allowed to
    re-implement the rule the canonical read model owns.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    containers = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if isinstance(node, containers):
            head = node.body[:1]
            if (
                head
                and isinstance(head[0], ast.Expr)
                and isinstance(head[0].value, ast.Constant)
                and isinstance(head[0].value.value, str)
            ):
                node.body.pop(0)
                if not node.body:
                    node.body.append(ast.Pass())
    return ast.unparse(tree)


def test_marketing_holds_no_second_copy_of_the_day_or_stock_rule() -> None:
    """A second trunc expression / second stock band is how they drift again."""
    code = _code_only(pathlib.Path(analytics.__file__))
    assert "date_trunc" not in code, "day bucketing belongs to the canonical read model"
    assert "InventoryBalance" not in code, "stock bands belong to stock_health()"
    assert "grand_total" not in code, "order money is payment-based, not order-based"


def test_money_is_never_cast_to_float_in_the_read_models() -> None:
    """ADR-001: the only float leaving marketing is a RATIO.

    A ``float(`` anywhere else in this module is an amount reaching a client as a
    float64 again — the failure the Decimal-string wire removes. ``_ratio`` is the
    one exemption, and a ROAS is a ratio, not money.
    """
    tree = ast.parse(pathlib.Path(analytics.__file__).read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or node.name == "_ratio":
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "float":
                offenders.append(f"{node.name}():line {call.lineno}")
    assert not offenders, "amount cast to float for the wire: " + ", ".join(offenders)


def test_the_marketing_router_emits_no_amount_as_a_float() -> None:
    """The route layer is half the contract: campaign budget, conversion value and
    credited attribution all cross there too.
    """
    source = pathlib.Path(marketing_router.__file__).read_text(encoding="utf-8")
    assert "float(" not in source, "the router casts an amount back to float"


# --------------------------------------------------------------------------
# 5. The registry must describe the code that exists (item 4)
# --------------------------------------------------------------------------


def test_roas_definition_names_a_planned_budget_and_says_no_spend_feed_exists() -> None:
    roas = MetricRegistry.get("roas")
    assert roas is not None
    definition = roas.definition.lower()
    # campaigns.budget is PLANNED money; calling it "ad spend" was the lie.
    assert "planned" in definition
    assert "burned" in definition, "spend means money actually burned"
    assert roas.filters.get("spend_source") != "campaigns.budget"
    assert roas.filters.get("planned_budget_source") == "campaigns.budget"


def test_net_revenue_definition_carries_the_floor_and_the_excess_rule() -> None:
    net = MetricRegistry.get("net_revenue")
    assert net is not None
    definition = net.definition.lower()
    assert "floor" in definition and "zero" in definition
    assert "refund_excess" in net.definition, "the floored-away money is named on the wire"


# --------------------------------------------------------------------------
# DB cases — CI (they skip locally without DATABASE_URL_APP_ADMIN)
# --------------------------------------------------------------------------


async def _collected(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    amount: str,
    paid_at: datetime,
    status: str = "completed",
) -> OrderPayment:
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:12]}", name="Buyer"
    )
    order = Order(
        tenant_id=tenant_id,
        customer_id=customer.id,
        number=f"SO-{uuid.uuid4().hex[:10].upper()}",
        status=status,
        grand_total=Decimal(amount),
        placed_at=paid_at,
    )
    db.add(order)
    await db.flush()
    payment = OrderPayment(
        tenant_id=tenant_id,
        order_id=order.id,
        method="cash",
        status="captured",
        amount=Decimal(amount),
        paid_at=paid_at,
    )
    db.add(payment)
    await db.flush()
    return payment


async def _refunded(
    db: AsyncSession, tenant_id: uuid.UUID, payment: OrderPayment, *, amount: str, at: datetime
) -> Refund:
    refund = Refund(
        tenant_id=tenant_id,
        payment_id=payment.id,
        amount=Decimal(amount),
        status="processed",
        processed_at=at,
    )
    db.add(refund)
    await db.flush()
    return refund


async def test_daily_orders_buckets_a_late_utc_sale_into_the_merchant_day(
    db: AsyncSession, tenant_ctx
) -> None:
    """The register's exact bug: 23:30 UTC is 03:30 the NEXT day in UTC+4."""
    tid = tenant_ctx.tenant_id
    # Yesterday 23:30 UTC — always inside a 30-day window, never in the future.
    instant = (datetime.now(UTC) - timedelta(days=1)).replace(
        hour=23, minute=30, second=0, microsecond=0
    )
    await _collected(db, tid, amount="70.00", paid_at=instant)

    utc_rows = await analytics.daily_orders(db, tid, days=30, timezone="UTC")
    local_rows = await analytics.daily_orders(db, tid, days=30, timezone="Asia/Dubai")

    utc_day = instant.astimezone(UTC).date().isoformat()
    dubai_day = (instant + timedelta(hours=4)).date().isoformat()
    assert {r["day"] for r in utc_rows} == {utc_day}
    assert {r["day"] for r in local_rows} == {dubai_day}
    assert dubai_day != utc_day
    assert local_rows[0]["orders"] == 1
    assert Decimal(local_rows[0]["gross_revenue"]) == Decimal("70.00")


async def test_orders_summary_agrees_with_the_analytics_dashboard(
    db: AsyncSession, tenant_ctx
) -> None:
    """Two screens, one number — the whole reason the registry exists (§167)."""
    tid = tenant_ctx.tenant_id
    now = datetime.now(UTC)
    payment = await _collected(db, tid, amount="100.00", paid_at=now - timedelta(hours=5))
    await _refunded(db, tid, payment, amount="40.00", at=now - timedelta(hours=4))

    marketing = await analytics.orders_summary(db, tid, days=30)
    canonical = await analytics_service.revenue_summary(
        db, tid, since=now - timedelta(days=30), until=now
    )

    # Two screens, ONE number, compared exactly: the wire string re-reads as the
    # Decimal the canonical read model returned, so gross cannot differ from the
    # dashboard by even a rounding step. (The float wire this replaces could only
    # ever be compared with a tolerance.)
    assert Decimal(marketing["gross_revenue"]) == canonical["gross_revenue"]
    assert Decimal(marketing["net_revenue"]) == canonical["net_revenue"]
    assert Decimal(marketing["refunded_amount"]) == canonical["refunded_amount"]
    assert Decimal(marketing["gross_revenue"]) == Decimal("100.00")
    assert Decimal(marketing["net_revenue"]) == Decimal("60.00")
    assert Decimal(marketing["refunded_amount"]) == Decimal("40.00")
    assert marketing["currency"] == canonical["currency"]
    assert marketing["orders_count"] == 1


async def test_an_order_refunded_wholesale_still_shows_its_captured_money(
    db: AsyncSession, tenant_ctx
) -> None:
    """The old marketing window dropped ``refunded`` orders entirely, so gross
    revenue was neither gross nor comparable to the analytics dashboard: the
    money was captured, then it went back as a refund the net figure subtracts."""
    tid = tenant_ctx.tenant_id
    now = datetime.now(UTC)
    payment = await _collected(
        db, tid, amount="120.00", paid_at=now - timedelta(hours=6), status="refunded"
    )
    await _refunded(db, tid, payment, amount="120.00", at=now - timedelta(hours=3))

    summary = await analytics.orders_summary(db, tid, days=30)
    assert Decimal(summary["gross_revenue"]) == Decimal("120.00")
    assert Decimal(summary["net_revenue"]) == Decimal("0.00")
    assert Decimal(summary["refunded_amount"]) == Decimal("120.00")


async def test_dashboard_separates_an_empty_shelf_from_a_low_one(
    db: AsyncSession, tenant_ctx
) -> None:
    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.models import InventoryBalance, Warehouse

    tid = tenant_ctx.tenant_id
    warehouse = Warehouse(
        tenant_id=tid, name=f"WH-{uuid.uuid4().hex[:6]}", code=f"W-{uuid.uuid4().hex[:6].upper()}"
    )
    db.add(warehouse)
    await db.flush()

    for on_hand, reserved in ((0, 0), (2, 2), (3, 2), (50, 0)):
        product = await CatalogService.create_product(
            db, tid, title=f"P-{uuid.uuid4().hex[:8]}", slug=f"p-{uuid.uuid4().hex[:8]}"
        )
        variant = await CatalogService.add_variant(db, tid, product.id, price="10.00")
        db.add(
            InventoryBalance(
                tenant_id=tid,
                warehouse_id=warehouse.id,
                variant_id=variant.id,
                on_hand=on_hand,
                reserved=reserved,
            )
        )
    await db.flush()

    summary = await analytics.dashboard_summary(db, tid)
    assert summary["low_stock_count"] == 1
    assert summary["out_of_stock_count"] == 2
    assert summary["low_stock_threshold"] == analytics_service.LOW_STOCK_THRESHOLD
    assert "low_stock" not in summary
