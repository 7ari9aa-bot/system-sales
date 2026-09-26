"""Spec §55-57 — analytics routes: metric queries, definitions, retention.

Reads return a number or a list. The ONE write surface here is §55-57's chosen
retention policy (``GET /analytics/retention``,
``PUT /analytics/retention/policies/{data_class}``): a tenant's answer to "may
your own cold rows be dropped by month?". It lives beside the reads because
``analytics/retention.py`` owns that decision, and it adds no query and no
upsert of its own — see the section at the bottom of this file.

Money never leaves here unlabelled: gross and net are different keys, and the
currency is read from the tenant (§47). Daily buckets are taken in the merchant's
zone, not at UTC midnight (gap M10).

``GET /overview`` is the screen-shaped aggregate: it composes the same readers
into one payload for the analytics page — no route here owns a query, and no
figure is computed twice.

This module provides the canonical metric computation endpoints (revenue,
orders_count, AOV, etc.) backed by the metric registry (§167). The marketing
module's analytics_router is for campaign-specific analytics (CAC, ROAS);
this module is for the platform-wide canonical numbers.

Every route here publishes a model (gap P8: this file measured 0 of 8 typed,
each annotated ``-> dict``, which FastAPI renders as "an object, keys unknown").
The models live in ``analytics/schemas.py``. The handlers keep returning the plain
mapping they always returned, because the payload IS composed in-process by
callers — ``tests/test_analytics_overview.py`` calls ``analytics_overview(...)``
directly and indexes the result — and ``response_model=`` is the boundary that
turns it into a contract: it is what refuses a ``Decimal`` that reached the encoder
unformatted, which no read-model test can see (ADR-001).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.audit import write_audit_row
from app.core.errors import ValidationError
from app.core.tenancy import resolve_tenant_currency
from app.modules.analytics import retention, schemas
from app.modules.analytics import service as analytics_service
from app.modules.analytics.timekit import ResolvedTimezone, resolve_timezone
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.platform.metrics import MetricRegistry

router = APIRouter(prefix="/analytics", tags=["analytics"])

#: The widest window any dated read model here will bind, in days. ``days`` was
#: capped at 365 on ``/overview`` while an explicit ``since`` of 1970 was
#: unlimited on the SAME route for the SAME query (gap P7) — one ceiling, both
#: doors, enforced in :func:`_bind_window` before anything reaches a reader.
MAX_WINDOW_DAYS = 365

#: The ceiling on ``low_stock_threshold``, which is bound into SQL as
#: ``available <= :threshold``. The floor (0) was already refused; a million is
#: not a stock band, it is a way to turn a dashboard card into a scan of every
#: balance a tenant holds. Generously above any real catalogue's reorder point,
#: so it refuses the mistake and not the use.
MAX_LOW_STOCK_THRESHOLD = 10_000

SettingsCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]

#: Reading the metric definitions and the retention position is an analytics
#: concern, so it is the ``analytics`` scope — not ``settings``, which the money
#: routes above never needed either. Choosing a retention policy is a governance
#: write: it is permission to DELETE, so it asks for ``analytics:write``, which
#: ``scripts/provision.py``'s ROLE_MATRIX grants to owner and manager and WITHHOLDS
#: from staff. A frontline role must not be the one that authorises a partition DROP.
AnalyticsReadCtx = Annotated[TenantContext, Depends(require_permission("analytics:read"))]
AnalyticsWriteCtx = Annotated[TenantContext, Depends(require_permission("analytics:write"))]

# ============================================= the parameter-declaration rule ===
#
# Every query parameter below is declared ``name: Annotated[type, Query(...)]``
# with a PLAIN Python default, and never ``name: type = Query(...)``. The two
# forms are identical to FastAPI and radically different to Python: the second
# leaves a ``fastapi.params.Query`` object — a pydantic ``FieldInfo``, which is
# neither an int nor a datetime — sitting in the handler's OWN signature, and
# only the HTTP path ever replaces it.
#
# CI run 35959902953 is what that costs. The seeded case
# ``tests/test_analytics_overview.py::test_overview_reports_seeded_money_in_its_named_families``
# calls ``analytics_overview(...)`` in-process and omits ``low_stock_threshold``,
# so that parameter still held ``Query(2)`` — the ``Query(default=2)``
# declaration, unconverted. The route forwarded it untouched to
# ``analytics_service.stock_health``, which bound it as ``:threshold`` against an
# ``integer``, and asyncpg answered ``DataError: invalid input for query argument
# $1: Query(2) ('Query' object cannot be interpreted as an integer)``. Every
# defaulted parameter on that route had the same defect; the threshold simply
# reached SQL first. ``days`` would have failed a ``timedelta`` subtraction,
# ``until`` an attribute lookup, ``timezone`` a zone resolution.
#
# A handler whose defaults are declarations instead of values answers correctly
# over HTTP and 500s for any in-process caller — a test today, a composed read
# model tomorrow — which is a contract that cannot be trusted from inside the
# process. Two guards hold the rule, both DB-free:
#
#   * ``test_route_parameters_default_to_values_not_declarations`` reads every
#     route signature in this module;
#   * ``analytics_service.bind_count`` refuses a non-integer threshold at the
#     reader, the way ``bind_instant`` refuses a naive window edge, so a
#     declaration that still reaches a bind is a 400 naming the parameter
#     rather than a codec's TypeError.

# ======================================================= the window policy ===
#
# W5-T2. Every dated read model here used to declare ``since: datetime``, and
# FastAPI accepted ``2026-09-01T00:00:00`` — a wall clock, not an instant — and
# bound it straight into ``placed_at >= :since`` on a ``timestamptz`` column.
# Postgres then read it in the CONNECTION's timezone, so one URL answered a
# different question per deployment, while the merchant-day labels
# (``timekit.py``) went on printing the tenant's own calendar. A "July 1" window
# could start three hours early and nothing in the response said so.
#
# The policy is stated in the Query descriptions below, which is what the
# published contract carries: a window edge is an instant, it must name its
# offset, and the ``since``/``until`` in the response are the exact instants the
# query bound. Naive values are refused rather than guessed at — the same
# posture ``identity.service.TenantSettingsService.set_timezone`` takes for a
# zone it cannot resolve and ``timekit.resolve_timezone`` takes for a stored
# zone that stopped resolving: refuse at the boundary, never convert.
_WINDOW_POLICY = (
    "An ISO 8601 INSTANT, which means it must carry a UTC offset: "
    "`2026-09-01T00:00:00Z`, or `2026-09-01T00:00:00+03:00` for a window you "
    "mean in Cairo time. A naive value (no offset) is refused with a 422, "
    "because Postgres would read it in the database session's timezone and the "
    "window would silently move with the connection. The `since`/`until` this "
    "response echoes are the exact UTC instants the query bound."
)
_SINCE_DOC = f"ISO 8601 start (inclusive). {_WINDOW_POLICY}"
_UNTIL_DOC = (
    f"ISO 8601 end (exclusive), as an instant. {_WINDOW_POLICY} "
    "Defaults to the moment the request is handled, in UTC."
)


def _bind_edge(value: Any, name: str, failures: list[dict]) -> datetime:
    """One window edge as a UTC instant, or the 422 failure that says why not.

    The returned ``value`` on the failure path is a placeholder: the caller
    raises as soon as this list is non-empty, so it never reaches a query. It is
    there so the seam that reports BOTH bad edges in one response (a client that
    fixed one and not the other gets told about both) does not have to lie to a
    type checker about the other one.

    ``value`` is typed loosely on purpose: the 422 must be able to describe a
    caller that passed something which is not a datetime at all (a string from a
    hand-rolled client, a route declaration that never became a value), and
    `datetime.isoformat` would raise on the way to explaining that.
    """
    try:
        return analytics_service.bind_instant(value, name)
    except ValidationError as exc:
        failures.append(
            {
                "type": "value_error",
                "loc": ["query", name],
                "msg": f"Value error, {exc.message}",
                "input": value.isoformat() if isinstance(value, datetime) else repr(value),
            }
        )
        return value


def _window_failure(name: str, message: str, value: object) -> dict:
    """One refusal in the shape FastAPI itself uses for a bad query parameter.

    Same ``loc``/``msg``/``input`` triple :func:`_bind_edge` builds, so a client
    that reads a 422 anywhere else in this API reads this one unchanged, and so
    BOTH halves of a broken window are reported in one response rather than one
    per round trip.
    """
    return {
        "type": "value_error",
        "loc": ["query", name],
        "msg": f"Value error, {message}",
        "input": value.isoformat() if isinstance(value, datetime) else repr(value),
    }


def _bind_window(
    since: datetime | None, until: datetime | None
) -> tuple[datetime | None, datetime]:
    """Bind the window edges to instants, or answer 422 naming the fix.

    This cannot ride on the parameter annotation: FastAPI validates a query
    parameter against its TYPE and drops every other pydantic metadata, so an
    ``AfterValidator`` here is parsed, ignored and never reached (a naive
    ``since`` sailed straight into the bind). So the rule is enforced at the one
    seam every dated route passes through, before any query runs, and answered
    in the shape the framework uses for a bad parameter — ``loc`` says WHICH
    one, ``msg`` says what to do about it — so a client that reads a 422
    anywhere else in this API reads this one unchanged.

    An omitted ``until`` is the moment the request is handled, in UTC, and it is
    resolved HERE rather than by a ``Query(default_factory=...)``: a factory
    still hands an in-process caller the factory's declaration object instead of
    a datetime (see the parameter-declaration rule above), which is how a
    ``Query(...)`` reached a SQL bind in CI run 35959902953. ``since`` stays
    optional because only ``/overview`` treats it as one, and there ``_window``
    turns it into a trailing ``days`` window.

    Two more refusals live here, and they are about the window's SHAPE rather
    than its spelling (gap P7):

    * ``[since, until)`` is an interval, so an inverted or empty one is a
      mistake, not a result. It selected nothing and answered 200 with a column
      of zeroes — the same class of 200-shaped-422 as ``{"error": ...}``.
    * the span is capped at :data:`MAX_WINDOW_DAYS`. ``days`` already carried
      that ceiling; ``since`` did not have one, so 26 years of payments-and-
      refunds aggregate was legal only by spelling the window the other way
      round, on the same route, behind a screen that polls every 20 seconds.

    Both are checked BEFORE anything is returned, so a refused request has run no
    query: the callers' own fakes assert that.
    """
    until = datetime.now(UTC) if until is None else until
    failures: list[dict] = []
    bound_since = None if since is None else _bind_edge(since, "since", failures)
    bound_until = _bind_edge(until, "until", failures)
    if failures:
        raise HTTPException(status_code=422, detail=failures)
    if bound_since is not None:
        span = bound_until - bound_since
        if span <= timedelta(0):
            raise HTTPException(
                status_code=422,
                detail=[
                    _window_failure(
                        "since",
                        "the window is empty or reversed: [since, until) selects the "
                        f"instants between them, and {bound_since.isoformat()} to "
                        f"{bound_until.isoformat()} selects none — send a `since` "
                        "strictly before its `until`.",
                        bound_since,
                    )
                ],
            )
        if span > timedelta(days=MAX_WINDOW_DAYS):
            raise HTTPException(
                status_code=422,
                detail=[
                    _window_failure(
                        "since",
                        f"the window is {span.days} days wide, and this route binds "
                        f"at most {MAX_WINDOW_DAYS} — the same ceiling `days` "
                        "carries. Ask for a shorter window, or page it.",
                        bound_since,
                    )
                ],
            )
    return bound_since, bound_until


# Metrics whose value is money, so the response must carry the currency the
# amount is denominated in.
_MONEY_METRICS = frozenset({"revenue", "net_revenue", "refunded_amount", "aov"})

#: Ratios that must name their denominator on the wire (§167: "a consumer must
#: say which budget figure it used"). ``roas`` divides by ``campaigns.budget``
#: — money PLANNED, not burned; no spend feed exists in this schema
#: (``marketing/analytics.campaign_actual_spend`` returns {} by design), so a
#: reader that never sees the basis will read a plan as an actual.
_METRIC_BASIS = {"roas": "planned_budget"}

# Every key a read model can return whose value is money. Named per family so
# a gross figure cannot be serialised under a net name, and — the reason this is
# one set rather than a set per route — the averages are money too. FastAPI's
# default encoder resolves a bare ``Decimal`` by casting it to ``float``, so
# "leave it as a Decimal and the framework will cope" is how a cent goes
# missing (ADR-001): every one of these becomes a string on the wire.
_MONEY_FIELDS = frozenset(
    {
        "gross_revenue",
        "net_revenue",
        "refunded_amount",
        "refund_excess",
        "gross_aov",
        "net_aov",
    }
)


def _as_json(value: Decimal | float | int | None) -> str | int | float | None:
    """Money leaves as a STRING; counts and RATIOS leave as NUMBERS; None as null.

    A float would round-trip a cent away from an amount (ADR-001), a stringified
    ratio would disagree with the SAME ratio as marketing ships it
    (``budget_roas=1.5`` is a number there), and ``str(None) == "None"`` would
    turn "no denominator exists" into a four-character lie.
    """
    if value is None or isinstance(value, (int, float)):
        return value
    return str(value)


def _money_json(row: dict) -> dict:
    """Stringify the money fields of one read model, leave the rest alone."""
    return {
        key: (str(value) if key in _MONEY_FIELDS and isinstance(value, Decimal) else value)
        for key, value in row.items()
    }


def _zone_source(zone: object) -> str | None:
    """Which layer of the resolution chain answered, or ``None`` when it said nothing.

    ``timekit.ResolvedTimezone`` IS a string that remembers whether the caller's
    ``?timezone=``, ``tenants.timezone``, ``ANALYTICS_TIMEZONE`` or the UTC
    fallback produced it, and a response that names a zone has to name where it
    came from — "the merchant's day" and "the deployment's guess about the
    merchant's day" are different claims. A zone that arrives here without that
    provenance reports ``null`` rather than letting the router invent a layer,
    which is the same reason ``str(None)`` is not spelled "None" downstream.
    """
    return zone.source if isinstance(zone, ResolvedTimezone) else None


def _window(
    days: int, since: datetime | None, until: datetime
) -> tuple[datetime, datetime]:
    """The one ``[since, until)`` every figure in a payload shares.

    ``since`` wins when given; otherwise the trailing ``days``. A summary and a
    daily series computed on two different windows cannot be reconciled by
    whoever reads them side by side, so this resolves once and callers reuse it.

    Both edges arrive bound by ``_bind_window`` — instants, in UTC — so a
    ``days`` window is the same length of time on every connection.
    """
    start = until - timedelta(days=days) if since is None else since
    return start, until


@router.get("/metrics/definitions", response_model=schemas.MetricDefinitionListOut)
async def list_metric_definitions(ctx: TenantCtxDep) -> dict[str, Any]:
    """§167: list every canonical metric definition.

    The registry is finite and never paged, so it shares the list envelope with a
    ``next_cursor`` of ``null`` rather than inventing a fifth shape for "a list
    that happens to stop" (gap P8).
    """
    return {"items": MetricRegistry.definitions(), "next_cursor": None}


@router.get(
    "/metrics/{metric_name}",
    response_model=schemas.MetricValueOut,
    # The definition keys that travel with a figure depend on WHICH metric was
    # asked for, so an inapplicable key is absent from the payload rather than
    # arriving as a null the handler never built.
    response_model_exclude_unset=True,
)
async def compute_metric(
    metric_name: str,
    ctx: TenantCtxDep,
    since: Annotated[datetime, Query(description=_SINCE_DOC)],
    until: Annotated[datetime | None, Query(description=_UNTIL_DOC)] = None,
) -> dict[str, Any]:
    """Compute a single canonical metric for the tenant's window.

    The response carries the definition the number was computed under
    (``refund_treatment`` says whether refunds were subtracted at all,
    ``timezone_rule`` says how a calendar bucket is taken) so a bare figure can
    never be read as the other family.

    ``value`` is the one field here that answers with three wire types, and the
    split is ADR-001's, not an accident: an AMOUNT (revenue, net_revenue,
    refunded_amount, aov) leaves as a Decimal STRING, a COUNT (orders_count) and
    a RATIO (conversion_rate, roas, the two durations) leave as NUMBERS, and a
    metric with no answer leaves as ``null``. ``_as_json`` applies that split and
    :data:`schemas.MetricValue` refuses a handler that breaks it — in both
    directions, because stringifying a ratio would disagree with the same ratio as
    ``marketing`` ships it.
    """
    since, until = _bind_window(since, until)
    spec = MetricRegistry.get(metric_name)
    value = await analytics_service.compute_metric(
        ctx.session,
        ctx.tenant_id,
        metric_name=metric_name,
        since=since,
        until=until,
    )
    payload: dict = {
        "metric": metric_name,
        "value": _as_json(value),
        "since": since.isoformat(),
        "until": until.isoformat(),
    }
    if spec is not None:
        payload["refund_treatment"] = spec.refund_treatment
        payload["timezone_rule"] = spec.timezone_rule
    if metric_name in _METRIC_BASIS:
        payload["basis"] = _METRIC_BASIS[metric_name]
    if metric_name in _MONEY_METRICS:
        # Money belongs to a tenant and one tenant trades in one currency (§47);
        # the label comes from the tenant row, never from a literal.
        payload["currency"] = await resolve_tenant_currency(ctx.session, ctx.tenant_id)
    return payload


@router.get("/revenue/summary", response_model=schemas.RevenueSummaryOut)
async def revenue_summary(
    ctx: TenantCtxDep,
    since: Annotated[datetime, Query(description=_SINCE_DOC)],
    until: Annotated[datetime | None, Query(description=_UNTIL_DOC)] = None,
    timezone: Annotated[
        str | None,
        Query(description="IANA zone for the day label; defaults to the deployment zone"),
    ] = None,
) -> dict[str, Any]:
    """Gross and net money for one window, each figure named for its family.

    ``net_revenue`` is ``gross_revenue - refunded_amount``, floored at zero;
    whatever could not be subtracted in this window is reported as
    ``refund_excess`` instead of disappearing.
    """
    since, until = _bind_window(since, until)
    resolve_timezone(timezone)  # reject a bad zone before running four queries
    summary = await analytics_service.revenue_summary(
        ctx.session, ctx.tenant_id, since=since, until=until, timezone=timezone
    )
    # The window is part of the answer, not metadata beside it: "the same instant
    # spelled two ways" can only be checked by a client that can read what the
    # server bound.
    return {**_money_json(summary), "since": since.isoformat(), "until": until.isoformat()}


@router.get("/daily-series", response_model=schemas.DailySeriesOut)
async def daily_series(
    ctx: TenantCtxDep,
    since: Annotated[datetime, Query(description=_SINCE_DOC)],
    until: Annotated[datetime | None, Query(description=_UNTIL_DOC)] = None,
    timezone: Annotated[
        str | None,
        Query(
            description=(
                "IANA zone the merchant counts days in. The day LABEL is local to "
                "this zone; since/until remain instants. Omit it and the tenant's "
                "declared zone is used, then the deployment's ANALYTICS_TIMEZONE."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """The merchant's daily revenue series — bucketed in the merchant's day.

    The payload is the ONE list envelope (``items`` + ``next_cursor``, null on a
    bounded series) with its window metadata beside it: this used to answer a
    top-level object with no cursor key at all, which was a fifth spelling of "a
    page of things" (gap P8). The metadata is not decoration — dropping
    ``since``/``until``/``timezone``/``timezone_source`` would take back W5-T2's
    answer to "which window, whose day".
    """
    since, until = _bind_window(since, until)
    resolve_timezone(timezone)  # reject a bad zone before the tenant lookup
    # ONE resolution for both the SQL and this label. The router cannot see
    # ``tenants.timezone``, so resolving the chain here and the service
    # resolving it again produced two answers to one question: Cairo buckets
    # under a deployment-zone label.
    zone = await analytics_service.resolve_report_timezone(
        ctx.session, ctx.tenant_id, timezone
    )
    rows = await analytics_service.daily_revenue_series(
        ctx.session, ctx.tenant_id, since=since, until=until, timezone=zone
    )
    return {
        "timezone": str(zone),
        "timezone_source": _zone_source(zone),
        "since": since.isoformat(),
        "until": until.isoformat(),
        "currency": await resolve_tenant_currency(ctx.session, ctx.tenant_id),
        "next_cursor": None,
        "items": [
            {
                "day": row["day"],
                "orders_count": row["orders_count"],
                "gross_revenue": str(row["gross_revenue"]),
                "refunded_amount": str(row["refunded_amount"]),
                "net_revenue": str(row["net_revenue"]),
                "refund_excess": str(row["refund_excess"]),
            }
            for row in rows
        ],
    }


@router.get("/inventory/stock-health", response_model=schemas.StockHealthOut)
async def stock_health(
    ctx: TenantCtxDep,
    low_stock_threshold: Annotated[
        int,
        Query(
            ge=0,
            le=MAX_LOW_STOCK_THRESHOLD,
            description=(
                "Available units at which a variant counts as low. Bound on both "
                "sides because it reaches SQL as `available <= :threshold`: a "
                "negative selects nothing and a million is not a reorder point, it "
                "is every balance the tenant holds (gap P7)."
            ),
        ),
    ] = analytics_service.LOW_STOCK_THRESHOLD,
) -> dict[str, Any]:
    """Replenishment signal with empty shelves split out of "low stock"."""
    health = await analytics_service.stock_health(
        ctx.session, ctx.tenant_id, low_stock_threshold=low_stock_threshold
    )
    return health


@router.get("/overview", response_model=schemas.AnalyticsOverviewOut)
async def analytics_overview(
    ctx: TenantCtxDep,
    days: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_WINDOW_DAYS,
            description=(
                "Trailing window in days; ignored when `since` is given. Counted "
                "back from `until`, which is an instant, so the window it describes "
                "is the same one on every connection."
            ),
        ),
    ] = 30,
    since: Annotated[
        datetime | None, Query(description=f"{_SINCE_DOC} When given, overrides `days`.")
    ] = None,
    until: Annotated[datetime | None, Query(description=_UNTIL_DOC)] = None,
    timezone: Annotated[
        str | None,
        Query(
            description=(
                "IANA zone the merchant counts days in — the day label is local to "
                "it. Defaults to the deployment's ANALYTICS_TIMEZONE."
            )
        ),
    ] = None,
    low_stock_threshold: Annotated[
        int,
        Query(
            ge=0,
            le=MAX_LOW_STOCK_THRESHOLD,
            description=(
                "Available units at which a variant counts as low. The same bound "
                "the standalone stock-health route carries, because the same "
                "parameter reaches the same `available <= :threshold` bind here "
                "(gap P7)."
            ),
        ),
    ] = analytics_service.LOW_STOCK_THRESHOLD,
) -> dict[str, Any]:
    """One call for the analytics screen: money, orders, AOV, days, stock.

    The screen used to fetch a path this server never published, so every visit
    landed on its error state — and ``as any`` on the response kept the type
    checker from noticing. What it returns is a composition, not a computation:
    every figure comes from a reader in ``analytics/service.py``, the module
    that owns metric SQL since Wave-4 M11. This route adds no query of its own.

    Shape honesty, in the words the registry uses (§167/ADR-053):

    * ``gross_revenue`` is collected money, ``net_revenue`` is what survives the
      refunds that LEFT in the same window, and ``refund_excess`` is the part
      that could not be subtracted because net is floored at zero. No key is
      ever named plain ``revenue``.
    * ``gross_aov``/``net_aov`` say which numerator they used.
    * ``daily_series`` buckets on the MERCHANT's day (gap M10) over the same
      window as the summary, so the bars add up to the cards beside them.
    * ``currency`` is the tenant's (§47) and ``timezone`` is the zone the buckets
      were labelled in; money crosses as strings, counts as integers.
    * ``stock`` separates an empty shelf from a nearly-empty one (gap M7).
    * ``since``/``until`` are the INSTANTS this window bound, in UTC. A window
      given without an offset is refused with a 422 rather than read in whatever
      timezone the connection happens to be in (W5-T2).

    There is deliberately no top-products key: no canonical reader computes one,
    and an invented field is how a screen ends up trusting a number that does
    not exist.

    Every default in the signature above is a VALUE (``30`` days, no ``since``,
    ``until`` resolved by ``_bind_window``, no zone, a threshold of
    ``analytics_service.LOW_STOCK_THRESHOLD``) and not a ``Query(...)``
    declaration. This is the handler that showed why: it used to declare
    ``low_stock_threshold: int = Query(default=2, ...)``, and the seeded case
    ``tests/test_analytics_overview.py::test_overview_reports_seeded_money_in_its_named_families``
    calls it in-process without that argument, so the unconverted ``Query(2)``
    rode into ``stock_health``'s ``:threshold`` bind. See the
    parameter-declaration rule above.
    """
    since, until = _bind_window(since, until)
    zone = resolve_timezone(timezone)  # fail closed before the first query
    start, end = _window(days, since, until)
    summary = _money_json(
        await analytics_service.revenue_summary(
            ctx.session, ctx.tenant_id, since=start, until=end, timezone=zone
        )
    )
    series = await analytics_service.daily_revenue_series(
        ctx.session, ctx.tenant_id, since=start, until=end, timezone=zone
    )
    stock = await analytics_service.stock_health(
        ctx.session, ctx.tenant_id, low_stock_threshold=low_stock_threshold
    )
    summary.update(
        {
            "since": start.isoformat(),
            "until": end.isoformat(),
            "daily_series": [_money_json(row) for row in series],
            "stock": stock,
        }
    )
    return summary


# ======================================================= §55-57 retention ===
#
# Why these two routes exist
# -------------------------
# ``retention.py`` refuses to drop a single month unless EVERY active tenant has
# chosen a policy (``BLOCKED_NO_CHOSEN_POLICY``) — fail-closed, because §56
# partitions by time and never by tenant, so one month belongs to everyone and a
# DROP cannot honour a silence. That made ``choose_policy`` load-bearing, and it
# had no HTTP caller: the purge sweep ran daily and declined daily. The table,
# the rule and the worker were all finished; the merchant had no door. This is
# the same shape as the deleted ``archive_old_rows`` and the 404-ing
# ``/analytics/overview``, so the door — and the refusal made legible — is what
# these two paths are for.
#
# What these routes deliberately do NOT do
# ---------------------------------------
# * own a query or an upsert: every read and write is a call into
#   ``analytics/retention.py``, which stays the ONLY writer of a policy row (the
#   boundary here adds validation, not logic);
# * take a ``tenant_id`` from a client: tenancy is ``ctx.tenant_id``, resolved and
#   RLS-bound by ``get_tenant_ctx`` — a route that accepted one would be a
#   cross-tenant bug with a permission check painted over it;
# * clamp anything. An out-of-range horizon, an unknown status or a store this
#   module cannot execute is a 4xx that names the fix, the way §47 refuses an
#   unknown currency and ``set_timezone`` refuses an unresolvable zone.

#: Two decimal-free integers and one enum: no money crosses these payloads, so
#: no ``str(Decimal)`` rule applies. ``None`` still stays ``None`` — an
#: unanswered question must not serialise as a zero-day horizon.
class RetentionPolicyChoice(BaseModel):
    """Body of ``PUT /analytics/retention/policies/{data_class}``.

    The bounds mirror the migration's CHECK on ``retention_policies``
    (``f7a2c9d4e8b1``) so a client learns the limit from a 422 instead of from a
    database error mid-request. They are NOT a duplicate of the module's own
    guard: ``choose_policy`` still refuses the same range, and a ValueError that
    escapes it is mapped below rather than returned as a 500.
    """

    retention_days: int = Field(
        ge=retention.MIN_RETENTION_DAYS,
        le=retention.MAX_RETENTION_DAYS,
        description=(
            "How long this tenant's rows in the store may live, in days. The "
            "month a shared partition may be dropped at is pinned by the LONGEST "
            "horizon any active tenant chose, so a short number here is honoured "
            "by the row-level worker and never by a DETACH. Below the legal floor "
            "for the store is refused by the database, not clamped."
        ),
    )
    status: Literal["active", "paused"] = Field(
        description=(
            "'active' is the consent that lets a month go; 'paused' is an explicit "
            "withdrawal — it keeps the horizon on record but counts as NOT chosen, "
            "which pins the shared month for every tenant."
        )
    )


def _gate_json(gate: retention.DropGate) -> dict:
    """The whole ``DropGate``, under its own names.

    The counts are all the aggregate is allowed to return: how many tenants exist,
    how many never answered, and the longest horizon. No other tenant's policy,
    store or identity is in here, and this is the only place that shape is
    spelled, so the read route and the write route cannot describe the gate
    differently.
    """
    return {
        "tenant_count": gate.tenant_count,
        "missing_policies": gate.missing_policies,
        "max_days": gate.max_days,
        "may_drop": gate.may_drop,
        "reason": gate.reason,
    }


def _unblock_requires(gate: retention.DropGate) -> list[str]:
    """What would have to change for the gate to open, in the caller's terms.

    A bare ``blocked_reason`` is a verdict; a merchant who is one of the tenants
    holding the month needs the actionable form of it — including the fact that
    the answer they can give is not the whole fix, because the gate is shared.

    Only the PARTITIONED stores can pin a shared month, so only they belong in
    this advice: naming ``messages`` here would send a merchant to fix a store
    whose rows were never part of the question (§56 partitions by time, and a
    row purge asks one tenant, not all of them).
    """
    if gate.may_drop:
        return []
    stores = ", ".join(sorted(retention.PARTITIONED_DATA_CLASSES))
    if gate.reason == retention.BLOCKED_NO_ACTIVE_TENANTS:
        return [
            "No active tenant exists, so there is nothing to consent and nothing "
            "to drop; this is not something a policy row can change."
        ]
    if gate.reason == retention.BLOCKED_NO_CHOSEN_POLICY:
        return [
            f"{gate.missing_policies} of {gate.tenant_count} active tenants have "
            f"no ACTIVE policy for {stores}; a shared month drops only once every "
            "one of them has chosen.",
            "Each of those tenants must PUT /analytics/retention/policies/"
            f"<data_class> with status 'active' (this deployment governs: {stores}).",
            "A 'paused' policy is a withdrawal, not an answer: it pins the month "
            "for every tenant, not only for the one that paused.",
        ]
    return [
        f"The longest horizon on record is {gate.max_days} days; every active "
        f"policy for {stores} must be greater than 0, since a zero would mean "
        "'delete everything now'."
    ]


def _gate_block(gate: retention.DropGate) -> dict:
    return {
        "gate": _gate_json(gate),
        "blocked_reason": None if gate.may_drop else gate.reason,
        "unblock_requires": _unblock_requires(gate),
    }


@router.get("/retention", response_model=schemas.RetentionPositionOut)
async def retention_position(ctx: AnalyticsReadCtx) -> dict[str, Any]:
    """§55-57 read: this tenant's retention policy, the shared gate, and what
    would unblock it.

    ``policies`` is ``retention.policy_position`` verbatim, so the two ways of
    asking "have I chosen" cannot disagree: a row that does not exist and a row
    that exists as ``paused`` both read back as ``chosen: false``, with the
    status and horizon that produced that answer beside them (``null`` for a
    question never answered — deliberately not 0, which would read as an
    instant-delete policy). The horizon this door pre-fills is
    ``offered_default_days`` (a store with no documented duration gets no
    suggestion), and ``legal_floor_months`` is the 13 months no SHARED month may
    be dropped under.

    Every store a policy can govern is listed, month-purged or row-purged, and
    ``purge_paths`` says which: ``["partition"]`` data leaves as whole months,
    ``["row"]`` data leaves as one tenant's own rows. For the row stores
    ``row_gate_reason`` is the answer that matters and ``shared_gate_reason`` is
    ``null`` — another tenant's silence cannot block a purge of this tenant's
    rows, and reporting it would send the merchant to fix the wrong thing.

    ``blocked_reason`` and ``gate`` are ``evaluate_gate``'s answer for the shared
    month, computed by ``read_drop_gate`` from the database's own SECURITY
    DEFINER aggregate. They are GLOBAL by construction — §56 partitions by time,
    so a month is shared — and they expose counts and the longest horizon only,
    never another tenant's policy or existence by name.
    """
    gate = await retention.read_drop_gate(ctx.session)
    position = await retention.policy_position(ctx.session, ctx.tenant_id)
    return {"policies": position, **_gate_block(gate)}


@router.put(
    "/retention/policies/{data_class}", response_model=schemas.RetentionPolicyWriteOut
)
async def choose_retention_policy(
    data_class: str, body: RetentionPolicyChoice, ctx: AnalyticsWriteCtx
) -> dict[str, Any]:
    """§55-57 write: choose (or withdraw) this tenant's retention policy.

    The door the gate was waiting for. It calls ``retention.choose_policy`` — the
    module's ONLY writer, an upsert on ``(tenant_id, data_class)`` so one tenant
    cannot hold two contradicting answers — and it writes nothing of its own.
    ``ctx.tenant_id`` is the only tenancy in play; ``retention_policies`` is
    FORCE RLS with a ``WITH CHECK`` guard, so the row that lands is this tenant's.

    Every refusal happens BEFORE the first query: an unknown store, a horizon
    outside 1..3650, or a status outside ``active``/``paused`` is a 4xx naming
    the fix, and no policy row and no audit row are produced. Nothing is clamped
    into range, because a silently-adjusted horizon is a delete the merchant did
    not agree to.

    Audited through ``app.core.audit`` with the previous answer as the ``before``
    image: this write is permission to DELETE — this tenant's own rows for a row
    store, every tenant's shared month for a partitioned one — so "who said what,
    when, replacing what" is the record that has to exist afterwards (§66). The
    gate is re-read after the write and returned, so the caller sees immediately
    whether the month is now droppable or still pinned by someone else's silence.
    """
    allowed = sorted(retention.CHOOSABLE_DATA_CLASSES)
    if data_class not in retention.CHOOSABLE_DATA_CLASSES:
        raise ValidationError(
            f"unknown data_class {data_class!r}: the stores a chosen policy can "
            f"execute against are {', '.join(allowed)}. 'audit_logs' is under "
            "legal retention (§57) so it never will be, and a store with no "
            "executor in this module is refused rather than parked as a policy "
            "that governs nothing.",
            details={"data_class": data_class, "allowed": allowed},
        )

    previous = await retention.read_policy(ctx.session, ctx.tenant_id, data_class)
    enabled = body.status == retention.POLICY_ACTIVE
    try:
        chosen = await retention.choose_policy(
            ctx.session,
            ctx.tenant_id,
            data_class,
            retention_days=body.retention_days,
            enabled=enabled,
        )
    except ValueError as exc:
        # Unreachable with the model above in place; mapped rather than trusted,
        # because a module guard escaping as a 500 is how a bad request starts
        # looking like the server's fault.
        raise ValidationError(str(exc)) from exc

    gate = await retention.read_drop_gate(ctx.session)
    before = (
        None
        if previous is None
        else {
            "status": previous["status"],
            "retention_days": previous["retention_days"],
        }
    )
    await write_audit_row(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        retention.CHOOSE_AUDIT_ACTION,
        retention.CHOOSE_AUDIT_RESOURCE,
        data_class,
        before=before,
        after={
            "data_class": data_class,
            "retention_days": body.retention_days,
            "status": body.status,
            "chosen": enabled,
            "shared_gate": _gate_json(gate),
        },
    )
    return {"policy": chosen, **_gate_block(gate)}


