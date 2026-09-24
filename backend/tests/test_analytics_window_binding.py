"""W5-T2 — an analytics window is a set of INSTANTS, and the route must be told.

The defect
----------
``/analytics/revenue/summary``, ``/analytics/daily-series``, ``/analytics/overview``
and ``/analytics/metrics/{name}`` typed their window as a bare ``datetime``.
FastAPI happily accepts a string with no offset — ``2026-09-01T00:00:00`` — and
the value then rode straight into ``placed_at >= :since`` against a
``timestamptz`` column. A timestamp without an offset is not an instant: the
database has to read it *in some zone*, and the zone it uses is the connection's
own. So one request URL answered two different questions depending on
deployment settings — and the merchant could not see it, because the DAY LABELS
are cut in the merchant's zone (``tenants.timezone``, ``analytics/timekit.py``),
which hides a window that silently starts three hours early or late.

The policy this file pins
-------------------------
**Every window parameter is an instant and must carry a UTC offset. A naive
value is refused with a 422 that names the fix; an accepted value is bound to
UTC and the response echoes the exact instants the query used.**

Why refuse rather than quietly assume UTC: UTC is a *guess* about what a Cairo
merchant who typed a wall clock meant, and the guess lands in the same place as
the bug this replaces. It is §47's rule, applied to the clock — the same
posture ``identity.service.TenantSettingsService.set_timezone`` takes for a zone
it cannot resolve (refuse at the boundary, never convert), and the same one
``timekit.resolve_timezone`` takes for a stored zone that stopped resolving
(fail closed, do not fall back).

What is DB-free and what is not
-------------------------------
Everything above the SQL bind is pinned here with no database: the 422, the
message, the OpenAPI statement, the exact ``datetime`` objects that reach
the read models, the two-instant claim itself (stated in Python by
``test_the_same_wall_clock_in_two_zones_names_two_instants``) and the
``bind_instant`` type refusal that stops a value which is not a datetime at all
(a ``Query`` declaration, a string, an epoch) from reaching a driver. The three
tests at the bottom need a real PostgreSQL — they skip locally when
``DATABASE_URL_APP_ADMIN`` is unset and run in CI — because they are the only
ones that can show what a connection does with an unoffset stamp.

This file is new rather than a section of ``test_tenant_timezone.py`` because
that file pins *which zone a day label is cut in*; this pins *which instants a
window selects*. The two are orthogonal questions and the second one applies to
every dated read model, not only the zone-aware ones.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from fastapi import FastAPI, HTTPException, Query
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.main import create_app
from app.modules.analytics import router as analytics_router
from app.modules.analytics import service as analytics_service
from app.modules.analytics.timekit import ResolvedTimezone
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from tests.test_analytics_correctness import _collected

TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")

SUMMARY_PATH = "/api/v1/analytics/revenue/summary"
SERIES_PATH = "/api/v1/analytics/daily-series"
OVERVIEW_PATH = "/api/v1/analytics/overview"
METRIC_PATH = "/api/v1/analytics/metrics/revenue"
#: OpenAPI publishes the metric route as a TEMPLATE, not as one path per metric.
METRIC_OPENAPI_PATH = "/api/v1/analytics/metrics/{metric_name}"

#: Every route that takes a window. A policy with an exception in it is not a policy.
WINDOW_ROUTES = (SUMMARY_PATH, SERIES_PATH, OVERVIEW_PATH, METRIC_PATH)
#: The routes whose response envelope is BUILT by ``analytics/router.py``, so the
#: echoed ``since``/``until`` there are production code and not the stub's.
ROUTER_ECHOES = (SERIES_PATH, OVERVIEW_PATH, METRIC_PATH)

# Cairo is +03:00 year-round, so this pair stays true whichever tzdata is loaded.
CAIRO_MIDNIGHT = "2026-09-01T00:00:00+03:00"
CAIRO_NOON = "2026-09-01T12:00:00+03:00"
UTC_MIDNIGHT = "2026-08-31T21:00:00Z"
UTC_NOON = "2026-09-01T09:00:00Z"
BOUND_SINCE = datetime(2026, 8, 31, 21, 0, tzinfo=UTC)
BOUND_UNTIL = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def _enc(stamp: str) -> str:
    """A ``+`` in a query string is a SPACE, so an offset has to be percent-encoded.

    Getting this wrong does not look like a bug in the test: the server receives
    ``2026-09-01T00:00:00 03:00`` and calls it unparseable.
    """
    return stamp.replace("+", "%2B")


#: One window, spelled two ways that name the SAME pair of instants.
CAIRO_WINDOW = f"since={_enc(CAIRO_MIDNIGHT)}&until={_enc(CAIRO_NOON)}"
UTC_WINDOW = f"since={UTC_MIDNIGHT}&until={UTC_NOON}"

#: The SAME wall clock with the offset deleted. Before W5-T2 this was a valid
#: request; it is the ambiguous input this policy exists to refuse.
NAIVE_SINCE = "2026-09-01T00:00:00"
NAIVE_UNTIL = "2026-09-01T12:00:00"

_SUMMARY: dict[str, Any] = {
    # No `since`/`until` on purpose: where the echo comes from the ROUTER it is
    # under test, where it comes from the service it is tested separately below.
    "currency": "EGP",
    "timezone": "Africa/Cairo",
    "timezone_source": "tenant",
    "gross_revenue": Decimal("100.00"),
    "refunded_amount": Decimal("40.00"),
    "net_revenue": Decimal("60.00"),
    "refund_excess": Decimal("0.00"),
    "orders_count": 3,
    "gross_aov": Decimal("33.33"),
    "net_aov": Decimal("20.00"),
}
_STOCK = {
    "low_stock_threshold": 2,
    "low_stock_count": 1,
    "out_of_stock_count": 0,
    "healthy_count": 42,
}


class _NoSqlSession:
    """A session that refuses to run a query for a window nobody bound.

    Every case in the first half of this file is a boundary case: if the request
    is rejected, NOTHING may reach Postgres. Reaching it is the defect.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement, _params=None):  # noqa: ANN001
        self.statements.append(str(statement))
        raise AssertionError(
            "a query ran for a window whose offset was never established — "
            "the refusal has to happen before the bind, not after it"
        )


