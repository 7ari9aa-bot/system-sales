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
6. A route parameter's default is a VALUE, never a ``fastapi.Query`` declaration.
   ``Query(2)`` is a pydantic ``FieldInfo``: handed to ``stock_health`` it rode
   into an ``integer`` bind and asyncpg answered
   ``DataError: invalid input for query argument $1: Query(2)`` — which is what
   CI run 35959902953 went red on. Handlers are callable in-process (every
   DB-free case here calls one), so a default that only becomes a value when
   HTTP passes through is a 500 waiting for the next caller.
7. ``stock_health`` refuses a declaration as its threshold at the reader, so the
   guarantee does not depend on every route having learned the lesson.

The seeded end-to-end case at the bottom skips locally when
``DATABASE_URL_APP_ADMIN`` is unset and runs in CI.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Query
from pydantic.fields import FieldInfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
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

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement, *_args, **_kwargs):  # noqa: ANN001
        self.statements.append(str(statement))
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
        # The zone alone is not enough: the reader has to say which layer of
        # caller -> tenants.timezone -> ANALYTICS_TIMEZONE -> UTC answered
        # (§47/M10 remainder). See tests/test_tenant_timezone.py.
        "timezone_source": "tenant",
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


def _refuse_declarations(where: str, *values: Any) -> None:
    """Fail here, not in a driver: a parameter DECLARATION is not a value.

    Every recorder below runs this on its own arguments. It is the invariant CI
    run 35959902953 proved was missing — a ``fastapi.Query`` object is a pydantic
    ``FieldInfo``, and handed onward it reaches ``text(sql)`` as a bind
    parameter, where asyncpg answers ``DataError`` and the merchant sees a 500.
    """
    for value in values:
        if isinstance(value, FieldInfo):
            raise AssertionError(
                f"{where} was handed {value!r}, a FastAPI parameter declaration "
                "rather than a value. Route parameters are declared "
                "`Annotated[type, Query(...)]` with a plain Python default so an "
                "in-process caller can never receive the declaration itself."
            )


def _stub_readers(monkeypatch: pytest.MonkeyPatch, calls: list[tuple]) -> None:
    """Replace the canonical readers with recorders — the router must ONLY call."""

    async def summary(session, tenant_id, *, since, until, timezone=None):  # noqa: ANN001
        _refuse_declarations("revenue_summary", since, until, timezone)
        calls.append(("revenue_summary", tenant_id, since, until, timezone))
        return _summary()

    async def series(session, tenant_id, *, since, until, timezone=None):  # noqa: ANN001
        _refuse_declarations("daily_revenue_series", since, until, timezone)
        calls.append(("daily_revenue_series", tenant_id, since, until, timezone))
        return _series()

    async def stock(session, tenant_id, *, low_stock_threshold=2):  # noqa: ANN001
        _refuse_declarations("stock_health", low_stock_threshold)
        calls.append(("stock_health", tenant_id, low_stock_threshold))
        return _stock()

    monkeypatch.setattr(analytics_service, "revenue_summary", summary)
    monkeypatch.setattr(analytics_service, "daily_revenue_series", series)
    monkeypatch.setattr(analytics_service, "stock_health", stock)


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


# ----------------------------------------------- the parameter declarations ---


def test_route_parameters_default_to_values_not_declarations() -> None:
    """No ``fastapi.Query`` object may sit in an analytics handler's signature.

    CI run 35959902953: ``analytics_overview`` declared
    ``low_stock_threshold: int = Query(default=2, ...)``. The seeded case calls
    that handler in-process and omits the argument, so the parameter held
    ``Query(2)`` — a pydantic ``FieldInfo``, not an int — the route forwarded it
    to ``stock_health``, and asyncpg refused to encode it for an ``integer``
    bind. HTTP hides the defect because the framework fills every defaulted
    parameter in; the handler is still a plain function, and every DB-free case
    in this file calls it as one.

    The signature is the whole surface, so the guard reads the signatures:
    ``Query``/``Body``/``Header`` are ``FieldInfo`` subclasses, ``Depends`` is
    not, and no parameter of a route in this module may default to one.
    """
    offenders: list[str] = []
    for route in analytics_router.router.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        for name, parameter in inspect.signature(endpoint).parameters.items():
            if isinstance(parameter.default, FieldInfo):
                offenders.append(f"{getattr(endpoint, '__name__', endpoint)}({name})")
    assert offenders == [], (
        "these analytics route parameters default to a FastAPI declaration, which "
        f"an in-process caller hands straight into a SQL bind: {offenders}. Declare "
        "them `Annotated[type, Query(...)] = <value>` instead."
    )


