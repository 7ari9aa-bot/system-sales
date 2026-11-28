"""Phase 3: proving a customer, and keeping one customer's data out of another's session."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.core.errors import PermissionDeniedError
from app.platform.voice.application.customer_context import (
    CustomerContextBuilder,
    OrderRef,
)
from app.platform.voice.security.capabilities import (
    AuthenticationLevel,
    ChannelType,
    PrincipalType,
    ToolGateway,
    resolve_capability,
)
from app.platform.voice.security.identity_verification import (
    IdentityVerificationEngine,
    InMemoryChallengeStore,
    VerificationExpired,
    VerificationFailed,
    VerificationThrottled,
)

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
CUSTOMER = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER = uuid.UUID("33333333-3333-3333-3333-333333333333")


class Clock:
    def __init__(self, now: dt.datetime) -> None:
        self.now = now

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, delta: dt.timedelta) -> None:
        self.now = self.now + delta


def _engine() -> tuple[IdentityVerificationEngine, Clock]:
    clock = Clock(dt.datetime(2026, 11, 27, 9, 0, tzinfo=dt.UTC))
    engine = IdentityVerificationEngine(InMemoryChallengeStore(), clock=clock, pepper="test-pepper")
    return engine, clock


class TestOtpLifecycle:
    async def test_the_right_code_verifies_once_and_never_again(self) -> None:
        engine, _ = _engine()
        ticket = await engine.start(
            tenant_id=TENANT, destination="+201000000001", customer_id=CUSTOMER
        )
        assert ticket.code_for_delivery.isdigit() and len(ticket.code_for_delivery) == 6

        identity = await engine.verify(
            challenge_id=ticket.challenge_id, code=ticket.code_for_delivery
        )
        assert identity.level is AuthenticationLevel.VERIFIED
        assert identity.customer_id == CUSTOMER
        assert identity.method == "otp"

        with pytest.raises(VerificationExpired):
            await engine.verify(challenge_id=ticket.challenge_id, code=ticket.code_for_delivery)

    async def test_a_wrong_code_counts_down_and_the_last_one_kills_the_challenge(self) -> None:
        engine, _ = _engine()
        ticket = await engine.start(tenant_id=TENANT, destination="+201000000002")
        with pytest.raises(VerificationFailed) as first:
            await engine.verify(challenge_id=ticket.challenge_id, code="000000")
        assert first.value.attempts_left == 2
        with pytest.raises(VerificationFailed):
            await engine.verify(challenge_id=ticket.challenge_id, code="111111")
        with pytest.raises(VerificationThrottled):
            await engine.verify(challenge_id=ticket.challenge_id, code="222222")
        # Even the real code cannot revive a challenge that ran out of attempts.
        with pytest.raises(VerificationExpired):
            await engine.verify(challenge_id=ticket.challenge_id, code=ticket.code_for_delivery)

    async def test_a_code_expires_on_the_clock_not_on_hope(self) -> None:
        engine, clock = _engine()
        ticket = await engine.start(tenant_id=TENANT, destination="+201000000003")
        clock.advance(dt.timedelta(minutes=6))
        with pytest.raises(VerificationExpired):
            await engine.verify(challenge_id=ticket.challenge_id, code=ticket.code_for_delivery)

    async def test_grinding_new_codes_is_refused(self) -> None:
        engine, _ = _engine()
        for _ in range(5):
            await engine.start(tenant_id=TENANT, destination="+201000000004")
        with pytest.raises(VerificationThrottled):
            await engine.start(tenant_id=TENANT, destination="+201000000004")


def _customer(level: AuthenticationLevel, *, principal: uuid.UUID = CUSTOMER):
    return resolve_capability(
        principal_type=PrincipalType.CUSTOMER,
        principal_id=principal,
        tenant_id=TENANT,
        workspace_id=None,
        held_scopes=frozenset(),
        channel=ChannelType.WEB_VOICE,
        authentication_level=level,
    )


class TestCustomerCapability:
    def test_an_anonymous_customer_holds_no_private_scope(self) -> None:
        capability = _customer(AuthenticationLevel.ANONYMOUS)
        assert "customer.own_orders:read" not in capability.scopes
        assert "catalog.published:read" in capability.scopes

    def test_verification_is_what_adds_the_customers_own_data(self) -> None:
        capability = _customer(AuthenticationLevel.VERIFIED)
        assert "customer.own_orders:read" in capability.scopes
        assert "customer.own_returns:read" in capability.scopes

    def test_a_customer_never_holds_merchant_scopes_even_if_they_were_offered(self) -> None:
        capability = resolve_capability(
            principal_type=PrincipalType.CUSTOMER,
            principal_id=CUSTOMER,
            tenant_id=TENANT,
            workspace_id=None,
            held_scopes=frozenset({"analytics:read", "expenses:read"}),
            channel=ChannelType.WHATSAPP_VOICE,
            authentication_level=AuthenticationLevel.VERIFIED,
        )
        assert capability.scopes & {"analytics:read", "expenses:read"} == frozenset()


class TestToolIsolation:
    def test_a_customer_may_read_their_own_orders_and_nothing_else(self) -> None:
        gateway = ToolGateway()
        capability = _customer(AuthenticationLevel.VERIFIED)
        gateway.authorize(capability, "customer.own_orders", subject_id=CUSTOMER)
        with pytest.raises(PermissionDeniedError):
            gateway.authorize(capability, "customer.own_orders", subject_id=OTHER)
        with pytest.raises(PermissionDeniedError):
            gateway.authorize(capability, "analytics.read")
        with pytest.raises(PermissionDeniedError):
            gateway.authorize(capability, "expenses.read")

    def test_an_unverified_customer_cannot_reach_orders_at_all(self) -> None:
        gateway = ToolGateway()
        capability = _customer(AuthenticationLevel.IDENTIFIED)
        with pytest.raises(PermissionDeniedError):
            gateway.authorize(capability, "customer.own_orders", subject_id=CUSTOMER)


class TestCustomerContext:
    def _orders(self) -> tuple[OrderRef, ...]:
        return (
            OrderRef(order_id=uuid.uuid4(), customer_id=CUSTOMER, number="1041", status="shipped"),
            OrderRef(order_id=uuid.uuid4(), customer_id=OTHER, number="1042", status="new"),
        )

    def test_another_customers_order_never_reaches_the_agent(self) -> None:
        context = CustomerContextBuilder().build(
            capability=_customer(AuthenticationLevel.VERIFIED),
            orders=self._orders(),
            discussed_products=("hoodie-xl",),
            policy_refs=("returns.14d",),
            verification_method="otp",
        )
        assert [order.number for order in context.visible_orders] == ["1041"]
        assert context.dropped_foreign_records == 1
        assert "1042" not in context.brief()["orders"]

    def test_an_unverified_session_sees_no_orders_even_if_they_were_passed(self) -> None:
        context = CustomerContextBuilder().build(
            capability=_customer(AuthenticationLevel.IDENTIFIED), orders=self._orders()
        )
        assert context.visible_orders == ()
        assert context.dropped_foreign_records == 2

    def test_a_merchant_session_cannot_be_given_a_customer_context(self) -> None:
        merchant = resolve_capability(
            principal_type=PrincipalType.MERCHANT_USER,
            principal_id=uuid.uuid4(),
            tenant_id=TENANT,
            workspace_id=None,
            held_scopes=frozenset({"orders:read"}),
            channel=ChannelType.WEB_VOICE,
        )
        with pytest.raises(PermissionDeniedError):
            CustomerContextBuilder().build(capability=merchant)