def _app() -> FastAPI:
    app = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=_NoSqlSession(),
            user=AuthedUser(id=uuid.uuid4(), tenant_id=TENANT, role_code="owner"),
            tenant_id=TENANT,
            role_code="owner",
            permission_codes=set(),
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test")


def _stub_readers(
    monkeypatch: pytest.MonkeyPatch, seen: list[tuple], zones: list[Any]
) -> None:
    """Replace the canonical readers with recorders of the window they were given."""

    async def summary(session, tenant_id, *, since, until, timezone=None):  # noqa: ANN001
        seen.append((since, until))
        return dict(_SUMMARY)

    async def series(session, tenant_id, *, since, until, timezone=None):  # noqa: ANN001
        seen.append((since, until))
        return []

    async def stock(session, tenant_id, *, low_stock_threshold=2):  # noqa: ANN001
        return dict(_STOCK)

    async def metric(session, tenant_id, *, metric_name, since, until):  # noqa: ANN001
        seen.append((since, until))
        return Decimal("12.00")

    async def zone(session, tenant_id, caller_timezone=None):  # noqa: ANN001
        zones.append(caller_timezone)
        return ResolvedTimezone("Africa/Cairo", source="tenant")

    async def currency(session, tenant_id):  # noqa: ANN001
        return "EGP"

    monkeypatch.setattr(analytics_service, "revenue_summary", summary)
    monkeypatch.setattr(analytics_service, "daily_revenue_series", series)
    monkeypatch.setattr(analytics_service, "stock_health", stock)
    monkeypatch.setattr(analytics_service, "compute_metric", metric)
    monkeypatch.setattr(analytics_service, "resolve_report_timezone", zone)
    monkeypatch.setattr(analytics_router, "resolve_tenant_currency", currency)


