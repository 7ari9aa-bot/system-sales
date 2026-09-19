"""Spec §30-31 — outbound messaging policy and the customer-service window.

Pure unit tests: the decision is a pure function of (channel, window anchor,
template state, now), so no database is needed. Each test encodes one provider
rule; deleting the rule fails the test rather than silently allowing a send
that the provider would reject.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.errors import DomainError
from app.modules.conversations.policy import (
    CHANNEL_POLICIES,
    MessagingPolicyService,
    OutboundBlockedError,
    policy_for,
)

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


@dataclass
class FakeConversation:
    channel: str
    last_customer_message_at: datetime | None = None


def _conv(channel: str, hours_since_customer: float | None) -> FakeConversation:
    anchor = (
        None
        if hours_since_customer is None
        else NOW - timedelta(hours=hours_since_customer)
    )
    return FakeConversation(channel=channel, last_customer_message_at=anchor)


# --- the policy table -------------------------------------------------------


def test_channels_with_a_window_are_regulated() -> None:
    for channel in ("whatsapp", "messenger", "instagram"):
        policy = policy_for(channel)
        assert policy.window_hours == 24, channel
        assert policy.supports_templates is True
        assert policy.template_provider == channel


def test_channels_without_a_window_are_not() -> None:
    for channel in ("telegram", "webchat", "email"):
        assert policy_for(channel).window_hours is None


def test_unknown_channel_is_unregulated_not_blocked() -> None:
    """An unmodelled channel must not become a silent outage."""
    assert policy_for("carrier-pigeon").window_hours is None
    assert policy_for(None).window_hours is None
    assert "whatsapp" in CHANNEL_POLICIES


# --- the window -------------------------------------------------------------


def test_inside_window_allows_free_form() -> None:
    decision = MessagingPolicyService.evaluate(_conv("whatsapp", 23), now=NOW)
    assert decision.allowed is True
    assert decision.requires_template is False
    assert decision.window_open is True
    assert decision.window_expires_at == NOW + timedelta(hours=1)


def test_outside_window_blocks_free_form_and_demands_a_template() -> None:
    decision = MessagingPolicyService.evaluate(_conv("whatsapp", 25), now=NOW)
    assert decision.allowed is False
    assert decision.requires_template is True
    assert "template is required" in decision.reason


def test_exactly_at_expiry_is_outside() -> None:
    """The window is half-open: at the boundary it is already closed."""
    decision = MessagingPolicyService.evaluate(_conv("whatsapp", 24), now=NOW)
    assert decision.allowed is False


def test_customer_never_wrote_requires_a_template() -> None:
    """No inbound message means no window has ever opened."""
    decision = MessagingPolicyService.evaluate(_conv("whatsapp", None), now=NOW)
    assert decision.allowed is False
    assert decision.requires_template is True
    assert decision.window_expires_at is None


def test_unregulated_channel_ignores_the_window_entirely() -> None:
    decision = MessagingPolicyService.evaluate(_conv("telegram", None), now=NOW)
    assert decision.allowed is True
    assert decision.window_expires_at is None


# --- templates --------------------------------------------------------------


def test_approved_template_unblocks_outside_the_window() -> None:
    decision = MessagingPolicyService.evaluate(
        _conv("whatsapp", 48),
        template_name="order_update",
        template_approved=True,
        template_provider="whatsapp",
        now=NOW,
    )
    assert decision.allowed is True
    assert decision.template_name == "order_update"


def test_unapproved_template_is_refused() -> None:
    """Draft/submitted/rejected templates must never reach a customer."""
    decision = MessagingPolicyService.evaluate(
        _conv("whatsapp", 48),
        template_name="order_update",
        template_approved=False,
        template_provider="whatsapp",
        now=NOW,
    )
    assert decision.allowed is False
    assert "not approved" in decision.reason


def test_template_from_another_provider_is_refused() -> None:
    decision = MessagingPolicyService.evaluate(
        _conv("whatsapp", 48),
        template_name="order_update",
        template_approved=True,
        template_provider="messenger",
        now=NOW,
    )
    assert decision.allowed is False
    assert "provider" in decision.reason


def test_template_inside_the_window_still_allows_free_form() -> None:
    """A template is permitted (not required) while the window is open."""
    decision = MessagingPolicyService.evaluate(
        _conv("whatsapp", 1),
        template_name="order_update",
        template_approved=True,
        template_provider="whatsapp",
        now=NOW,
    )
    assert decision.allowed is True
    assert decision.requires_template is False


# --- the error contract -----------------------------------------------------


def test_blocked_error_is_a_domain_error_with_a_stable_code() -> None:
    err = OutboundBlockedError("outside the 24h window")
    assert isinstance(err, DomainError)
    assert err.code == "outbound_blocked"
    assert err.http_status == 409
    # Retrying unchanged cannot help — the customer has to write back, or the
    # caller has to switch to a template.
    assert err.retryable is False


def test_decision_is_explainable() -> None:
    """Every verdict carries a reason a support agent can act on."""
    for conv in (_conv("whatsapp", 1), _conv("whatsapp", 48), _conv("telegram", None)):
        decision = MessagingPolicyService.evaluate(conv, now=NOW)
        assert decision.reason
