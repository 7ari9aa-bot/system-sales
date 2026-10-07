"""§144 — event priority tiers.

"Campaign كبيرة من Tenant A لا يجوز أن تجوع Tenant B" — and the tie-break
order is fixed by the spec: Human Response > AI Response > Critical System
Events > Customer Webhooks > Normal Automation > Bulk/Campaign Work.

The tiers are a lookup over REAL event types (DOMAIN_EVENT_TYPES), so the
scheduler/worker side can ask "how urgent is this envelope" without a
per-module guessing map. Unknown types default to the automation tier:
never treated as more urgent than the spec says, never silently dropped.
"""

from __future__ import annotations

from app.core.fairness import DOMAIN_PRIORITIES, EventPriority, priority_for


def test_priority_order_matches_the_spec_tiers():
    order = [
        EventPriority.HUMAN_RESPONSE,
        EventPriority.AI_RESPONSE,
        EventPriority.CRITICAL_SYSTEM,
        EventPriority.CUSTOMER_WEBHOOK,
        EventPriority.NORMAL_AUTOMATION,
        EventPriority.BULK_CAMPAIGN,
    ]
    assert [p.rank for p in order] == [1, 2, 3, 4, 5, 6]
    # Ordering is total: every adjacent pair compares.
    assert all(a < b for a, b in zip(order[:-1], order[1:], strict=True))


def test_human_and_bulk_sits_at_opposite_ends():
    assert priority_for("message.outbound") is EventPriority.HUMAN_RESPONSE
    assert priority_for("campaign.run.started") is EventPriority.BULK_CAMPAIGN
    assert priority_for("campaign.run.batch") is EventPriority.BULK_CAMPAIGN
    assert priority_for("message.outbound") < priority_for("campaign.run.started")


def test_customer_webhooks_outrank_automation_but_not_ai():
    assert priority_for("webhook.ingest") is EventPriority.CUSTOMER_WEBHOOK
    assert priority_for("webhook.deliver") is EventPriority.CUSTOMER_WEBHOOK
    assert priority_for("message.received") < priority_for("webhook.ingest")
    assert priority_for("webhook.ingest") < priority_for("saga.started")


def test_every_registered_domain_type_has_an_explicit_tier():
    """No fall-through guesses for real types: each registered event names
    its tier (the default exists for future types, not for laziness)."""
    from app.core.events.schemas import DOMAIN_EVENT_TYPES

    for event_type in DOMAIN_EVENT_TYPES:
        if event_type.startswith("test."):
            continue
        assert event_type in DOMAIN_PRIORITIES, f"{event_type} has no tier"


def test_unknown_types_default_to_normal_automation():
    assert priority_for("some.future.event") is EventPriority.NORMAL_AUTOMATION
