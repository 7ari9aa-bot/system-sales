"""P7 + P8, closed for the two report-generating modules.

The gap-register entries this file retires
-----------------------------------------
``P8`` — *"Three list envelopes (bare array / {items,next_cursor} / unions) +
~45 of 62 routes untyped (no response_model) → OpenAPI useless."*
``P7`` — *"two sort keys between page 1 and page N; negative/unbounded
limit/offset/days."*

Measured before this file existed: ``marketing/router.py`` published 0 of its
routes with a ``response_model``, ``analytics/router.py`` 0 of 8 — every one of
them annotated ``-> dict``, which FastAPI turns into a schema that says "an
object, keys unknown". Typed in Python, untyped on the wire.

Why a ``response_model`` is worth having here, in one test
---------------------------------------------------------
A declared model is only useful if it holds a rule the encoder can break. The
rule is ADR-001/§47: **an AMOUNT leaves as a Decimal STRING; a RATIO and a COUNT
leave as NUMBERS.** ``marketing/analytics.wire_money`` and
``analytics/router._money_json`` already obey it, and ``test_roas.py``,
``test_attribution_money_wire.py`` and ``test_analytics_overview.py`` pin that
layer. None of those can see the route: FastAPI's default encoder resolves a
bare ``Decimal`` by casting it to ``float``, so a future handler that forgets
``wire_money`` would ship ``150.0`` with every existing test still green. A
``str`` field turns that into a refusal at the boundary — tested here in BOTH
directions, because a model that stringified ``budget_roas`` to look conformant
would be the same class of bug wearing the flag.

The envelope (P8)
-----------------
Every list these two modules return answers exactly ``{items, next_cursor}``.
Four spellings existed: ``{items,next_cursor}`` (campaigns), ``{items,count}``
(campaign conversions — where ``count`` was the page length wearing a total's
name), ``{items}`` (journey runs) and a bare top-level array (daily-orders).
``next_cursor`` is ``null`` on the bounded lists: a 365-day series and the closed
metric registry have no next page, and saying so with the same key is what makes
the shape one shape instead of four readers.

**The exception is pinned, not trusted.** The composed summaries keep their BARE
nested arrays, because ``frontend/src/lib/queries.ts`` types ``revenue_by_source:
AttributedBySource[]``, ``revenue_by_campaign: AttributedByCampaign[]``,
``daily_orders: DailyOrderRow[]`` and ``daily_series: OverviewDailyRow[]``.
Wrapping a nested array breaks the screen for a cosmetic win, so it is reported
rather than done — and ``test_the_nested_arrays_the_frontend_types_stay_bare``
makes that a claim a later sweep cannot quietly undo.

Naive input, re-checked rather than assumed
-------------------------------------------
W5-T2 bound every dated analytics route through one seam (``_bind_window``) and
``test_analytics_window_binding.py`` proves it for all four. What that proof does
not cover is this pair's *other* date entry point — ``POST /marketing/conversions``
accepts a naive ``occurred_at`` and writes it into a ``timestamptz`` column, the
identical defect on the side where the value becomes permanent — and the window's
WIDTH, which ``since``/``until`` never bounded at all (``days`` is capped at 365
while an explicit ``since`` of 1970 was unlimited, on the same route, for the same
query).

DB-free throughout: each route's read models are replaced by stubs, and one fake
session refuses to run a query for a request that should never have reached it.
"""

from __future__ import annotations

import inspect
import typing
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.main import create_app
from app.modules.analytics import retention
from app.modules.analytics import router as analytics_router
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.marketing import analytics as marketing_analytics
from app.modules.marketing import router as marketing_router
from app.modules.marketing.attribution_service import AttributionService
from app.modules.marketing.service import MarketingService

TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
CAMPAIGN = uuid.UUID("33333333-3333-3333-3333-333333333333")
CONVERSION = uuid.UUID("44444444-4444-4444-4444-444444444444")
TOUCHPOINT = uuid.UUID("55555555-5555-5555-5555-555555555555")
JOURNEY = uuid.UUID("66666666-6666-6666-6666-666666666666")

#: The two modules under contract. ``marketing`` ships TWO routers (its own
#: surface plus the campaign-analytics router mounted at ``/analytics``);
#: ``analytics`` ships one.
OWNED_ROUTERS = (
    marketing_router.router,
    marketing_router.analytics_router,
    analytics_router.router,
)

#: The money keys, by the names the read models use. Every one of these is an
#: amount and therefore a string; the ratio names beside them are the exceptions.
MONEY_FIELDS = frozenset(
    {
        "budget",
        "value",
        "revenue",
        "credited_value",
        "credited_revenue",
        "planned_budget",
        "actual_spend",
        "gross_revenue",
        "net_revenue",
        "refunded_amount",
        "refund_excess",
        "gross_aov",
        "net_aov",
    }
)
RATIO_FIELDS = frozenset({"budget_roas", "spend_roas", "weight", "conversion_rate"})

#: The one field that is deliberately polymorphic: ``MetricValueOut.value`` answers
#: money, counts and ratios from a single model — ``analytics/schemas.py``'s
#: ``MetricValue`` says so out loud, and
#: ``test_the_metric_value_keeps_amount_count_and_ratio_types_apart`` (which is
#: green) pins that a Decimal leaves as ``"150.00"`` while 7 and 1.5 leave as
#: numbers. The blanket rule below would demand it be STRING-ONLY and so would
#: forbid the count arm — an absurd contract. It is checked by the rule that
#: actually matters instead: the money rule must survive inside the union, which
#: means one arm is a string carrying the money pattern.
POLYMORPHIC_MONEY = frozenset({("MetricValueOut", "value")})
MONEY_PATTERN = r"^-?\d+\.\d{2}$"


# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------


