"""Phase 0 contracts: the rules a voice session cannot break, pinned as tests.

These are the checks the architecture proposal calls invariants 1-9 and 12. They are pure: no
database, no provider, no audio. That is the point — the security shape of the voice layer must be
provable before a single byte of audio is streamed, otherwise the first real call is the first
test.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from app.core.errors import PermissionDeniedError
from app.modules.voice.domain.contracts import (
    AudioPath,
    Completeness,
    ContractViolation,
    Evidence,
    Fact,
    Period,
    ProviderCapabilities,
    add_amounts,
)
from app.modules.voice.domain.personas import (
    Effect,
    PersonaResolutionError,
    PersonaType,
    PrincipalType,
    persona_for,
)
from app.modules.voice.domain.states import (
    IllegalTransition,
    TurnState,
    VoiceSessionState,
    agent_may_speak,
    next_session_state,
    next_turn_state,
    session_is_terminal,
)
from app.modules.voice.security.capabilities import (
    AuthenticationLevel,
    ChannelType,
    SessionCapability,
    ToolGateway,
    assert_same_tenant,
    resolve_capability,
)
from app.modules.voice.security.data_egress import (
    DataClass,
    EgressDecision,
    EgressDenied,
    ProviderPolicy,
    decide,
    require_egress,
)

NOW = dt.datetime(2026, 11, 27, 9, 0, tzinfo=dt.UTC)
TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()
USER = uuid.uuid4()


def _merchant_capability(scopes: frozenset[str] | None = None) -> SessionCapability:
    return resolve_capability(
        principal_type=PrincipalType.MERCHANT_USER,
        principal_id=USER,
        tenant_id=TENANT,
        workspace_id=None,
        held_scopes=scopes
        if scopes is not None
        else frozenset({"orders:read", "inventory:read", "analytics:read"}),
        channel=ChannelType.WEB_VOICE,
        issued_at=NOW,
    )


def _customer_capability(level: AuthenticationLevel = AuthenticationLevel.ANONYMOUS):
    return resolve_capability(
        principal_type=PrincipalType.CUSTOMER,
        principal_id=uuid.uuid4() if level >= AuthenticationLevel.IDENTIFIED else None,
        tenant_id=TENANT,
        workspace_id=None,
        held_scopes=frozenset(),
        channel=ChannelType.WEB_VOICE,
        authentication_level=level,
        issued_at=NOW,
    )


class TestPersonas:
    def test_merchant_and_customer_are_different_principals(self) -> None:
        merchant = persona_for(PrincipalType.MERCHANT_USER)
        customer = persona_for(PrincipalType.CUSTOMER)
        assert merchant.type is not customer.type
        assert merchant.data_scope != customer.data_scope

    def test_merchant_persona_has_no_write_tools(self) -> None:
        merchant = persona_for(PrincipalType.MERCHANT_USER)
        assert merchant.write_tools is False
        assert merchant.allowed_effects == frozenset({Effect.READ})

    def test_customer_persona_cannot_cross_tenants_or_customers(self) -> None:
        customer = persona_for(PrincipalType.CUSTOMER)
        assert customer.cross_tenant_access is False
        assert customer.cross_customer_access is False

    def test_anonymous_caller_is_a_customer_not_a_merchant(self) -> None:
        assert persona_for(PrincipalType.ANONYMOUS).type is PersonaType.CUSTOMER_AGENT

    def test_customer_persona_holds_no_merchant_analytics_scope(self) -> None:
        customer = persona_for(PrincipalType.CUSTOMER)
        for scope in ("analytics:read", "expenses:read", "billing:read", "customers:read"):
            assert scope not in customer.read_scopes

    def test_unknown_principal_is_refused(self) -> None:
        with pytest.raises(PersonaResolutionError):
            persona_for("platform_admin")  # type: ignore[arg-type]


class TestCapabilityResolution:
    def test_merchant_scopes_are_the_intersection_with_what_the_user_holds(self) -> None:
        # The persona allows all twelve shop domains; the session carries only the ones this
        # user already holds in the dashboard, so a cashier without expenses cannot hear them.
        both = _merchant_capability(frozenset({"orders:read", "expenses:read"}))
        assert both.scopes == frozenset({"orders:read", "expenses:read"})

        cashier = _merchant_capability(frozenset({"orders:read"}))
        assert cashier.scopes == frozenset({"orders:read"})
        assert "expenses:read" not in cashier.scopes

    def test_merchant_with_no_readable_scope_gets_no_session(self) -> None:
        with pytest.raises(PermissionDeniedError):
            _merchant_capability(frozenset({"settings:write"}))

    def test_customer_capability_carries_public_scopes_but_not_own_orders(self) -> None:
        capability = _customer_capability()
        assert "catalog.published:read" in capability.scopes
        assert "customer.own_orders:read" not in capability.scopes

    def test_verified_customer_gains_own_order_scope(self) -> None:
        capability = _customer_capability(AuthenticationLevel.VERIFIED)
        assert "customer.own_orders:read" in capability.scopes

    def test_capability_expires(self) -> None:
        capability = _merchant_capability()
        assert capability.is_live(NOW + dt.timedelta(minutes=1))
        assert not capability.is_live(NOW + dt.timedelta(hours=2))


class TestToolGateway:
    def setup_method(self) -> None:
        self.gateway = ToolGateway()

    def test_merchant_read_tool_in_scope_is_allowed(self) -> None:
        capability = _merchant_capability()
        tool = self.gateway.authorize(capability, "orders.read", now=NOW)
        assert tool.name == "orders.read"

    def test_merchant_cannot_reach_a_scope_it_does_not_hold(self) -> None:
        capability = _merchant_capability(frozenset({"orders:read"}))
        with pytest.raises(PermissionDeniedError):
            self.gateway.authorize(capability, "expenses.read", now=NOW)

    def test_merchant_is_refused_a_write_tool_even_if_it_asks(self) -> None:
        capability = _merchant_capability()
        with pytest.raises(PermissionDeniedError):
            self.gateway.authorize(capability, "orders.create", now=NOW)

    def test_customer_is_refused_merchant_analytics(self) -> None:
        capability = _customer_capability(AuthenticationLevel.VERIFIED)
        with pytest.raises(PermissionDeniedError):
            self.gateway.authorize(capability, "analytics.read", now=NOW)

    def test_customer_cannot_read_another_customers_orders_without_verification(self) -> None:
        capability = _customer_capability()
        with pytest.raises(PermissionDeniedError):
            self.gateway.authorize(capability, "customer.own_orders", now=NOW)

    def test_unknown_tool_is_refused(self) -> None:
        with pytest.raises(PermissionDeniedError):
            self.gateway.authorize(_merchant_capability(), "sql.query", now=NOW)

    def test_expired_session_is_refused(self) -> None:
        capability = _merchant_capability()
        with pytest.raises(PermissionDeniedError):
            self.gateway.authorize(capability, "orders.read", now=NOW + dt.timedelta(hours=3))

    def test_tool_call_for_another_tenant_is_refused(self) -> None:
        capability = _merchant_capability()
        with pytest.raises(PermissionDeniedError):
            self.gateway.authorize(capability, "orders.read", tenant_id=OTHER_TENANT, now=NOW)

    def test_session_cannot_move_tenant(self) -> None:
        capability = _merchant_capability()
        assert_same_tenant(capability, TENANT)
        with pytest.raises(PermissionDeniedError):
            assert_same_tenant(capability, OTHER_TENANT)

    def test_authorized_tools_never_list_a_write_for_a_merchant(self) -> None:
        names = self.gateway.authorized_tools(_merchant_capability())
        assert "orders.read" in names
        assert "orders.create" not in names
        assert "analytics.read" in names

    def test_authorized_tools_for_a_customer_exclude_merchant_scopes(self) -> None:
        names = self.gateway.authorized_tools(_customer_capability())
        assert "catalog.public" in names
        assert "expenses.read" not in names
        assert "analytics.read" not in names


class TestSessionStates:
    def test_happy_path(self) -> None:
        state = VoiceSessionState.CREATED
        for target in (
            VoiceSessionState.AUTHENTICATING,
            VoiceSessionState.CONFIGURING,
            VoiceSessionState.CONNECTING,
            VoiceSessionState.ACTIVE,
            VoiceSessionState.CLOSING,
            VoiceSessionState.CLOSED,
        ):
            state = next_session_state(state, target)
        assert session_is_terminal(state)

    def test_a_closed_session_cannot_be_reopened(self) -> None:
        with pytest.raises(IllegalTransition):
            next_session_state(VoiceSessionState.CLOSED, VoiceSessionState.ACTIVE)

    def test_a_human_handoff_is_a_one_way_door(self) -> None:
        assert next_session_state(VoiceSessionState.ACTIVE, VoiceSessionState.HANDOFF_PENDING)
        assert next_session_state(VoiceSessionState.HANDOFF_PENDING, VoiceSessionState.HUMAN_ACTIVE)
        with pytest.raises(IllegalTransition):
            next_session_state(VoiceSessionState.HUMAN_ACTIVE, VoiceSessionState.ACTIVE)

    def test_agent_does_not_speak_while_a_human_holds_the_call(self) -> None:
        assert agent_may_speak(VoiceSessionState.ACTIVE)
        assert not agent_may_speak(VoiceSessionState.HUMAN_ACTIVE)
        assert not agent_may_speak(VoiceSessionState.CLOSING)
        assert not agent_may_speak(VoiceSessionState.CLOSED)

    def test_interruption_ends_the_turn_not_the_session(self) -> None:
        assert next_turn_state(TurnState.SPEAKING, TurnState.INTERRUPTED)
        assert next_session_state(VoiceSessionState.ACTIVE, VoiceSessionState.INTERRUPTED)

    def test_a_tool_result_after_barge_in_cannot_be_spoken(self) -> None:
        # The user cut in while the tool ran: the result is kept for the record, the turn is over.
        with pytest.raises(IllegalTransition):
            next_turn_state(TurnState.INTERRUPTED, TurnState.SPEAKING)

    def test_turn_cannot_jump_from_listening_to_speaking(self) -> None:
        with pytest.raises(IllegalTransition):
            next_turn_state(TurnState.LISTENING, TurnState.SPEAKING)


class TestFactContract:
    def _fact(self, **overrides: object) -> Fact:
        base = dict(
            metric="net_sales",
            value=Decimal("125000"),
            currency="EGP",
            period=Period(dt.date(2026, 11, 1), dt.date(2026, 11, 27)),
            timezone="Africa/Cairo",
            as_of=NOW,
            scope="all_locations",
            evidence=(Evidence("analytics", "1.0"),),
        )
        base.update(overrides)
        return Fact(**base)  # type: ignore[arg-type]

    def test_wire_shape_carries_context_and_evidence(self) -> None:
        payload = self._fact().as_dict()
        assert payload["status"] == "success"
        assert payload["data"]["value"] == "125000"
        assert payload["data"]["currency"] == "EGP"
        assert payload["context"]["timezone"] == "Africa/Cairo"
        assert payload["evidence"][0]["source"] == "analytics"

    def test_a_value_without_currency_is_refused(self) -> None:
        with pytest.raises(ContractViolation):
            self._fact(currency=None)

    def test_a_missing_value_is_unavailable_not_zero(self) -> None:
        fact = self._fact(
            value=None,
            currency=None,
            completeness=Completeness.PARTIAL,
            limitations=("the sales view was not reachable",),
        )
        payload = fact.as_dict()
        assert payload["status"] == "unavailable"
        assert payload["data"]["value"] is None

    def test_a_missing_value_must_say_why(self) -> None:
        with pytest.raises(ContractViolation):
            self._fact(value=None, currency=None, completeness=Completeness.PARTIAL)

    def test_adding_two_currencies_is_refused(self) -> None:
        egp = self._fact()
        usd = self._fact(currency="USD")
        with pytest.raises(ContractViolation):
            add_amounts([egp, usd])

    def test_adding_partial_data_is_refused(self) -> None:
        complete = self._fact()
        partial = self._fact(completeness=Completeness.PARTIAL)
        with pytest.raises(ContractViolation):
            add_amounts([complete, partial])

    def test_adding_comparable_facts_sums_and_keeps_evidence(self) -> None:
        total = add_amounts([self._fact(), self._fact(value=Decimal("5000"))])
        assert total.value == Decimal("130000")
        assert total.currency == "EGP"
        assert len(total.evidence) == 2


class TestProviderCapabilities:
    def test_a_provider_without_barge_in_cannot_serve_a_hybrid_route(self) -> None:
        caps = ProviderCapabilities(
            name="example",
            paths=frozenset({AudioPath.CASCADED}),
            languages=frozenset({"ar-EG", "en"}),
        )
        assert caps.can_serve(AudioPath.CASCADED, "ar-EG")
        assert not caps.can_serve(AudioPath.SPEECH_TO_SPEECH, "ar-EG")
        assert caps.can_serve(AudioPath.CASCADED, "ar-SA")
        assert not caps.can_serve(AudioPath.CASCADED, "fr-FR")


class TestDataEgress:
    def test_unknown_provider_may_not_carry_audio(self) -> None:
        verdict = decide(provider="unlisted", data_class=DataClass.PII)
        assert verdict.decision is EgressDecision.DENY
        assert "no recorded policy" in verdict.reason

    def test_payment_data_never_leaves_even_with_a_policy(self) -> None:
        policies = {
            "good": ProviderPolicy(
                provider="good",
                allowed_classes=frozenset(DataClass),
                regions=frozenset({"eu"}),
                model_allowlist=frozenset({"m"}),
                dpa_signed=True,
            )
        }
        verdict = decide(provider="good", data_class=DataClass.PAYMENT, policies=policies)
        assert verdict.decision is EgressDecision.DENY

    def test_a_class_outside_the_policy_is_refused(self) -> None:
        policies = {
            "good": ProviderPolicy(
                provider="good",
                allowed_classes=frozenset({DataClass.PUBLIC}),
                regions=frozenset({"eu"}),
                model_allowlist=frozenset({"m"}),
                dpa_signed=True,
            )
        }
        assert (
            decide(provider="good", data_class=DataClass.CONFIDENTIAL, policies=policies).decision
            is EgressDecision.DENY
        )

    def test_unsigned_dpa_blocks_the_payload(self) -> None:
        policies = {
            "good": ProviderPolicy(
                provider="good",
                allowed_classes=frozenset({DataClass.PUBLIC, DataClass.PII}),
                regions=frozenset({"eu"}),
                model_allowlist=frozenset({"m"}),
                dpa_signed=False,
            )
        }
        assert (
            decide(provider="good", data_class=DataClass.PII, policies=policies).decision
            is EgressDecision.DENY
        )

    def test_a_complete_policy_allows(self) -> None:
        policies = {
            "good": ProviderPolicy(
                provider="good",
                allowed_classes=frozenset({DataClass.PUBLIC, DataClass.INTERNAL}),
                regions=frozenset({"eu"}),
                model_allowlist=frozenset({"m"}),
                dpa_signed=True,
            )
        }
        assert decide(
            provider="good",
            data_class=DataClass.INTERNAL,
            region="eu",
            model="m",
            policies=policies,
        ).allowed

    def test_require_egress_raises_on_refusal(self) -> None:
        with pytest.raises(EgressDenied):
            require_egress(provider="unlisted", data_class=DataClass.PII)
