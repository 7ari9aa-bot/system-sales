"""A conversation that began from a Click-to-Messenger / Click-to-Direct ad keeps a 7-day window.

Meta extended the standard messaging window from 24 hours to 7 days for those conversations
(28 Sep 2026). The policy only knew 24 hours plus the human-agent exception, so it refused a bot
or a person a send that Meta allows. The extension runs from the ad message, never shortens the
ordinary window, and only exists on channels that have it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.applications.apparel.modules.conversations.gateway.base import InboundMessage
from app.applications.apparel.modules.conversations.gateway.ingest import IngestService
from app.applications.apparel.modules.conversations.policy import (
    MessagingPolicyService,
    ad_window_started_at,
    ad_window_state,
)

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _conv(channel="messenger", state="open", last_customer=None):
    return SimpleNamespace(
        channel=channel, messaging_policy_state=state, last_customer_message_at=last_customer
    )


# ---------------------------------------------------------------- the marker round-trips


def test_the_marker_fits_the_column_and_reads_back() -> None:
    state = ad_window_state(NOW)
    assert state == "ad:2026-11-22T12:00:00Z"
    assert len(state) <= 31  # conversations.messaging_policy_state is String(31)
    assert ad_window_started_at(state) == NOW


@pytest.mark.parametrize("state", [None, "", "open", "template_only", "ad:", "ad:garbage", 7])
def test_anything_that_is_not_an_ad_marker_reads_as_no_ad(state) -> None:
    assert ad_window_started_at(state) is None


# ---------------------------------------------------------------- the policy


def test_an_ad_conversation_may_be_answered_by_a_bot_after_24h_but_inside_7_days() -> None:
    started = NOW - timedelta(days=3)
    conv = _conv(state=ad_window_state(started), last_customer=started)
    # sender_type "ai": the human-agent exception does NOT apply to it, only the ad window can
    decision = MessagingPolicyService.evaluate(conv, sender_type="ai", now=NOW)
    assert decision.allowed
    assert not decision.requires_template
    assert decision.human_agent is False  # no HUMAN_AGENT tag is needed for the ad window
    assert decision.window_expires_at == started + timedelta(days=7)


def test_the_same_conversation_without_the_ad_needs_a_template_after_24h() -> None:
    started = NOW - timedelta(days=3)
    decision = MessagingPolicyService.evaluate(
        _conv(state="open", last_customer=started), sender_type="ai", now=NOW
    )
    assert not decision.allowed
    assert decision.requires_template


def test_the_ad_window_ends_after_7_days() -> None:
    started = NOW - timedelta(days=7, minutes=1)
    decision = MessagingPolicyService.evaluate(
        _conv(state=ad_window_state(started), last_customer=started), sender_type="ai", now=NOW
    )
    assert not decision.allowed
    assert decision.requires_template


def test_the_window_runs_from_the_ad_message_not_from_the_latest_message() -> None:
    """A customer who clicked an ad 8 days ago and wrote again an hour ago is in the ordinary
    24-hour window of that last message, not in a fresh 7 days."""
    ad_time = NOW - timedelta(days=8)
    last = NOW - timedelta(hours=30)
    decision = MessagingPolicyService.evaluate(
        _conv(state=ad_window_state(ad_time), last_customer=last), sender_type="ai", now=NOW
    )
    assert not decision.allowed


def test_an_ad_never_shortens_the_ordinary_window() -> None:
    """Ad clicked 7 days ago, but the customer wrote 2 hours ago: the 24h window is open."""
    ad_time = NOW - timedelta(days=7, hours=1)
    last = NOW - timedelta(hours=2)
    decision = MessagingPolicyService.evaluate(
        _conv(state=ad_window_state(ad_time), last_customer=last), sender_type="ai", now=NOW
    )
    assert decision.allowed
    assert decision.window_expires_at == last + timedelta(hours=24)


@pytest.mark.parametrize("channel", ["messenger", "facebook", "instagram"])
def test_it_applies_on_every_meta_chat_channel(channel) -> None:
    started = NOW - timedelta(days=2)
    decision = MessagingPolicyService.evaluate(
        _conv(channel, ad_window_state(started), started), sender_type="ai", now=NOW
    )
    assert decision.allowed


def test_whatsapp_has_no_ad_extension_here() -> None:
    started = NOW - timedelta(days=2)
    decision = MessagingPolicyService.evaluate(
        _conv("whatsapp", ad_window_state(started), started), sender_type="ai", now=NOW
    )
    assert not decision.allowed


def test_the_human_agent_window_still_works_without_an_ad() -> None:
    last = NOW - timedelta(days=3)
    decision = MessagingPolicyService.evaluate(
        _conv(state="open", last_customer=last), sender_type="agent", now=NOW
    )
    assert decision.allowed
    assert decision.human_agent is True


# ---------------------------------------------------------------- ingest recognises an ad


def _msg(**raw) -> InboundMessage:
    return InboundMessage(channel="messenger", channel_message_id="m", customer_ref="u", raw=raw)


@pytest.mark.parametrize(
    "referral",
    [
        {"source": "ADS", "type": "OPEN_THREAD", "ad_id": "AD-1"},
        {"source": "ads"},
        {"ad_id": "AD-9"},
    ],
)
def test_an_ad_referral_is_recognised(referral) -> None:
    assert IngestService._came_from_ad(_msg(_messenger={"referral": referral}))


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"_messenger": {}},
        {"_messenger": {"referral": {"source": "SHORTLINK", "ref": "promo"}}},
        {"_messenger": {"referral": "ADS"}},
        {"_messenger": {"postback_payload": "X"}},
    ],
)
def test_an_ordinary_message_or_link_referral_is_not_an_ad(raw) -> None:
    assert not IngestService._came_from_ad(_msg(**raw))


def test_a_postback_that_carries_an_ad_referral_counts() -> None:
    assert IngestService._came_from_ad(
        _msg(_messenger={"postback_payload": "GET_STARTED", "referral": {"ad_id": "AD-2"}})
    )


def test_the_messenger_adapter_output_is_what_ingest_reads() -> None:
    """Adapter and ingest must agree on where the referral lives."""
    from app.applications.apparel.modules.conversations.gateway.messenger import messenger_adapter

    payload = {
        "object": "page",
        "entry": [
            {
                "id": "P",
                "messaging": [
                    {
                        "sender": {"id": "U"},
                        "recipient": {"id": "P"},
                        "timestamp": 1,
                        "referral": {"source": "ADS", "type": "OPEN_THREAD", "ad_id": "AD-1"},
                    }
                ],
            }
        ],
    }
    [message] = messenger_adapter.parse_inbound(payload)
    assert IngestService._came_from_ad(message)


def test_an_instagram_ad_referral_is_parsed_and_recognised() -> None:
    from app.applications.apparel.modules.conversations.gateway.instagram import instagram_adapter

    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "IG",
                "messaging": [
                    {
                        "sender": {"id": "U"},
                        "recipient": {"id": "IG"},
                        "timestamp": 5,
                        "referral": {"source": "ADS", "ad_id": "AD-3"},
                    }
                ],
            }
        ],
    }
    [message] = instagram_adapter.parse_inbound(payload)
    assert message.channel_message_id.startswith("referral:")
    assert IngestService._came_from_ad(message)
    [again] = instagram_adapter.parse_inbound(payload)
    assert again.channel_message_id == message.channel_message_id
