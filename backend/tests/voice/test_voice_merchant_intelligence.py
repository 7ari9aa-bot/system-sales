"""The Merchant Intelligence Gateway: four read paths, one honest answer shape."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from app.core.errors import PermissionDeniedError
from app.platform.voice.application.merchant_intelligence import (
    MerchantIntelligenceGateway,
    Reading,
)
from app.platform.voice.domain.contracts import Completeness, Period
from app.platform.voice.domain.metrics import METRIC_REGISTRY, UnknownMetric
from app.platform.voice.security.capabilities import (
    AuthenticationLevel,
    ChannelType,
    PrincipalType,
    resolve_capability,
)

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER = uuid.UUID("22222222-2222-2222-2222-222222222222")
PERIOD = Period(dt.date(2026, 11, 1), dt.date(2026, 11, 27))


class FakeAnalytics:
    def __init__(self, readings: dict[str, Reading] | None = None) -> None:
        self.readings = readings or {}
        self.calls: list[str] = []

    async def read_metric(self, *, definition, tenant_id, workspace_id, period, currency):
        self.calls.append(definition.code)
        return self.readings.get(definition.code, Reading(value=Decimal("1000"), currency=currency))


class FakeOperational:
    def __init__(self) -> None:
        self.calls = 0

    async def read_record(self, *, subject, reference, tenant_id, workspace_id):
        self.calls += 1
        return Reading(value=Decimal("1"), extra={"reference": reference})


class FakeKnowledge:
    async def search(self, *, question, tenant_id, limit):
        return Reading(value=Decimal("1"), extra={"answer": "policy text"})


class FakeActivity:
    async def timeline(self, *, subject, reference, tenant_id, period):
        return Reading(value=Decimal("3"))


def merchant(scopes: frozenset[str] | None = None):
    return resolve_capability(
        principal_type=PrincipalType.MERCHANT_USER,
        principal_id=USER,
        tenant_id=TENANT,
        workspace_id=None,
        held_scopes=scopes
        or frozenset(
            {"analytics:read", "orders:read", "inventory:read", "customers:read", "expenses:read"}
        ),
        channel=ChannelType.WEB_VOICE,
    )


def customer():
    return resolve_capability(
        principal_type=PrincipalType.CUSTOMER,
        principal_id=uuid.uuid4(),
        tenant_id=TENANT,
        workspace_id=None,
        held_scopes=frozenset({"catalog:read"}),
        channel=ChannelType.WHATSAPP_VOICE,
        authentication_level=AuthenticationLevel.VERIFIED,
    )


def gateway(analytics=None) -> MerchantIntelligenceGateway:
    return MerchantIntelligenceGateway(
        analytics=analytics or FakeAnalytics(),
        operational=FakeOperational(),
        knowledge=FakeKnowledge(),
        activity=FakeActivity(),
        clock=lambda: dt.datetime(2026, 11, 27, 9, 0, tzinfo=dt.UTC),
    )


class TestMerchantReads:
    async def test_net_sales_carries_currency_period_as_of_and_its_definition(self) -> None:
        fact = await gateway().metric(merchant(), "net_sales", period=PERIOD)
        wire = fact.as_dict()
        assert wire["status"] == "success"
        assert wire["data"]["currency"] == "EGP"
        assert wire["data"]["period"] == {"from": "2026-11-01", "to": "2026-11-27"}
        assert wire["context"]["timezone"] == "Africa/Cairo"
        assert wire["context"]["as_of"].startswith("2026-11-27T09:00")
        versions = [item.get("metric_definition_version") for item in wire["evidence"]]
        assert "net_sales@1.0" in versions

    async def test_a_count_metric_is_not_given_a_currency(self) -> None:
        fact = await gateway().metric(merchant(), "order_count", period=PERIOD)
        assert fact.currency is None
        assert fact.value is not None

    async def test_operational_and_activity_paths_answer_with_the_reference_they_read(self) -> None:
        fact = await gateway().operational(merchant(), subject="orders", reference="SO-4412")
        assert fact.scope == "SO-4412"
        assert fact.as_dict()["data"]["reference"] == "SO-4412"

        history = await gateway().activity(
            merchant(), subject="orders", reference="SO-4412", period=PERIOD
        )
        assert history.period == PERIOD

    async def test_knowledge_answers_from_the_shops_own_documents(self) -> None:
        fact = await gateway().knowledge(merchant(), question="سياسة الاستبدال؟")
        assert fact.as_dict()["data"]["answer"] == "policy text"


class TestRefusals:
    async def test_a_customer_session_cannot_read_merchant_analytics(self) -> None:
        with pytest.raises(PermissionDeniedError):
            await gateway().metric(customer(), "net_sales", period=PERIOD)
        with pytest.raises(PermissionDeniedError):
            await gateway().summary(customer(), period=PERIOD)

    async def test_a_scope_the_user_does_not_hold_is_refused(self) -> None:
        only_orders = merchant(frozenset({"orders:read"}))
        with pytest.raises(PermissionDeniedError):
            await gateway().metric(only_orders, "net_sales", period=PERIOD)

    async def test_an_undefined_metric_is_never_approximated(self) -> None:
        with pytest.raises(UnknownMetric):
            await gateway().metric(merchant(), "profit_guess", period=PERIOD)

    def test_every_registry_metric_names_the_scope_it_spends(self) -> None:
        for code, definition in METRIC_REGISTRY.items():
            assert definition.scope, code
            assert definition.formula, code
            assert definition.needs, code
            assert definition.version, code


class TestHonestNumbers:
    async def test_an_unreadable_source_is_unavailable_not_zero(self) -> None:
        analytics = FakeAnalytics({"net_sales": Reading.unavailable("returns")})
        fact = await gateway(analytics).metric(merchant(), "net_sales", period=PERIOD)
        wire = fact.as_dict()
        assert wire["status"] == "unavailable"
        assert wire["data"]["value"] is None
        assert wire["quality"]["completeness"] == "partial"
        assert any("returns" in note for note in wire["quality"]["limitations"])

    async def test_a_reader_that_answers_with_missing_inputs_is_discarded(self) -> None:
        # The reader produced 1000 but admitted cogs was missing: net_profit is not that number.
        analytics = FakeAnalytics(
            {
                "net_profit": Reading(
                    value=Decimal("1000"),
                    currency="EGP",
                    completeness=Completeness.PARTIAL,
                    missing_inputs=("expenses",),
                )
            }
        )
        fact = await gateway(analytics).metric(merchant(), "net_profit", period=PERIOD)
        assert fact.value is None
        assert fact.completeness is Completeness.PARTIAL
        assert any("expenses" in note for note in fact.limitations)


class TestProgressiveLoading:
    async def test_summary_reads_headline_metrics_only_and_no_records(self) -> None:
        analytics = FakeAnalytics()
        gw = gateway(analytics)
        facts = await gw.summary(merchant(), period=PERIOD)
        assert [fact.metric for fact in facts] == ["net_sales", "order_count", "aov"]
        assert analytics.calls == ["net_sales", "order_count", "aov"]
        assert gw._operational.calls == 0  # type: ignore[attr-defined]

    async def test_summary_skips_a_metric_whose_scope_is_not_held(self) -> None:
        facts = await gateway().summary(merchant(frozenset({"orders:read"})), period=PERIOD)
        assert [fact.metric for fact in facts] == ["order_count"]
