"""§55 / §167 — the analytics API must answer every metric it advertises.

``GET /analytics/metrics/definitions`` publishes EVERY name in the canonical
registry (``platform/metrics.py``), and ``tests/test_flags_metrics.py`` pins
``conversion_rate`` and ``roas`` as REQUIRED. But the §55 pipeline ends with
"Analytics API", and the API had no query behind those two names: asking for
either raised a bare ``ValueError`` from ``compute_metric`` — which ``app.main``
does not map (only ``DomainError`` subclasses get the unified error contract),
so a merchant-visible read endpoint answered a documented request with a 500.
The same applied to an unknown metric name: 500 where a 404 is the honest
answer. And the ratio/None wire shapes in ``_as_json`` contradicted the repo's
own rule (amounts leave as strings, RATIOS as numbers — marketing/analytics.py
ships ``budget_roas=1.5`` as a number while this route stringified every
float, and ``None`` would have shipped as the STRING ``"None"``).

The pins below, in the order a reviewer should read them:

1. parity: every registry name has a handler in ``METRIC_HANDLERS`` (the two
   sets cannot drift again — the definitions route would be advertising
   numbers this module cannot produce);
2. a name the registry does not know is a ``NotFoundError`` (404 at the edge),
   raised BEFORE any query runs;
3. ``conversion_rate`` and ``roas`` compute exactly what their registry rows
   pin: purchases/touchpoints, and last-touch credit over the campaigns'
   PLANNED budget (a ratio that must name its denominator — the roas response
   carries ``basis='planned_budget'``);
4. the money/ratio/None wire shapes of ``_as_json``;
5. a naive window edge is refused by the new readers the same way the existing
   ones refuse it (W5-T2), before touching the session.

Cases 1-4 and the refusal cases are DB-free (a recording-refusing fake session
proves "before any query"). The value cases need the real database and skip
without ``DATABASE_URL_APP_ADMIN`` — CI proves them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.main import create_app
from app.modules.analytics import router as analytics_router
from app.modules.analytics import service as analytics_service
from app.modules.customers.models import Customer
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.marketing.service import MarketingService
from app.modules.platform.metrics import MetricRegistry

SEALED_TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
SINCE = "2026-09-01T00:00:00Z"
UNTIL = "2026-09-02T00:00:00Z"


class _NoQueriesSession:
    """Any statement at all is the defect: refusals happen before binds."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement, _params=None):  # noqa: ANN001
        self.statements.append(str(statement))
        raise AssertionError("a query ran for a request that must be refused first")


def _app() -> FastAPI:
    app = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=_NoQueriesSession(),
            user=AuthedUser(id=uuid.uuid4(), tenant_id=SEALED_TENANT, role_code="owner"),
            tenant_id=SEALED_TENANT,
            role_code="owner",
            permission_codes=set(),
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test")


# ================================================= 1. registry/API parity ===


def test_every_canonical_metric_has_a_canonical_query() -> None:
    """``/metrics/definitions`` advertises the whole registry; the dispatch
    table behind ``/metrics/{name}`` must answer exactly the same set.

    ``conversion_rate`` and ``roas`` were in the advertisement with no query
    behind them, and asking for either was a 500.
    """
    assert set(analytics_service.METRIC_HANDLERS) == set(MetricRegistry.names())


# =============================================== 2. unknown name -> 404 =====


async def test_an_unknown_metric_raises_a_domain_not_found_not_a_value_error() -> None:
    """ValueError at the edge is a 500; the registry-not-known case is 404."""
    with pytest.raises(NotFoundError):
        await analytics_service.compute_metric(
            _NoQueriesSession(),  # type: ignore[arg-type]
            SEALED_TENANT,
            metric_name="not_a_metric",
            since=datetime(2026, 9, 1, tzinfo=UTC),
            until=datetime(2026, 9, 2, tzinfo=UTC),
        )


async def test_the_unknown_metric_refusal_runs_no_query() -> None:
    session = _NoQueriesSession()
    with pytest.raises(NotFoundError):
        await analytics_service.compute_metric(
            session,  # type: ignore[arg-type]
            SEALED_TENANT,
            metric_name="not_a_metric",
            since=datetime(2026, 9, 1, tzinfo=UTC),
            until=datetime(2026, 9, 2, tzinfo=UTC),
        )
    assert session.statements == []


async def test_the_route_answers_404_not_500_for_an_unknown_metric() -> None:
    async with _client() as client:
        response = await client.get(
            f"/api/v1/analytics/metrics/not_a_metric?since={SINCE}&until={UNTIL}"
        )
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"


# ==================================================== 4. wire-shape rules ===


def test_money_still_leaves_as_a_string() -> None:
    assert analytics_router._as_json(Decimal("150.00")) == "150.00"


