"""``GET /api/v1/analytics/overview`` — the analytics screen's one call (T3).

The defect this file exists for
-------------------------------
``frontend/src/app/(dash)/analytics/page.tsx`` fetched ``/api/v1/analytics/overview``
and **no such route existed anywhere under ``app/``**, so the screen hit a 404 and
rendered its error state on every single visit. ``as any`` on the response is why
nothing complained: the type checked a contract the server never published.

What is pinned here (all DB-free unless the test says otherwise)
----------------------------------------------------------------
1. The route is mounted and publishes its window parameters — a handler nobody
   can reach is the same bug in a different costume.
2. The route computes NOTHING itself. Every figure is delegated to the canonical
   readers in ``analytics/service.py``, which is the module that owns metric
   SQL since Wave-4 M11. A second SELECT for gross/net in a router is how two
   screens disagree by a refund.
3. Money leaves as a Decimal STRING. FastAPI's default encoder turns a Decimal
   into a float, so the route must stringify explicitly — the same rule
   ``orders/router.py`` follows for ``grand_total``. The named money families
   (``gross_``/``net_``/``refunded_``/``refund_excess``) keep their names, so a
   caller cannot read one as the other (ADR-053).
4. A bad IANA zone is rejected before any query runs, and the caller's zone is
   forwarded to the readers rather than dropped on the floor (gap M10).
5. An empty shelf is reported as ``out_of_stock_count``, not folded into
   "low stock" (gap M7).

The seeded end-to-end case at the bottom skips locally when
``DATABASE_URL_APP_ADMIN`` is unset and runs in CI.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.analytics import router as analytics_router
from app.modules.analytics import service as analytics_service
from app.modules.analytics.timekit import UnknownTimezoneError
from app.modules.customers.service import CustomerService
from app.modules.orders.models import Order, OrderPayment, Refund

OVERVIEW_PATH = "/api/v1/analytics/overview"
SUMMARY_PATH = "/api/v1/analytics/revenue/summary"
TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
SINCE = datetime(2026, 3, 1, tzinfo=UTC)
UNTIL = datetime(2026, 3, 15, tzinfo=UTC)

#: Keys whose value is money. ``app/core/currency.py`` owns what the code means;
#: here it owns what the WIRE TYPE must be: a string.
MONEY_KEYS = frozenset(
    {
        "gross_revenue",
        "net_revenue",
        "refunded_amount",
        "refund_excess",
        "gross_aov",
        "net_aov",
    }
)


class _NoSqlSession:
    """A session that refuses to answer: the router must not query at all."""

    async def execute(self, *_args, **_kwargs):
        raise AssertionError(
            "the analytics ROUTER touched the database — every metric SQL lives "
            "in analytics/service.py (Wave-4 M11)"
        )


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(tenant_id=TENANT, session=_NoSqlSession())


def _summary() -> dict[str, Any]:
    """One window: 100.00 collected, 40.00 refunded, 60.00 kept, 3 orders."""
    return {
        "currency": "EGP",
        "timezone": "Africa/Cairo",
        "since": SINCE.isoformat(),
        "until": UNTIL.isoformat(),
        "gross_revenue": Decimal("100.00"),
        "refunded_amount": Decimal("40.00"),
        "net_revenue": Decimal("60.00"),
        "refund_excess": Decimal("0.00"),
        "orders_count": 3,
        "gross_aov": Decimal("33.33"),
        "net_aov": Decimal("20.00"),
    }


def _series() -> list[dict[str, Any]]:
    return [
        {
            "day": "2026-03-14",
            "gross_revenue": Decimal("70.00"),
            "refunded_amount": Decimal("20.00"),
            "net_revenue": Decimal("50.00"),
            "refund_excess": Decimal("0.00"),
            "orders_count": 2,
        }
    ]


def _stock() -> dict[str, Any]:
    return {
        "low_stock_threshold": 2,
        "low_stock_count": 1,
        "out_of_stock_count": 7,
        "healthy_count": 42,
    }


def _stub_readers(monkeypatch: pytest.MonkeyPatch, calls: list[tuple]) -> None:
    """Replace the canonical readers with recorders — the router must ONLY call."""

    async def summary(session, tenant_id, *, since, until, timezone=None):
        calls.append(("revenue_summary", tenant_id, since, until, timezone))
        return _summary()

    async def series(session, tenant_id, *, since, until, timezone=None):
        calls.append(("daily_revenue_series", tenant_id, since, until, timezone))
        return _series()

    async def stock(session, tenant_id, *, low_stock_threshold=2):
        calls.append(("stock_health", tenant_id, low_stock_threshold))
        return _stock()

    monkeypatch.setattr(analytics_service, "revenue_summary", summary)
    monkeypatch.setattr(analytics_service, "daily_revenue_series", series)
    monkeypatch.setattr(analytics_service, "stock_health", stock)


def _money_calls(calls: list[tuple]) -> list[tuple]:
    """The window-shaped readers only — ``stock_health`` takes no window."""
    return [call for call in calls if len(call) == 5]


def _money_calls(calls: list[tuple]) -> list[tuple]:
    """The two window-shaped readers only — ``stock_health`` takes no window."""
    return [call for call in calls if len(call) == 5]


def _walk(payload: Any):
    """Every (key, value) pair in a nested JSON payload."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield key, value
            yield from _walk(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _walk(item)


# ------------------------------------------------------------- mounting ---


def test_overview_route_is_published() -> None:
    """RED first: the frontend calls this path and the server had no answer."""
    assert OVERVIEW_PATH in set(create_app().openapi()["paths"])


def test_overview_publishes_its_window_parameters() -> None:
    params = create_app().openapi()["paths"][OVERVIEW_PATH]["get"]["parameters"]
    names = {p["name"] for p in params}
    assert {"days", "since", "until", "timezone", "low_stock_threshold"} <= names


# ---------------------------------------------------------- delegation ---


async def test_overview_delegates_every_figure_to_a_canonical_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []
    _stub_readers(monkeypatch, calls)

    payload = await analytics_router.analytics_overview(
        _ctx(), days=30, since=None, until=UNTIL, timezone="Africa/Cairo"
    )

    assert {name for name, *_rest in calls} == {
        "revenue_summary",
        "daily_revenue_series",
        "stock_health",
    }
    # One window, one zone, used by both money readers — a series bucketed on a
    # different zone than the summary cannot be reconciled against it.
    windows = {
        (since, until, zone)
        for _name, _t, since, until, zone in _money_calls(calls)
    }
    assert len(windows) == 1
    _since, _until, zone = windows.pop()
    assert zone == "Africa/Cairo"
    assert _until - _since == timedelta(days=30)
    assert {key for key in payload} == {
        "since",
        "until",
        "currency",
        "timezone",
        "gross_revenue",
        "refunded_amount",
        "net_revenue",
        "refund_excess",
        "orders_count",
        "gross_aov",
        "net_aov",
        "daily_series",
        "stock",
    }
    # Counts and labels stay what they are; only money is stringified.
    assert payload["orders_count"] == 3
    assert payload["currency"] == "EGP"
    assert payload["timezone"] == "Africa/Cairo"
    assert payload["stock"] == _stock()
    assert payload["daily_series"][0]["day"] == "2026-03-14"
    assert payload["daily_series"][0]["orders_count"] == 2


async def test_overview_forwards_the_replenishment_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []
    _stub_readers(monkeypatch, calls)

    await analytics_router.analytics_overview(
        _ctx(), days=30, since=None, until=UNTIL, timezone=None, low_stock_threshold=5
    )

    assert ("stock_health", TENANT, 5) in calls


# ------------------------------------------------------------- the wire ---


async def test_overview_money_is_a_string_never_a_float(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-001: a float money field loses a cent somewhere and nobody can see it."""
    calls: list[tuple] = []
    _stub_readers(monkeypatch, calls)

    payload = await analytics_router.analytics_overview(
        _ctx(), days=30, since=None, until=UNTIL, timezone=None
    )

    pairs = dict(_walk(payload))
    for key in MONEY_KEYS & set(pairs):
        assert isinstance(pairs[key], str), f"{key} left the route as {type(pairs[key])}"
    for key, value in _walk(payload):
        assert not isinstance(value, float), f"{key} crossed the wire as a float"
    assert Decimal(payload["gross_revenue"]) == Decimal("100.00")
    assert Decimal(payload["net_revenue"]) == Decimal("60.00")
    assert Decimal(payload["refunded_amount"]) == Decimal("40.00")
    assert Decimal(payload["refund_excess"]) == Decimal("0.00")
    assert Decimal(payload["gross_aov"]) == Decimal("33.33")
    assert Decimal(payload["net_aov"]) == Decimal("20.00")
    row = payload["daily_series"][0]
    assert Decimal(row["gross_revenue"]) == Decimal("70.00")
    assert Decimal(row["net_revenue"]) == Decimal("50.00")


async def test_revenue_summary_route_stringifies_its_aov(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sibling route leaked ``gross_aov``/``net_aov`` as floats.

    Its money set named the four revenue keys and forgot the two averages, and
    FastAPI's default encoder resolves a bare Decimal by casting it to float —
    so the same endpoint that refuses to emit float revenue emitted a float AOV.
    """

    async def summary(session, tenant_id, *, since, until, timezone=None):
        return _summary()

    monkeypatch.setattr(analytics_service, "revenue_summary", summary)

    payload = await analytics_router.revenue_summary(
        _ctx(), since=SINCE, until=UNTIL, timezone=None
    )

    assert payload["gross_aov"] == "33.33"
    assert payload["net_aov"] == "20.00"
    for key, value in _walk(payload):
        assert not isinstance(value, float), f"{key} crossed the wire as a float"


# ------------------------------------------------------------- the window ---


async def test_overview_days_describes_a_trailing_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []
    _stub_readers(monkeypatch, calls)

    payload = await analytics_router.analytics_overview(
        _ctx(), days=7, since=None, until=UNTIL, timezone=None
    )

    since = datetime.fromisoformat(payload["since"])
    until = datetime.fromisoformat(payload["until"])
    assert until - since == timedelta(days=7)
    assert since == UNTIL - timedelta(days=7)


async def test_an_explicit_since_beats_the_default_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []
    _stub_readers(monkeypatch, calls)

    payload = await analytics_router.analytics_overview(
        _ctx(), days=7, since=SINCE, until=UNTIL, timezone=None
    )

    assert datetime.fromisoformat(payload["since"]) == SINCE
    asked = {since for _n, _t, since, _u, _z in _money_calls(calls)}
    assert asked == {SINCE}


# --------------------------------------------------------- fail closed ---


async def test_overview_refuses_an_unknown_zone_before_running_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zone that does not exist must not silently become UTC (gap M10)."""

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("a query ran for a window the caller cannot mean")

    monkeypatch.setattr(analytics_service, "revenue_summary", forbidden)
    monkeypatch.setattr(analytics_service, "daily_revenue_series", forbidden)
    monkeypatch.setattr(analytics_service, "stock_health", forbidden)

    with pytest.raises(UnknownTimezoneError):
        await analytics_router.analytics_overview(
            _ctx(), days=30, since=None, until=UNTIL, timezone="Mars/Olympus_Mons"
        )


def test_the_analytics_router_holds_no_sql() -> None:
    """The route is a serialiser, not a query writer — SQL belongs to service.py."""
    source = pathlib.Path(analytics_router.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not [name for name in imported if "sqlalchemy" in name], (
        "analytics/router.py imports sqlalchemy — the metric SQL lives in service.py"
    )


# ------------------------------------------------- seeded end to end (CI) ---


async def test_overview_reports_seeded_money_in_its_named_families(
    db: AsyncSession, tenant_ctx
) -> None:
    """100.00 collected, 40.00 refunded on the same merchant day."""
    tid = tenant_ctx.tenant_id
    customer = await CustomerService.get_or_create_by_identity(
        db, tid, "whatsapp", f"wa-{uuid.uuid4().hex[:12]}", name="Overview Buyer"
    )
    paid_at = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
    order = Order(
        tenant_id=tid,
        customer_id=customer.id,
        number=f"SO-{uuid.uuid4().hex[:10].upper()}",
        status="completed",
        grand_total=Decimal("100.00"),
        placed_at=paid_at,
    )
    db.add(order)
    await db.flush()
    payment = OrderPayment(
        tenant_id=tid,
        order_id=order.id,
        method="cash",
        status="captured",
        amount=Decimal("100.00"),
        paid_at=paid_at,
    )
    db.add(payment)
    await db.flush()
    db.add(
        Refund(
            tenant_id=tid,
            payment_id=payment.id,
            amount=Decimal("40.00"),
            status="processed",
            processed_at=paid_at,
        )
    )
    await db.flush()

    payload = await analytics_router.analytics_overview(
        SimpleNamespace(tenant_id=tid, session=db),
        days=30,
        since=SINCE,
        until=UNTIL,
        timezone="UTC",
    )

    assert payload["gross_revenue"] == "100.00"
    assert payload["net_revenue"] == "60.00"
    assert payload["refunded_amount"] == "40.00"
    assert payload["refund_excess"] == "0.00"
    assert payload["orders_count"] == 1
    assert payload["gross_aov"] == "100.00"
    assert payload["net_aov"] == "60.00"
    rows = [
        (row["day"], row["gross_revenue"], row["net_revenue"])
        for row in payload["daily_series"]
    ]
    assert rows == [("2026-03-10", "100.00", "60.00")]
    assert payload["currency"]