async def _window_seen(
    monkeypatch: pytest.MonkeyPatch, path: str, query: str
) -> tuple[datetime, datetime]:
    """The ONE ``[since, until)`` the readers were handed for this request."""
    seen: list[tuple] = []
    _stub_readers(monkeypatch, seen, [])
    async with _client() as client:
        response = await client.get(f"{path}?{query}")
    assert response.status_code == 200, response.text
    assert seen, "the request answered without asking a reader for anything"
    windows = set(seen)
    assert len(windows) == 1, f"one request bound {len(windows)} different windows: {windows}"
    return windows.pop()


async def _payload(monkeypatch: pytest.MonkeyPatch, path: str, query: str) -> dict:
    _stub_readers(monkeypatch, [], [])
    async with _client() as client:
        response = await client.get(f"{path}?{query}")
    assert response.status_code == 200, response.text
    return response.json()


def _error_text(response) -> str:  # noqa: ANN001
    """Everything a 422 tells the caller, flattened into one string to read."""
    detail = response.json()["detail"]
    return " ".join(
        f"{'.'.join(str(p) for p in e.get('loc', []))} {e.get('msg', '')}" for e in detail
    )


# ============================================ a naive window is refused ====


@pytest.mark.parametrize("path", WINDOW_ROUTES)
async def test_a_naive_since_is_refused_before_anything_is_queried(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """`2026-09-01T00:00:00` is a wall clock, not an instant: it cannot be bound.

    The old behaviour was a 200 and a number — the number was whichever instant
    the connection's timezone happened to make of it.
    """
    _stub_readers(monkeypatch, seen := [], zones := [])
    async with _client() as client:
        response = await client.get(f"{path}?since={NAIVE_SINCE}")

    assert response.status_code == 422, response.text
    assert "since" in _error_text(response)
    assert seen == [] and zones == [], "a refused window still reached a reader"


@pytest.mark.parametrize("path", WINDOW_ROUTES)
async def test_a_naive_until_is_refused_too(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    """The open end of the interval is as ambiguous as the closed one — and it is
    the one a caller can forget, because it defaults to something aware."""
    _stub_readers(monkeypatch, seen := [], zones := [])
    async with _client() as client:
        response = await client.get(f"{path}?since={UTC_MIDNIGHT}&until={NAIVE_UNTIL}")

    assert response.status_code == 422, response.text
    assert "until" in _error_text(response)
    assert seen == [] and zones == []


async def test_the_refusal_names_the_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 422 that only says "invalid" sends the caller back to the docs. The
    message has to name the missing thing and show it spelled correctly."""
    _stub_readers(monkeypatch, [], [])
    async with _client() as client:
        response = await client.get(f"{SERIES_PATH}?since={NAIVE_SINCE}")

    assert response.status_code == 422, response.text
    text = _error_text(response)
    assert "UTC offset" in text, text
    assert "Z" in text and "+03:00" in text, f"the refusal gives no example to copy: {text}"


@pytest.mark.parametrize("path", WINDOW_ROUTES)
def test_the_policy_is_published_in_openapi(path: str) -> None:
    """The Query description IS the contract a client integrator reads. A policy
    that lives only in a docstring is a policy one caller will re-derive wrong."""
    published = METRIC_OPENAPI_PATH if path == METRIC_PATH else path
    parameters = create_app().openapi()["paths"][published]["get"]["parameters"]
    window = {p["name"]: p for p in parameters if p["name"] in {"since", "until"}}
    assert {"since", "until"} <= set(window), f"{path} stopped publishing its window"
    for name, parameter in window.items():
        description = parameter["schema"].get("description", "")
        assert "UTC offset" in description, f"{path} {name}: the policy is not stated"
        assert "naive" in description, f"{path} {name}: the refused input is not named"
        assert _formats(parameter["schema"]) == {"date-time"}, (
            f"{path} {name} is no longer published as an instant: {parameter['schema']}"
        )


def _formats(schema: dict) -> set:
    """Every format a published parameter names — an optional parameter hides
    behind ``anyOf``, which is how "omit it" is written in JSON Schema."""
    if "format" in schema:
        return {schema["format"]}
    return {sub["format"] for sub in schema.get("anyOf", []) if "format" in sub}


# ================================== an instant binds exactly one UTC value ==


@pytest.mark.parametrize("path", WINDOW_ROUTES)
async def test_an_offset_carrying_window_binds_the_instant_it_names(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    seen = await _window_seen(monkeypatch, path, CAIRO_WINDOW)

    assert seen == (BOUND_SINCE, BOUND_UNTIL), (
        "Cairo midnight must reach the reader as the UTC instant it IS"
    )
    # Equality alone would not prove the binding: two aware datetimes in different
    # offsets compare equal. WHAT reaches the SQL has to be rendered in UTC, which
    # is what makes the echoed window and the bound window the same text.
    assert [value.utcoffset() for value in seen] == [timedelta(0), timedelta(0)], (
        f"the window reached SQL as {seen}, not as UTC instants"
    )


@pytest.mark.parametrize("path", WINDOW_ROUTES)
async def test_the_same_instant_spelled_two_ways_selects_the_same_rows(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """The proof the reader needs: "+03:00" and "Z" are not two questions.

    Whatever the server's connection believes about its own timezone, one
    instant set is one answer.
    """
    cairo = await _window_seen(monkeypatch, path, CAIRO_WINDOW)
    utc = await _window_seen(monkeypatch, path, UTC_WINDOW)

    assert cairo == utc == (BOUND_SINCE, BOUND_UNTIL)


@pytest.mark.parametrize("path", ROUTER_ECHOES)
async def test_the_response_says_which_window_it_bound(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """Reporting the zone a day label was cut in, and not reporting the instants
    the rows were selected by, leaves half the answer implicit."""
    payload = await _payload(monkeypatch, path, CAIRO_WINDOW)

    for name, bound in (("since", BOUND_SINCE), ("until", BOUND_UNTIL)):
        echoed = payload[name]
        assert echoed.endswith("+00:00"), f"{path} echoed {name}={echoed}, not a UTC instant"
        assert datetime.fromisoformat(echoed) == bound
        # An instant carries its offset; a day LABEL never does. Keep them apart.
        assert "T" in echoed


async def test_the_default_until_is_an_instant_as_well(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server's own default must obey the policy it enforces on callers, or
    `until` answers a different kind of question than `since` does."""
    payload = await _payload(monkeypatch, SERIES_PATH, f"since={_enc(CAIRO_MIDNIGHT)}")

    until = datetime.fromisoformat(payload["until"])
    assert until.tzinfo is not None, payload["until"]
    assert payload["until"].endswith("+00:00")
    # The default is stamped inside the request, so it is ~now and not exactly now:
    # it can land on either side of the test's own clock read by a millisecond.
    skew = until - datetime.now(UTC)
    assert timedelta(seconds=-5) < skew < timedelta(minutes=5), (
        f"the default end of the window stopped being ~now: {payload['until']}"
    )


# ==================== the SQL bind itself refuses an unbound instant ========


@pytest.mark.parametrize(
    ("reader", "kwargs"),
    [
        ("revenue", {}),
        ("net_revenue", {}),
        ("orders_count", {}),
        ("refunded_amount", {}),
        ("aov", {}),
        ("daily_revenue_series", {}),
        ("revenue_summary", {}),
        ("first_response_time_avg", {}),
        ("resolution_time_avg", {}),
        ("ai_resolution_rate", {}),
        ("compute_metric", {"metric_name": "revenue"}),
    ],
)
async def test_a_reader_refuses_to_bind_a_naive_window(
    reader: str, kwargs: dict[str, Any]
) -> None:
    """The route is the promise; this is the guarantee behind it.

    Every read model in this module compares against a ``timestamptz`` column, so
    a naive instant is not a value the SQL layer can honour — it must refuse
    before the bind rather than let Postgres pick the timezone.
    """
    session = _NoSqlSession()
    with pytest.raises(ValidationError, match="UTC offset"):
        await getattr(analytics_service, reader)(
            session,
            TENANT,
            since=datetime(2026, 9, 1),  # noqa: DTZ001 — the ambiguity IS the input
            until=datetime(2026, 9, 2, 9, 0),  # noqa: DTZ001
            **kwargs,
        )
    assert session.statements == []


async def test_the_summary_echoes_the_instant_it_bound_not_the_clock_it_was_handed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``revenue_summary`` owns its own envelope, so the canonical UTC echo has to
    be produced there too — and a window given in another offset must come back
    as the same instant, not as the caller's spelling."""

    async def money(session, tenant_id, *, since, until):
        return Decimal("100.00")

    async def count(session, tenant_id, *, since, until):
        return 1

    async def currency(session, tenant_id):  # noqa: ANN001
        return "EGP"

    async def zone(session, tenant_id, caller_timezone=None):  # noqa: ANN001
        return ResolvedTimezone("Africa/Cairo", source="tenant")

    monkeypatch.setattr(analytics_service, "revenue", money)
    monkeypatch.setattr(analytics_service, "refunded_amount", money)
    monkeypatch.setattr(analytics_service, "orders_count", count)
    monkeypatch.setattr(analytics_service, "resolve_report_timezone", zone)
    monkeypatch.setattr(analytics_service, "resolve_tenant_currency", currency)

    cairo = ZoneInfo("Africa/Cairo")
    summary = await analytics_service.revenue_summary(
        _NoSqlSession(),
        TENANT,
        since=datetime(2026, 9, 1, tzinfo=cairo),
        until=datetime(2026, 9, 1, 12, tzinfo=cairo),
    )

    assert summary["since"] == "2026-08-31T21:00:00+00:00"
    assert summary["until"] == "2026-09-01T09:00:00+00:00"


# ==================== the merchant-day label, untouched by all of this =====

# W5-T1 fixed daily-series to resolve the zone ONCE and report
# `timezone` + `timezone_source`. Binding the window harder must not re-cut the
# label: the label is local, the window is an instant, and one request resolves
# each exactly once.


async def test_binding_the_window_does_not_re_cut_the_day_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zones: list[Any] = []
    _stub_readers(monkeypatch, seen := [], zones)
    async with _client() as client:
        response = await client.get(
            f"{SERIES_PATH}?{CAIRO_WINDOW}&timezone=Europe/Paris"
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["timezone"] == "Africa/Cairo"
    assert payload["timezone_source"] == "tenant"
    assert zones == ["Europe/Paris"], f"the zone was resolved {len(zones)} times"
    # The caller's ask travels to the ONE resolution; the window does not disturb it.
    assert seen == [(BOUND_SINCE, BOUND_UNTIL)]


# ========================== the claim itself, in Python (DB-free) ==========


def test_the_same_wall_clock_in_two_zones_names_two_instants() -> None:
    """DB-free twin of the seeded proof below — the claim, stated in Python.

    ``2026-09-01T00:00:00`` is a wall clock, not an instant. Attach a zone and it
    becomes one, and WHICH one depends entirely on the zone: Cairo is +03:00 on
    that date (summer time since 2023), so it names ``2026-08-31T21:00Z``; a
    +02:00 zone such as Paris names ``2026-08-31T22:00Z``; UTC itself names
    ``2026-09-01T00:00Z``. Three hours between the first and the last, for one
    string — and a naive ``since`` used to leave the choice to whoever happened
    to own the connection, while ``tenants.timezone`` (which decides the DAY
    LABELS beside it) was never consulted at all.

    That is also why the fix cannot be "read naive values as UTC": it would move
    a Cairo merchant's window three hours and print the merchant's own days next
    to the shifted numbers. `bind_instant` refuses instead, which is what the
    last assertion pins.
    """
    wall_clock = datetime.fromisoformat(NAIVE_SINCE)  # noqa: DTZ001 — no zone yet
    assert wall_clock.tzinfo is None

    cairo = wall_clock.replace(tzinfo=ZoneInfo("Africa/Cairo"))
    paris = wall_clock.replace(tzinfo=ZoneInfo("Europe/Paris"))
    in_utc = wall_clock.replace(tzinfo=UTC)
    assert cairo.astimezone(UTC) == datetime(2026, 8, 31, 21, 0, tzinfo=UTC)
    assert paris.astimezone(UTC) == datetime(2026, 8, 31, 22, 0, tzinfo=UTC)
    assert in_utc == datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    assert cairo != paris != in_utc, "one wall clock in three zones is three instants"
    assert (in_utc - cairo) == timedelta(hours=3)

    # ... and none of the three is reachable by binding the naive spelling.
    with pytest.raises(ValidationError, match="UTC offset"):
        analytics_service.bind_instant(wall_clock, "since")


# ==================== a window edge must be a datetime, not a declaration ===

#: The object CI run 35959902953 bound: a ``Query`` DECLARATION that survived
#: because the caller omitted the parameter, in the other case the pydantic
#: default of one. Neither is a value, and neither may reach a bind.
_NOT_VALUES = (
    Query(2),
    "2026-09-01T00:00:00",
    1_756_684_800,
    datetime,
)


@pytest.mark.parametrize("value", _NOT_VALUES)
def test_bind_instant_refuses_anything_that_is_not_an_instant(value: Any) -> None:
    """:func:`bind_instant` guards its own type, not just the offset.

    The naive-``datetime`` refusal below (`test_a_reader_refuses_to_bind_a_naive_
    window`) reaches ``value.utcoffset()``. That is the right question for a
    datetime and an ``AttributeError`` — an unhandled 500 — for anything else,
    which is exactly the shape of the CI failure this file exists to kill: a
    declaration that never became a value travelling as far as a driver. Refusing
    the TYPE first, in the same seam that refuses the offset, means the answer is
    a 400 that names the parameter.
    """
    with pytest.raises(ValidationError, match="ISO 8601 instant") as exc_info:
        analytics_service.bind_instant(value, "since")

    assert exc_info.value.details["since"] == repr(value)


def test_the_refusal_answers_a_non_datetime_instead_of_raising_inside_the_422() -> None:
    """The 422 builder reads its own input, so it has to survive a non-datetime.

    ``_bind_edge`` used to render the failing value with ``.isoformat()`` — safe
    while the only bad input was a naive datetime, an ``AttributeError`` the
    moment the input was a declaration or a string. A client that sent the wrong
    KIND of value got a 500 about the refusal, not the refusal.
    """
    with pytest.raises(HTTPException) as exc_info:
        analytics_router._bind_window(None, Query(2))  # noqa: SLF001 — the seam is private

    (failure,) = exc_info.value.detail
    assert failure["loc"] == ["query", "until"]
    assert failure["input"] == "Query(2)", failure
    assert "ISO 8601 instant" in failure["msg"], failure


# ============================================ driven over a real database ===


async def test_a_stamp_without_an_offset_really_names_two_instants(
    db: AsyncSession, tenant_ctx
) -> None:
    """DB-GATED (CI). Why the refusal is not pedantry, on a real connection.

    The same wall clock text, two session timezones, two different instants.
    This is exactly what a naive ``since`` used to smuggle into
    ``placed_at >= :since`` — and the merchant could not see it, because the day
    labels beside it were cut in a third zone again.

    The stamp is bound the way the defect bound it: as a zone-less
    ``timestamp``, so the SERVER decides which instant the wall clock names,
    under the ``TimeZone`` its session believes it lives in. Two earlier shapes
    of this test proved nothing: a ``timestamptz`` bind is a Python-side decision
    (asyncpg encodes an instant and Postgres has nothing left to interpret), and
    a comparison of two Python strings never reached the database at all. Parsing
    to a naive ``datetime`` and letting ``::timestamp::timestamptz`` do the zone
    work is the one formulation where the answer comes from PostgreSQL.
    """

    async def utc_instant(wall_clock: str, zone: str) -> str:
        """Where the database puts an unoffset stamp, given the zone it thinks it is in."""
        naive = datetime.fromisoformat(wall_clock)  # noqa: DTZ001 — the point of it
        assert naive.tzinfo is None, f"{wall_clock} arrived with a zone already"
        # `is_local=true` is transaction-scoped, and the fixture's transaction
        # spans this test: the zone has to be set by its own statement so the
        # cast below provably runs after it (a target list has no order).
        await db.execute(sa.text("SELECT set_config('TimeZone', :tz, true)"), {"tz": zone})
        row = (
            await db.execute(
                sa.text(
                    "SELECT ((:stamp::timestamp)::timestamptz AT TIME ZONE 'UTC')::text"
                ),
                {"stamp": naive},
            )
        ).first()
        return row[0]

    dubai = await utc_instant(NAIVE_SINCE, "Asia/Dubai")
    cairo = await utc_instant(NAIVE_SINCE, "Africa/Cairo")

    assert dubai != cairo, f"an unoffset stamp should not move: both said {dubai}"
    assert dubai.startswith("2026-08-31 20:00") and cairo.startswith("2026-08-31 21:00"), (
        f"Dubai={dubai} Cairo={cairo}"
    )


async def test_an_offset_carrying_window_selects_the_same_money_in_any_zone(
    db: AsyncSession, tenant_ctx
) -> None:
    """DB-GATED (CI). Cairo day one: two sales inside it, one just outside.

    08-31 20:30 UTC is 23:30 on 31 August in Cairo — NOT in the window.
    08-31 21:30 UTC is 00:30 on 1 September in Cairo — in it.
    09-01 20:30 UTC is 23:30 on 1 September in Cairo — in it.

    The window is stated as Cairo midnights and must select 120.00 no matter what
    the connection's own timezone is; a session that believed it lived in Dubai
    would have opened the window an hour earlier and read 170.00.
    """
    tid = tenant_ctx.tenant_id
    await _collected(db, tid, amount="50.00", paid_at=datetime(2026, 8, 31, 20, 30, tzinfo=UTC))
    await _collected(db, tid, amount="70.00", paid_at=datetime(2026, 8, 31, 21, 30, tzinfo=UTC))
    await _collected(db, tid, amount="50.00", paid_at=datetime(2026, 9, 1, 20, 30, tzinfo=UTC))

    cairo = ZoneInfo("Africa/Cairo")
    since = datetime(2026, 9, 1, tzinfo=cairo)
    until = datetime(2026, 9, 2, tzinfo=cairo)

    for zone in ("UTC", "Asia/Dubai", "America/New_York"):
        await db.execute(sa.text("SELECT set_config('TimeZone', :tz, true)"), {"tz": zone})
        gross = await analytics_service.revenue(db, tid, since=since, until=until)
        assert gross == Decimal("120.00"), f"the session zone {zone} changed the answer"

        spelled = await analytics_service.revenue(
            db, tid, since=BOUND_SINCE, until=datetime(2026, 9, 1, 21, tzinfo=UTC)
        )
        assert spelled == gross, f"the same instants in another offset read differently: {zone}"


async def test_a_naive_window_is_refused_end_to_end(
    db: AsyncSession, tenant_ctx
) -> None:
    """DB-GATED (CI). The refusal over the real stack, not just the annotation.

    The route is reached, its dependency is satisfied, and the request still
    stops at validation: no row is read, no number is answered.
    """
    app = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_ctx.tenant_id, role_code="owner"),
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
            permission_codes=set(),
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        refused = await client.get(f"{SERIES_PATH}?since={NAIVE_SINCE}&until={NAIVE_UNTIL}")
        assert refused.status_code == 422, refused.text
        assert "UTC offset" in _error_text(refused)

        answered = await client.get(
            f"{SERIES_PATH}?{CAIRO_WINDOW}&timezone=UTC"
        )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["since"] == "2026-08-31T21:00:00+00:00"
    assert body["until"] == "2026-09-01T09:00:00+00:00"
    assert body["timezone"] and body["timezone_source"] in {
        "param",
        "tenant",
        "deployment",
        "fallback",
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