async def test_an_in_process_call_omitting_every_default_binds_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The red call shape, with NOTHING but the context supplied.

    ``days`` has to arrive as the int 30, ``until`` as the instant the request is
    handled, ``low_stock_threshold`` as ``LOW_STOCK_THRESHOLD``. The recorders in
    ``_stub_readers`` are the assertion: any one of them being handed a
    declaration raises before a query can be mis-bound.
    """
    calls: list[tuple] = []
    _stub_readers(monkeypatch, calls)

    payload = await analytics_router.analytics_overview(_ctx())

    thresholds = [call[2] for call in calls if call[0] == "stock_health"]
    assert thresholds == [analytics_service.LOW_STOCK_THRESHOLD]
    assert [type(value) for value in thresholds] == [int]

    windows = {
        (since, until) for _name, _tenant, since, until, _zone in _money_calls(calls)
    }
    assert len(windows) == 1, f"one call bound {len(windows)} windows: {windows}"
    since, until = windows.pop()
    assert until - since == timedelta(days=30)
    assert since.tzinfo is not None and until.tzinfo is not None, (
        f"a defaulted window reached the readers as {since} / {until}"
    )
    # The echoed pair is the pair the readers were given — same instants, UTC.
    assert datetime.fromisoformat(payload["since"]) == since
    assert datetime.fromisoformat(payload["until"]) == until
    assert datetime.fromisoformat(payload["until"]).utcoffset() == timedelta(0)


async def test_stock_health_refuses_a_declaration_as_its_threshold() -> None:
    """The reader's own guarantee, so the route is not the only thing holding.

    The twin of ``test_a_reader_refuses_to_bind_a_naive_window`` in
    ``test_analytics_window_binding.py``: refuse before the bind and answer 400
    naming the parameter, rather than letting a driver discover that a caller
    passed a declaration instead of a value.
    """
    session = _NoSqlSession()

    with pytest.raises(ValidationError, match="low_stock_threshold"):
        await analytics_service.stock_health(session, TENANT, low_stock_threshold=Query(2))

    assert session.statements == [], "the declaration reached SQL before the refusal"


async def test_stock_health_binds_a_supplied_threshold_as_an_integer() -> None:
    """The positive half: a real int passes the guard and reaches the bind."""
    seen: list[dict] = []

    class _RecordingSession:
        async def execute(self, statement, params=None, *_args, **_kwargs):  # noqa: ANN001
            seen.append(dict(params or {}))

            class _Result:
                @staticmethod
                def one():
                    return (0, 0, 0)

            return _Result()

    health = await analytics_service.stock_health(
        _RecordingSession(), TENANT, low_stock_threshold=5
    )

    assert seen[0]["threshold"] == 5
    assert type(seen[0]["threshold"]) is int
    assert health["low_stock_threshold"] == 5


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
        "timezone_source",
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
    assert payload["timezone_source"] == "tenant"
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
    # The stock band is the argument this case used to die on: the call omits
    # `low_stock_threshold`, so the route's DEFAULT is what reaches the integer
    # bind. CI run 35959902953 got `DataError: invalid input for query argument
    # $1: Query(2)` here; an int is what comes back.
    assert payload["stock"]["low_stock_threshold"] == analytics_service.LOW_STOCK_THRESHOLD