class _Row:
    """An ORM-shaped row: attribute access, with ``created_at`` + ``id`` for a cursor."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """Records the SQL a route tried to run and hands back canned rows.

    ``statements`` is how a test asserts the ``ORDER BY`` a paged list needs;
    ``raise_on_query`` is the guarantee the analytics window tests already use —
    a request refused at the boundary must not have spent a query.
    """

    def __init__(self, rows: list[Any] | None = None, *, raise_on_query: bool = False) -> None:
        self.rows = rows or []
        self.statements: list[str] = []
        self.raise_on_query = raise_on_query

    async def execute(self, statement: Any, _params: Any = None) -> _Result:
        self.statements.append(str(statement))
        if self.raise_on_query:
            raise AssertionError(
                "a query ran for a request that should have been refused at the boundary"
            )
        return _Result(self.rows)


def _app(session: FakeSession, *, permissions: set[str] | None = None) -> FastAPI:
    app = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=session,
            user=AuthedUser(id=uuid.uuid4(), tenant_id=TENANT, role_code="owner"),
            tenant_id=TENANT,
            role_code="owner",
            permission_codes=set(permissions or set()),
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


async def _get(session: FakeSession, path: str, *, permissions: set[str] | None = None):
    async with AsyncClient(
        transport=ASGITransport(app=_app(session, permissions=permissions)), base_url="http://test"
    ) as client:
        return await client.get(path)


async def _post(
    session: FakeSession, path: str, body: dict, *, permissions: set[str] | None = None
):
    async with AsyncClient(
        transport=ASGITransport(app=_app(session, permissions=permissions)), base_url="http://test"
    ) as client:
        return await client.post(path, json=body)


async def _put(
    session: FakeSession, path: str, body: dict, *, permissions: set[str] | None = None
):
    async with AsyncClient(
        transport=ASGITransport(app=_app(session, permissions=permissions)), base_url="http://test"
    ) as client:
        return await client.put(path, json=body)


def _routes(module_router: Any) -> list[APIRoute]:
    return [r for r in module_router.routes if isinstance(r, APIRoute)]


def _models_of(declared: Any) -> list[type[BaseModel]]:
    """Every ``BaseModel`` a declared response model resolves to, unions unwrapped.

    ``/marketing/attribution`` legitimately answers two different payloads on one
    path, and a union of two real models is the honest way to publish that. What
    is NOT honest is ``dict``, ``None``, or a union with an untyped arm in it —
    so the unwrapping is exhaustive and the caller asserts on the result.
    """
    if declared is None:
        return []
    if isinstance(declared, type) and issubclass(declared, BaseModel):
        return [declared]
    models: list[type[BaseModel]] = []
    for arg in typing.get_args(declared):
        models.extend(_models_of(arg))
    return models


def _route(path: str) -> APIRoute:
    """The route object for one path, addressing routers by their OWN prefix."""
    for owned in OWNED_ROUTERS:
        for route in _routes(owned):
            if route.path == path:
                return route
    raise AssertionError(f"{path} is not mounted on marketing/analytics")


def _error_text(response: Any) -> str:
    detail = response.json().get("detail")
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        return str(detail)
    return " ".join(
        f"{'.'.join(str(p) for p in item.get('loc', []))} {item.get('msg', '')}"
        for item in detail or []
        if isinstance(item, dict)
    )


# ==========================================================================
# 1. P8, first half: every route declares a real response_model
# ==========================================================================


def test_every_route_in_marketing_and_analytics_declares_a_response_model() -> None:
    """0 of 17 and 0 of 8 measured before this change.

    A handler annotated ``-> dict`` is not typed either: FastAPI emits
    ``{"type": "object"}`` with no properties, which is the same statement a
    missing annotation makes and is why ``dict`` is refused explicitly.
    """
    untyped: list[str] = []
    total = 0
    for owned in OWNED_ROUTERS:
        for route in _routes(owned):
            total += 1
            if not _models_of(route.response_model):
                untyped.append(
                    f"{sorted(route.methods)[0]} {route.path} -> "
                    f"{getattr(route.response_model, '__name__', route.response_model)!r}"
                )
    assert total >= 25, f"the walk reached only {total} routes — it is not covering both modules"
    assert not untyped, "these routes publish no schema:\n  " + "\n  ".join(untyped)


def test_the_declared_models_are_published_in_openapi_not_just_declared() -> None:
    """A ``$ref`` to an empty schema is a contract nobody can read.

    Guards the direction the framework can break silently: a generic built at
    import time, or a model with no annotated fields, passes the isinstance check
    above while publishing nothing.
    """
    schema = create_app().openapi()
    components = schema.get("components", {}).get("schemas", {})

    checked = 0
    for owned in OWNED_ROUTERS:
        for route in _routes(owned):
            method = sorted(route.methods)[0].lower()
            # A response's media lives under `responses/<code>`, not on the
            # operation — reading `[method]["content"]` is a KeyError on every
            # route and proves nothing about any of them.
            responses = schema["paths"][f"/api/v1{route.path}"][method]["responses"]
            bodies = [
                (code, content["application/json"])
                for code, resp in responses.items()
                if code.startswith("2")
                for content in [resp.get("content") or {}]
                if content.get("application/json")
            ]
            assert bodies, (
                f"{method.upper()} {route.path} publishes no 2xx JSON body at all: "
                f"{sorted(responses)}"
            )
            for _code, content in bodies:
                ref = _first_ref(content["schema"])
                assert ref, f"{route.path} publishes no schema reference: {content['schema']}"
                name = ref.rsplit("/", 1)[-1]
                assert name in components, f"{route.path} references a missing schema {name!r}"
                assert components[name].get("properties") or components[name].get("anyOf"), (
                    f"{route.path} resolves to {name}, which declares nothing: {components[name]}"
                )
            checked += 1
    assert checked >= 25, f"only {checked} routes were checked"


def _first_ref(spec: dict) -> str | None:
    """The schema name a published response resolves to, through anyOf/items."""
    if "$ref" in spec:
        return spec["$ref"]
    for key in ("items", "additionalProperties"):
        child = spec.get(key)
        if isinstance(child, dict) and "$ref" in child:
            return child["$ref"]
    for arm in spec.get("anyOf", []) or spec.get("allOf", []) or []:
        if "$ref" in arm:
            return arm["$ref"]
        nested = arm.get("items")
        if isinstance(nested, dict) and "$ref" in nested:
            return nested["$ref"]
    return None


def test_no_handler_still_annotates_its_return_as_a_bare_dict() -> None:
    """``-> dict`` is the shape this sweep removed.

    It reads as typed and publishes nothing, so a client generator emits
    ``Record<string, unknown>`` for every one of the analytics routes.
    """
    offenders = [
        route.path
        for owned in OWNED_ROUTERS
        for route in _routes(owned)
        if inspect.signature(route.endpoint).return_annotation in ("dict", dict)
    ]
    assert not offenders, f"still annotated -> dict: {offenders}"


# ==========================================================================
# 2. The money-string rule, enforced at the boundary rather than by review
# ==========================================================================


def test_a_money_field_refuses_a_float_a_decimal_and_an_int() -> None:
    """ADR-001 at the route layer: an amount that arrives unformatted is refused.

    This is the half the read-model tests cannot see. ``wire_money`` is correct
    today; a handler that returned the ``Decimal`` straight would have FastAPI
    cast it to ``float`` on the way out and keep every existing test green,
    because they assert on the read model, not on the encoder.
    """
    model = marketing_router.CampaignOut
    base = {
        "id": str(CAMPAIGN),
        "name": "Ramadan Sale",
        "provider": "facebook",
        "external_id": None,
        "objective": None,
        "status": "draft",
        "created_at": "2026-09-01T00:00:00+00:00",
    }

    assert model(**base, budget="150.00").budget == "150.00"
    assert model(**base, budget=None).budget is None
    for wrong in (Decimal("150.00"), 150.0, 150):
        try:
            model(**base, budget=wrong)
        except PydanticValidationError:
            continue
        raise AssertionError(f"{type(wrong).__name__} {wrong!r} was accepted into a money field")


def test_a_ratio_refuses_to_become_a_string_by_mistake() -> None:
    """The other direction, which a blanket "money is a string" would break.

    ``budget_roas`` is a dimensionless share: marketing already ships it as
    ``1.5`` and ``test_roas.py`` pins ``isinstance(row["budget_roas"], float)``.
    A model that stringified a ratio to look conformant would disagree with the
    same figure on the other screen.
    """
    model = marketing_router.RoasRowOut
    row = {
        "campaign_id": CAMPAIGN,
        "name": "Ramadan Sale",
        "revenue": "150.00",
        "planned_budget": "100.00",
        "actual_spend": None,
        "basis": "planned_budget",
        "budget_roas": 1.5,
        "spend_roas": None,
    }
    assert model(**row).budget_roas == 1.5
    try:
        model(**{**row, "budget_roas": "1.5"})
    except PydanticValidationError:
        return
    raise AssertionError("a ratio was accepted as a string")


async def test_a_credited_amount_leaves_the_attribution_route_as_a_string() -> None:
    """The float-on-the-wire bug, pinned one layer closer to the client.

    ``AttributionService.compute_for_conversion`` returns ORM rows whose
    ``credited_value`` is a ``Decimal``. This drives the real route with the real
    ``Decimal`` and reads the PARSED JSON, which is where a float would have been
    introduced — ``test_attribution_money_wire.py`` stops one function earlier.
    """
    rows = [
        _Row(
            touchpoint_id=TOUCHPOINT,
            model="first_touch",
            weight=1.0,
            credited_value=Decimal("999999999999.99"),
        )
    ]

    async def fake(_session, _tenant, _conversion_id, **_kw):  # noqa: ANN001
        return rows

    original = AttributionService.compute_for_conversion
    AttributionService.compute_for_conversion = staticmethod(fake)  # type: ignore[method-assign]
    try:
        response = await _get(
            FakeSession(), f"/api/v1/marketing/attribution?conversion_id={CONVERSION}"
        )
    finally:
        AttributionService.compute_for_conversion = original  # type: ignore[method-assign]

    assert response.status_code == 200, response.text
    body = response.json()
    credit = body["touchpoints"][0]["credited_value"]
    assert credit == "999999999999.99", f"an amount left as {credit!r}"
    assert Decimal(credit) - Decimal("999999999999.98") == Decimal("0.01")
    # `weight` is a share of one whole, not money: it stays a number beside it.
    assert isinstance(body["touchpoints"][0]["weight"], float)


def test_the_published_money_fields_are_strings_everywhere() -> None:
    """The rule as a published contract, not as a code reading.

    Every money key in both modules' schemas resolves to ``string``; no money key
    is published as ``number`` (the shape that loses a cent) and no ratio is
    published as ``string`` (the shape that disagrees with the same ratio on the
    other module).
    """
    components = create_app().openapi()["components"]["schemas"]
    found_money: set[str] = set()
    found_ratios: set[str] = set()

    for name, entry in components.items():
        for field, spec in (entry.get("properties") or {}).items():
            types = {arm.get("type") for arm in spec.get("anyOf", [spec])}
            if (name, field) in POLYMORPHIC_MONEY:
                found_money.add(f"{name}.{field}")
                arms = spec.get("anyOf", [spec])
                money_arms = [
                    arm
                    for arm in arms
                    if arm.get("type") == "string" and arm.get("pattern") == MONEY_PATTERN
                ]
                assert money_arms, (
                    f"{name}.{field} answers money among its kinds, but no arm is the "
                    f"Decimal STRING at the money scale — money published as a number "
                    f"loses a cent: {spec}"
                )
            elif field in MONEY_FIELDS:
                found_money.add(f"{name}.{field}")
                assert "number" not in types and "integer" not in types, (
                    f"{name}.{field} is money published as a number: {spec}"
                )
                assert "string" in types, f"{name}.{field} is not a string: {spec}"
            elif field in RATIO_FIELDS:
                found_ratios.add(f"{name}.{field}")
                assert "string" not in types, f"{name}.{field} is a ratio published as a string"

    assert len(found_money) >= 10, f"only {sorted(found_money)} money fields are published"
    assert "RoasRowOut.budget_roas" in found_ratios, sorted(found_ratios)


# ==========================================================================
# 3. P8, second half: ONE list envelope across both modules
# ==========================================================================

#: Routes whose payload IS a list: they must all answer the same two keys.
LIST_ROUTES = (
    "/marketing/campaigns",
    "/marketing/campaigns/{campaign_id}/conversions",
    "/journeys/{journey_id}/runs",
    "/analytics/daily-orders",
    "/analytics/metrics/definitions",
    "/analytics/daily-series",
)


def test_every_list_route_publishes_the_same_envelope() -> None:
    """``{items, next_cursor}`` and nothing else paging-shaped.

    Before: ``{items,next_cursor}`` (campaigns), ``{items,count}`` (campaign
    conversions, where ``count`` was the page length wearing a total's name),
    ``{items}`` (journey runs) and a bare top-level array (daily-orders). Four
    spellings of one concept is four client readers, which is what P8 counts.
    """
    offenders = {}
    for path in LIST_ROUTES:
        model = _route(path).response_model
        fields = set(getattr(model, "model_fields", {}))
        if fields != {"items", "next_cursor"}:
            offenders[path] = fields or getattr(model, "__name__", model)
    assert not offenders, f"these lists do not share the envelope: {offenders}"


def test_the_nested_arrays_the_frontend_types_stay_bare() -> None:
    """The exception, pinned so a later sweep cannot "unify" it by accident.

    ``frontend/src/lib/queries.ts`` reads these four as arrays today
    (``AttributedBySource[]``, ``AttributedByCampaign[]``, ``DailyOrderRow[]``,
    ``OverviewDailyRow[]``). Wrapping a nested array is a frontend break for a
    cosmetic win, so the shape is left alone — and recorded as a decision.
    """
    components = create_app().openapi()["components"]["schemas"]
    for schema_name, field in (
        ("MarketingSummaryOut", "revenue_by_source"),
        ("MarketingSummaryOut", "revenue_by_campaign"),
        ("MarketingSummaryOut", "campaign_budget_roas"),
        ("DashboardOut", "daily_orders"),
        ("DashboardOut", "revenue_by_source"),
        ("AnalyticsOverviewOut", "daily_series"),
    ):
        assert schema_name in components, f"{schema_name} was never published"
        spec = components[schema_name]["properties"][field]
        assert spec.get("type") == "array" or "items" in spec, (
            f"{schema_name}.{field} stopped being a bare array: {spec}"
        )


# ==========================================================================
# 4. P7: paging and range parameters are clamped at the boundary
# ==========================================================================

_ORDERS_BLOCK = {
    "orders_count": 0,
    "gross_revenue": "0.00",
    "refunded_amount": "0.00",
    "net_revenue": "0.00",
    "refund_excess": "0.00",
    "gross_aov": "0.00",
    "net_aov": "0.00",
    "currency": "EGP",
    "timezone": "UTC",
}


def _stub_marketing_readers(monkeypatch) -> None:  # noqa: ANN001
    """Replace every marketing read model with a fixed, schema-shaped answer."""

    async def orders(session, tenant_id, **kw):  # noqa: ANN001, ARG001
        return dict(_ORDERS_BLOCK)

    async def empty_list(session, tenant_id, *a, **kw):  # noqa: ANN001, ARG001
        return []

    async def dashboard(session, tenant_id):  # noqa: ANN001, ARG001
        return {
            "orders": dict(_ORDERS_BLOCK),
            "ai_orders_30d": 0,
            "conversations": {"open": 0, "unread": 0},
            "customers": 0,
            "products_active": 0,
            "low_stock_count": 0,
            "out_of_stock_count": 0,
            "low_stock_threshold": 2,
        }

    monkeypatch.setattr(marketing_analytics, "orders_summary", orders)
    monkeypatch.setattr(marketing_analytics, "revenue_by_source", empty_list)
    monkeypatch.setattr(marketing_analytics, "revenue_by_campaign", empty_list)
    monkeypatch.setattr(marketing_analytics, "campaign_budget_roas", empty_list)
    monkeypatch.setattr(marketing_analytics, "daily_orders", empty_list)
    monkeypatch.setattr(marketing_analytics, "dashboard_summary", dashboard)


#: Every route in the marketing module that takes a merchant-supplied ``days``.
#: Three of the four published no bound at all.
DAYS_ROUTES = (
    "/analytics/summary",
    "/analytics/daily-orders",
    "/analytics/dashboard",
    "/analytics/overview",
)


async def test_the_days_window_is_bounded_on_every_route_that_takes_one(
    monkeypatch,  # noqa: ANN001
) -> None:
    """P7's "unbounded ``days``", still live on all three marketing routes.

    ``days=-1`` is not a past window: it flips the interval and selects the
    future. ``days=100000`` is an unbounded aggregate scan behind a screen that
    polls every 20 seconds. ``/analytics/overview`` and ``/marketing/attribution``
    already refused both; these three answered 200.
    """
    _stub_marketing_readers(monkeypatch)
    for path in DAYS_ROUTES:
        for days in ("0", "-5", "366", "100000", "abc"):
            response = await _get(FakeSession(), f"/api/v1{path}?days={days}")
            assert response.status_code == 422, f"{path}?days={days} was accepted"


async def test_a_sane_days_window_still_answers(monkeypatch) -> None:  # noqa: ANN001
    """The clamp is a bound, not a ban — the frontend's own 14/30 must pass."""
    _stub_marketing_readers(monkeypatch)
    _stub_analytics_readers(monkeypatch)
    for path, days in (
        ("/analytics/summary", "30"),
        ("/analytics/daily-orders", "7"),
        ("/analytics/dashboard", "14"),
        ("/analytics/overview", "1"),
        ("/analytics/overview", "365"),
    ):
        response = await _get(FakeSession(), f"/api/v1{path}?days={days}")
        assert response.status_code == 200, f"{path}?days={days} -> {response.status_code}"


async def test_the_replenishment_threshold_is_bounded(monkeypatch) -> None:  # noqa: ANN001
    """``low_stock_threshold`` is bound into SQL as ``available <= :threshold``.

    A negative was refused already; the missing half is the ceiling. A million is
    not a stock band, it is a way to turn a dashboard card into a scan of every
    balance the tenant holds — and the same parameter is published on two routes,
    so one number has to hold on both.
    """
    _stub_analytics_readers(monkeypatch)
    for path in ("/analytics/inventory/stock-health", "/analytics/overview"):
        for value in ("-1", "1000000"):
            response = await _get(
                FakeSession(), f"/api/v1{path}?low_stock_threshold={value}&days=30"
            )
            assert response.status_code == 422, f"{path}?low_stock_threshold={value} accepted"
        response = await _get(FakeSession(), f"/api/v1{path}?low_stock_threshold=5&days=30")
        assert response.status_code == 200, response.text


async def test_a_paged_list_orders_by_its_cursor_key() -> None:
    """P7's "two sort keys between page 1 and page N", the journey-runs half.

    The route issued ``SELECT ... LIMIT n`` with no ``ORDER BY`` at all. Postgres
    returns rows in any order it likes, so page 2 of an unordered list is not
    page 2 of the same query — and an envelope that promises a next page owes the
    order it pages along.
    """
    rows = [
        _Row(
            id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            status="running",
            current_step=0,
            started_at=datetime(2026, 9, 1, tzinfo=UTC),
            completed_at=None,
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    ]
    session = FakeSession(rows)
    response = await _get(session, f"/api/v1/journeys/{JOURNEY}/runs")
    assert response.status_code == 200, response.text
    sql = " ".join(session.statements)
    assert "ORDER BY" in sql, f"the list has no sort key, so page N is undefined: {sql}"
    assert "created_at DESC" in sql and "id DESC" in sql, (
        f"the sort is not the (created_at, id) pair a cursor encodes from: {sql}"
    )
    assert set(response.json()) == {"items", "next_cursor"}


async def test_the_conversions_list_pages_by_a_cursor_like_its_sibling() -> None:
    """``offset`` on a table where rows arrive out of order skips and repeats.

    The campaigns list already pages by keyset; its conversions sub-list paged by
    ``offset`` and reported the page length under a ``count`` key. Both now answer
    the same envelope, so one reader walks both.
    """
    asked: list[dict] = []
    row = _Row(
        id=CONVERSION,
        order_id=None,
        customer_id=None,
        type="purchase",
        value=Decimal("300.00"),
        currency="EGP",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    async def fake(_session, _tenant, _campaign, **kwargs):  # noqa: ANN001
        asked.append(kwargs)
        return [(row, ["first_touch"])]

    original = MarketingService.list_campaign_conversions
    MarketingService.list_campaign_conversions = staticmethod(fake)  # type: ignore[method-assign]
    try:
        response = await _get(FakeSession(), f"/api/v1/marketing/campaigns/{CAMPAIGN}/conversions")
    finally:
        MarketingService.list_campaign_conversions = original  # type: ignore[method-assign]

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "next_cursor"}, body
    assert body["items"][0]["value"] == "300.00", "an amount left as a number"
    assert asked and "offset" not in asked[0], f"the route is still offset-paging: {asked}"
    assert asked[0]["limit"] == 51, (
        "a keyset page fetches limit+1 so it can say whether a next cursor exists"
    )


# ==========================================================================
# 5. Naive input, re-checked across the two modules rather than assumed
# ==========================================================================


def test_a_naive_occurred_at_is_refused_on_the_write_side() -> None:
    """W5-T2's rule, applied to the one date this pair still let through.

    ``POST /marketing/conversions`` took ``occurred_at`` as a bare ``datetime``
    and bound it into ``conversions.occurred_at``, a ``timestamptz`` column —
    the identical defect the analytics window fix removed on the read side, on
    the side where the value is WRITTEN and therefore permanent. That timestamp
    is what every ROAS and attribution figure later filters on.
    """
    model = marketing_router.ConversionRequest
    try:
        model(occurred_at="2026-09-01T00:00:00")
    except PydanticValidationError as exc:
        assert "offset" in str(exc).lower(), str(exc)
    else:
        raise AssertionError("a wall clock was accepted as a conversion instant")

    accepted = model(occurred_at="2026-09-01T00:00:00+03:00")
    assert accepted.occurred_at is not None and accepted.occurred_at.tzinfo is not None
    assert model().occurred_at is None, "omitting the instant must stay legal"


async def test_a_naive_occurred_at_is_refused_over_http_without_touching_the_database() -> None:
    """The refusal must precede the INSERT, not correct it afterwards."""
    session = FakeSession(raise_on_query=True)
    response = await _post(
        session,
        "/api/v1/marketing/conversions",
        {"type": "purchase", "value": "250.00", "occurred_at": "2026-09-01T00:00:00"},
        permissions={"marketing:write"},
    )
    assert response.status_code == 422, response.text
    assert session.statements == [], "a refused conversion still reached the database"
    assert "offset" in _error_text(response).lower(), _error_text(response)


async def test_an_oversized_or_reversed_window_is_refused_before_any_query_binds() -> None:
    """``days`` was capped at 365 on ``/overview``; ``since`` was not capped at all.

    One cap, two doors: a caller who passed ``since=2000-01-01T00:00:00Z`` got an
    unbounded payments-and-refunds aggregate behind a 20-second poll, and the same
    route's own ``days`` ceiling made the request legal only by spelling it the
    other way round. A reversed or empty window selected nothing and answered 200;
    ``[since, until)`` is an interval, and an inverted one is a mistake.
    """
    for path in (
        "/analytics/revenue/summary",
        "/analytics/daily-series",
        "/analytics/overview",
        "/analytics/metrics/revenue",
    ):
        for query in (
            "since=2000-01-01T00:00:00Z&until=2026-09-01T00:00:00Z",
            "since=2026-09-02T00:00:00Z&until=2026-09-01T00:00:00Z",
            "since=2026-09-01T00:00:00Z&until=2026-09-01T00:00:00Z",
        ):
            session = FakeSession(raise_on_query=True)
            response = await _get(session, f"/api/v1{path}?{query}")
            assert response.status_code == 422, f"{path}?{query} -> {response.status_code}"
            assert session.statements == [], f"{path}?{query} reached the database"


async def test_a_legal_window_still_binds_and_answers(monkeypatch) -> None:  # noqa: ANN001
    """The cap must not be a wall: two weeks is a report, 26 years is a scan."""
    _stub_analytics_readers(monkeypatch)
    response = await _get(
        FakeSession(),
        "/api/v1/analytics/revenue/summary?since=2026-03-01T00:00:00Z&until=2026-03-15T00:00:00Z",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gross_revenue"] == "100.00", body


# ==========================================================================
# 6. The payloads survive their own schemas (a dropped key is a silent break)
# ==========================================================================

_SUMMARY: dict[str, Any] = {
    "currency": "EGP",
    "timezone": "Africa/Cairo",
    "timezone_source": "tenant",
    "since": "2026-08-31T21:00:00+00:00",
    "until": "2026-09-01T09:00:00+00:00",
    "gross_revenue": Decimal("100.00"),
    "refunded_amount": Decimal("40.00"),
    "net_revenue": Decimal("60.00"),
    "refund_excess": Decimal("0.00"),
    "orders_count": 3,
    "gross_aov": Decimal("33.33"),
    "net_aov": Decimal("20.00"),
}


def _stub_analytics_readers(monkeypatch) -> None:  # noqa: ANN001
    service = analytics_router.analytics_service

    async def summary(session, tenant_id, **kw):  # noqa: ANN001, ARG001
        return dict(_SUMMARY)

    async def series(session, tenant_id, **kw):  # noqa: ANN001, ARG001
        return [
            {
                "day": "2026-09-01",
                "gross_revenue": Decimal("70.00"),
                "refunded_amount": Decimal("20.00"),
                "net_revenue": Decimal("50.00"),
                "refund_excess": Decimal("0.00"),
                "orders_count": 2,
            }
        ]

    async def stock(session, tenant_id, *, low_stock_threshold=2):  # noqa: ANN001, ARG001
        return {
            "low_stock_threshold": low_stock_threshold,
            "low_stock_count": 1,
            "out_of_stock_count": 0,
            "healthy_count": 42,
        }

    async def metric(session, tenant_id, **kw):  # noqa: ANN001, ARG001
        return Decimal("150.00")

    async def zone(session, tenant_id, caller_timezone=None):  # noqa: ANN001, ARG001
        return "Africa/Cairo"

    async def currency(session, tenant_id):  # noqa: ANN001, ARG001
        return "EGP"

    monkeypatch.setattr(service, "revenue_summary", summary)
    monkeypatch.setattr(service, "daily_revenue_series", series)
    monkeypatch.setattr(service, "stock_health", stock)
    monkeypatch.setattr(service, "compute_metric", metric)
    monkeypatch.setattr(service, "resolve_report_timezone", zone)
    monkeypatch.setattr(analytics_router, "resolve_tenant_currency", currency)


async def test_the_overview_payload_survives_its_own_schema(monkeypatch) -> None:  # noqa: ANN001
    """A response_model that silently DROPS a key is worse than no response_model.

    FastAPI filters the reply through the declared model, so an undeclared key
    vanishes on the wire while every in-process test keeps seeing it. The
    analytics screen reads ``timezone_source``, ``stock`` and ``daily_series`` off
    this one object, so the published property list is asserted here.
    """
    _stub_analytics_readers(monkeypatch)
    response = await _get(
        FakeSession(),
        "/api/v1/analytics/overview?since=2026-03-01T00:00:00Z&until=2026-03-15T00:00:00Z",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert {
        "currency", "timezone", "timezone_source", "since", "until", "gross_revenue",
        "refunded_amount", "net_revenue", "refund_excess", "orders_count", "gross_aov",
        "net_aov", "daily_series", "stock",
    } <= set(body), sorted(body)
    assert body["gross_revenue"] == "100.00", body
    assert body["daily_series"][0]["gross_revenue"] == "70.00", body
    assert body["daily_series"][0]["orders_count"] == 2, "a count must not become a string"
    assert body["stock"]["low_stock_count"] == 1


async def test_the_daily_series_route_ships_its_items_under_the_envelope(
    monkeypatch,
) -> None:  # noqa: ANN001
    """The metadata keys ride beside ``{items, next_cursor}``, not instead of them."""
    _stub_analytics_readers(monkeypatch)
    response = await _get(
        FakeSession(),
        "/api/v1/analytics/daily-series?since=2026-03-01T00:00:00Z&until=2026-03-15T00:00:00Z",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert {"items", "next_cursor"} <= set(body), sorted(body)
    assert body["next_cursor"] is None, "a bounded series has no next page"
    assert body["items"][0]["gross_revenue"] == "70.00", body


async def test_the_metric_value_keeps_amount_count_and_ratio_types_apart(
    monkeypatch,
) -> None:  # noqa: ANN001
    """``/metrics/{name}`` answers money, counts and ratios from ONE model."""
    _stub_analytics_readers(monkeypatch)
    service = analytics_router.analytics_service

    async def ask(value: Any) -> dict:
        async def handler(session, tenant_id, **kw):  # noqa: ANN001, ARG001
            return value

        monkeypatch.setattr(service, "compute_metric", handler)
        response = await _get(
            FakeSession(),
            "/api/v1/analytics/metrics/revenue?since=2026-03-01T00:00:00Z&until=2026-03-15T00:00:00Z",
        )
        assert response.status_code == 200, response.text
        return response.json()

    assert (await ask(Decimal("150.00")))["value"] == "150.00"
    assert (await ask(7))["value"] == 7
    assert (await ask(1.5))["value"] == 1.5
    assert (await ask(None))["value"] is None


async def test_the_retention_routes_answer_their_declared_shapes(monkeypatch) -> None:  # noqa: ANN001
    """§55-57's door is typed too — including the keys a store publishes optionally.

    ``policy_position`` builds a data-driven superset per store (``keep_predicate``
    and ``media`` exist for some stores only), so that item model has to ALLOW
    extras while still naming what is always there. A strict model would DELETE
    the merchant's evidence that a store keeps rows on purpose.
    """
    gate = retention.DropGate(
        tenant_count=2,
        missing_policies=1,
        max_days=390,
        may_drop=False,
        reason=retention.BLOCKED_NO_CHOSEN_POLICY,
    )

    async def read_gate(session):  # noqa: ANN001
        return gate

    async def position(session, tenant_id):  # noqa: ANN001
        return [
            {
                "data_class": "ai_usage",
                "table": "ai_usage",
                "purge_paths": ["partition"],
                "chosen": False,
                "status": None,
                "retention_days": None,
                "last_run_at": None,
                "offered_default_days": 390,
                "row_gate_reason": None,
                "legal_floor_months": 13,
                "shared_gate_reason": retention.BLOCKED_NO_CHOSEN_POLICY,
                "shared_gate_blocks_me": True,
            },
            {
                "data_class": "messages",
                "table": "messages",
                "purge_paths": ["row"],
                "chosen": True,
                "status": "active",
                "retention_days": 30,
                "last_run_at": None,
                "offered_default_days": None,
                "row_gate_reason": None,
                "legal_floor_months": None,
                "shared_gate_reason": None,
                "shared_gate_blocks_me": False,
                "keep_predicate": "direction = 'inbound'",
                "keep_reason": "the customer's own copy is kept",
                "media": {"key_column": None, "cascades_from_child": None},
            },
        ]

    async def choose(session, tenant_id, data_class, *, retention_days, enabled=True):  # noqa: ANN001, ARG001
        return {
            "data_class": data_class,
            "retention_days": retention_days,
            "status": "active" if enabled else "paused",
            "chosen": enabled,
        }

    async def nothing(*args, **kwargs):  # noqa: ANN001, ARG001
        return None

    async def no_policy(session, tenant_id, data_class):  # noqa: ANN001, ARG001
        return None

    monkeypatch.setattr(retention, "read_drop_gate", read_gate)
    monkeypatch.setattr(retention, "policy_position", position)
    monkeypatch.setattr(retention, "choose_policy", choose)
    monkeypatch.setattr(retention, "read_policy", no_policy)
    monkeypatch.setattr(analytics_router, "write_audit_row", nothing)

    read = await _get(
        FakeSession(), "/api/v1/analytics/retention", permissions={"analytics:read"}
    )
    assert read.status_code == 200, read.text
    written = await _put(
        FakeSession(),
        "/api/v1/analytics/retention/policies/ai_usage",
        {"retention_days": 400, "status": "active"},
        permissions={"analytics:write"},
    )
    assert written.status_code == 200, written.text

    read_body, write_body = read.json(), written.json()
    assert {"policies", "gate", "blocked_reason", "unblock_requires"} == set(read_body)
    assert {"policy", "gate", "blocked_reason", "unblock_requires"} == set(write_body)
    assert read_body["gate"] == {
        "tenant_count": 2,
        "missing_policies": 1,
        "max_days": 390,
        "may_drop": False,
        "reason": retention.BLOCKED_NO_CHOSEN_POLICY,
    }
    by_class = {row["data_class"]: row for row in read_body["policies"]}
    assert by_class["messages"]["keep_predicate"] == "direction = 'inbound'", (
        "the model dropped a key the store only sometimes publishes"
    )
    assert by_class["ai_usage"]["retention_days"] is None, (
        "an unanswered question must not serialise as a zero-day horizon"
    )
    assert write_body["unblock_requires"], write_body


async def test_the_metric_definitions_list_is_typed_and_closed() -> None:
    """``/metrics/definitions`` publishes §167's whole registry, field by field.

    The list is finite and never paged, so it shares the envelope with a
    ``next_cursor`` of ``null`` rather than inventing a second shape.
    """
    response = await _get(FakeSession(), "/api/v1/analytics/metrics/definitions")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "next_cursor"}
    assert body["next_cursor"] is None
    assert body["items"], "the registry published an empty list, which is not the truth"
    assert {
        "name", "definition", "source", "filters",
        "timezone_rule", "currency_rule", "refund_treatment", "version",
    } == set(body["items"][0])


# ==========================================================================
# 7. The marketing read paths still answer, with their money strings intact
# ==========================================================================


async def test_the_composed_summary_route_ships_amounts_as_strings(monkeypatch) -> None:  # noqa: ANN001
    """``test_roas.py`` pins this end to end on a real database; this is the same
    claim with the database replaced, so it is watched locally, not only in CI.
    """

    async def sources(session, tenant_id, *a, **kw):  # noqa: ANN001, ARG001
        return [{"source": "facebook", "revenue": "150.00", "conversions": 3}]

    async def by_campaign(session, tenant_id, *a, **kw):  # noqa: ANN001, ARG001
        return [
            {
                "campaign_id": CAMPAIGN,
                "campaign_name": "Ramadan Sale",
                "revenue": "150.00",
                "conversions": 3,
            }
        ]

    async def roas(session, tenant_id, *a, **kw):  # noqa: ANN001, ARG001
        return [
            {
                "campaign_id": CAMPAIGN,
                "name": "Ramadan Sale",
                "revenue": "150.00",
                "planned_budget": "100.00",
                "actual_spend": None,
                "basis": "planned_budget",
                "budget_roas": 1.5,
                "spend_roas": None,
            }
        ]

    _stub_marketing_readers(monkeypatch)

    # The shared block is all-zero (it exists to prove the *shape*), which would
    # make this test pass on a route that dropped the amounts entirely — `"0.00"`
    # is a string either way. Non-zero amounts are the assertion's teeth: an
    # amount that crosses as a float, or is recomputed by the composer instead of
    # shipped, stops matching here.
    async def orders_with_amounts(session, tenant_id, **kw):  # noqa: ANN001, ARG001
        return {
            **_ORDERS_BLOCK,
            "orders_count": 4,
            "gross_revenue": "100.00",
            "refunded_amount": "5.00",
            "net_revenue": "95.00",
            "gross_aov": "25.00",
            "net_aov": "23.75",
        }

    monkeypatch.setattr(marketing_analytics, "orders_summary", orders_with_amounts)
    monkeypatch.setattr(marketing_analytics, "revenue_by_source", sources)
    monkeypatch.setattr(marketing_analytics, "revenue_by_campaign", by_campaign)
    monkeypatch.setattr(marketing_analytics, "campaign_budget_roas", roas)

    response = await _get(FakeSession(), "/api/v1/analytics/summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "orders_summary",
        "revenue_by_source",
        "revenue_by_campaign",
        "campaign_budget_roas",
    }, sorted(body)
    assert body["orders_summary"]["gross_revenue"] == "100.00"
    assert isinstance(body["orders_summary"]["orders_count"], int)
    assert body["revenue_by_source"][0]["revenue"] == "150.00"
    assert body["revenue_by_source"][0]["conversions"] == 3
    assert body["campaign_budget_roas"][0]["budget_roas"] == 1.5
    assert body["campaign_budget_roas"][0]["actual_spend"] is None
    assert body["campaign_budget_roas"][0]["campaign_id"] == str(CAMPAIGN)


async def test_an_unbudgeted_campaign_ships_no_string_zero(monkeypatch) -> None:  # noqa: ANN001
    """``None`` stays ``None`` — "no plan" and "a plan of 0.00" are different answers.

    The same route pages: with ``limit + 1`` rows present it must hand back the
    keyset cursor its own docstring promises, or the second page is unreachable.
    """
    now = datetime(2026, 9, 1, tzinfo=UTC)

    async def fake(_session, _tenant, **_kwargs):  # noqa: ANN001
        return [
            _Row(
                id=CAMPAIGN,
                name="Unbudgeted",
                provider="manual",
                external_id=None,
                objective=None,
                status="draft",
                budget=None,
                created_at=now,
            ),
            _Row(
                id=uuid.uuid4(),
                name="Second",
                provider="manual",
                external_id=None,
                objective=None,
                status="draft",
                budget=Decimal("500.00"),
                created_at=now,
            ),
        ]

    monkeypatch.setattr(MarketingService, "list_campaigns", staticmethod(fake))
    # Two claims, two requests — the route's paging rule makes them exclusive.
    # `limit=2` surfaces both rows so the money rule is visible on each; a short
    # page (2 of 2) owes NO cursor, which is as much part of the contract as the
    # key that a full page must hand back.
    response = await _get(FakeSession(), "/api/v1/marketing/campaigns?limit=2")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "next_cursor"}
    assert body["items"][0]["budget"] is None
    assert body["items"][1]["budget"] == "500.00"
    assert body["next_cursor"] is None, "a page that read every row must not promise more"

    full = await _get(FakeSession(), "/api/v1/marketing/campaigns?limit=1")
    assert full.status_code == 200, full.text
    assert len(full.json()["items"]) == 1, "limit is a ceiling, not a suggestion"
    assert full.json()["next_cursor"], "a full page owes the cursor that continues it"


async def test_campaign_write_routes_declare_their_replies(monkeypatch) -> None:  # noqa: ANN001
    """The 201s are contract too: a POST whose reply is untyped is undocumented.

    ``POST /marketing/conversions`` is where the money rule re-enters on the
    write side: the request accepts an amount, the reply must leave it as a
    string, and the instant the caller sent comes back as the instant stored.
    """

    async def fake_conversion(_session, _tenant, **_kwargs):  # noqa: ANN001
        return _Row(
            id=CONVERSION,
            order_id=None,
            customer_id=None,
            type="purchase",
            value=Decimal("250.00"),
            currency="EGP",
            occurred_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        )

    async def fake_entitlement(*_args, **_kwargs):  # noqa: ANN001
        return None

    monkeypatch.setattr(MarketingService, "record_conversion", staticmethod(fake_conversion))
    monkeypatch.setattr(
        marketing_router.EntitlementService, "ensure", staticmethod(fake_entitlement)
    )

    response = await _post(
        FakeSession(),
        "/api/v1/marketing/conversions",
        {"type": "purchase", "value": "250.00", "occurred_at": "2026-09-01T12:00:00+00:00"},
        permissions={"marketing:write"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["value"] == "250.00", body
    assert body["currency"] == "EGP"
    assert body["occurred_at"].startswith("2026-09-01T12:00:00")


async def test_the_attribution_route_refuses_to_answer_a_bad_question() -> None:
    """``{"error": "..."}`` with status 200 was a 200-shaped 422.

    A caller that supplied neither id got an OK and a prose error, which no
    client checks and no schema can describe. The refusal the rest of the API
    uses is a 422 naming the parameters — and it is the only reason this route's
    response model can be a union of two real shapes instead of one object with
    three optional faces.
    """
    response = await _get(FakeSession(), "/api/v1/marketing/attribution")
    assert response.status_code == 422, f"the route still answers 200 with {response.text}"
    assert "campaign_id" in _error_text(response)
    assert "conversion_id" in _error_text(response)


def test_both_attribution_shapes_are_declared_models() -> None:
    """A response model for a union route must name BOTH arms.

    The conversion view lists touchpoints, the campaign view reports alternative
    model readings. They are different payloads on one path, and the published
    schema has to show both or it is a lie about one of them.
    """
    models = _models_of(_route("/marketing/attribution").response_model)
    assert len(models) >= 2, f"only {models} attribution shape(s) are published"
    names = {model.__name__ for model in models}
    assert any("Conversion" in name for name in names), names
    assert any("Campaign" in name for name in names), names