def test_a_ratio_leaves_as_a_number_not_a_string() -> None:
    """ADR-001's split: amounts are strings, ratios are numbers.

    marketing/analytics.py ships ``budget_roas=1.5`` as a number; the same
    ratio leaving the canonical route as ``"1.5"`` is two screens disagreeing
    about the type of one number.
    """
    assert analytics_router._as_json(1.5) == 1.5


def test_a_missing_answer_leaves_as_json_null_not_the_string_None() -> None:
    """``str(None) == 'None'`` — a roas with no denominator must not ship as
    the four-letter string 'None' (and 0.0 is not acceptable either: it reads
    as 'returned nothing', when the truth is 'there was no denominator')."""
    assert analytics_router._as_json(None) is None


# ============================================ naive windows still refused ===


@pytest.mark.parametrize("metric_name", ["conversion_rate", "roas"])
async def test_the_new_readers_refuse_a_naive_window_before_any_bind(
    metric_name: str,
) -> None:
    """W5-T2's rule applies to every reader this module adds, not just to the
    money ones: a wall clock is not an instant. session=None proves the bind
    happens first — the function raises before it would ever touch it."""
    naive = datetime(2026, 9, 1)
    handler = analytics_service.METRIC_HANDLERS[metric_name]
    with pytest.raises(ValidationError):
        await handler(
            None,  # type: ignore[arg-type]
            SEALED_TENANT,
            since=naive,
            until=naive + timedelta(days=1),
        )


# ==================================================== 3. the real numbers ====


@pytest.fixture
async def attribution_seed(db: AsyncSession, tenant_ctx):
    """One campaign (budget 100), one touchpoint, one 150-value purchase with
    its last-touch attribution — the same shape test_analytics.py seeds, and
    the smallest dataset that can answer BOTH new metrics at once:
    conversion_rate = 1 purchase / 1 touchpoint = 1.0, roas = 150/100 = 1.5."""
    tenant_id = tenant_ctx.tenant_id

    campaign = await MarketingService.create_campaign(
        db, tenant_id, name="Ramadan Sale", provider="facebook", budget=100
    )
    customer = Customer(tenant_id=tenant_id, name="Attribution Customer")
    db.add(customer)
    await db.flush()

    await MarketingService.record_touchpoint(
        db, tenant_id, customer_id=customer.id, source="facebook", campaign_id=campaign.id
    )
    await MarketingService.record_conversion(
        db, tenant_id, customer_id=customer.id, value=150
    )
    await db.flush()
    return {"tenant_id": tenant_id, "campaign_id": campaign.id}


def _open_window() -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    return now - timedelta(hours=1), now + timedelta(hours=1)


async def test_conversion_rate_is_purchases_over_touchpoints(
    db: AsyncSession, attribution_seed
) -> None:
    """§55 read model, registry-pinned: purchase conversions / touchpoints."""
    since, until = _open_window()
    rate = await analytics_service.conversion_rate(
        db, attribution_seed["tenant_id"], since=since, until=until
    )
    assert rate == 1.0


async def test_conversion_rate_is_zero_when_nothing_was_touched(
    db: AsyncSession, attribution_seed
) -> None:
    """A tenant with no touchpoints has no denominator: 0.0, the same answer
    ``ai_resolution_rate`` gives for an empty population (never a 500, never
    a division error)."""
    since, until = _open_window()
    rate = await analytics_service.conversion_rate(
        db, uuid.uuid4(), since=since, until=until
    )
    assert rate == 0.0


async def test_roas_is_return_over_the_plan_and_names_its_denominator(
    db: AsyncSession, attribution_seed
) -> None:
    """The registry pins roas to last-touch credit / campaigns.budget, and a
    consumer "must say which budget figure it used" — 150/100 = 1.5, computed
    in Decimal, delivered as a number."""
    since, until = _open_window()
    value = await analytics_service.roas(
        db, attribution_seed["tenant_id"], since=since, until=until
    )
    assert value == 1.5


async def test_roas_is_none_when_no_campaign_budgeted_anything(
    db: AsyncSession, attribution_seed
) -> None:
    """No denominator is not 0.00 returned: 0.0 would read as 'spent, got
    nothing back'. ``None`` leaves as JSON null (see the _as_json pin above)."""
    since, until = _open_window()
    value = await analytics_service.roas(db, uuid.uuid4(), since=since, until=until)
    assert value is None


# ============================== the route-level basis label on the roas ====


async def test_the_roas_response_carries_its_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§167: a ratio names its denominator on the wire. The value handler is
    stubbed so the pin is about the ROUTE payload, not the SQL."""

    async def metric(session, tenant_id, *, metric_name, since, until):  # noqa: ANN001
        return 1.5

    monkeypatch.setattr(analytics_service, "compute_metric", metric)
    async with _client() as client:
        response = await client.get(
            f"/api/v1/analytics/metrics/roas?since={SINCE}&until={UNTIL}"
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["basis"] == "planned_budget"
    assert body["value"] == 1.5
