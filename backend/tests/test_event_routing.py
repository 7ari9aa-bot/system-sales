"""The platform routes an event by its application prefix, and refuses to guess.

§17: the platform owns the envelope and the transport, the application owns the
meaning. These tests pin the seam so a future dispatcher cannot grow a table of
application names or swallow an event it does not recognise.
"""

from __future__ import annotations

import pytest

from app.applications.apparel.events import event_names, register
from app.platform.events.routing import (
    NoConsumer,
    UnknownApplicationEvent,
    application_of,
    consumers_for,
    consumes,
    dispatch,
    parse,
)


def test_an_event_is_routed_by_its_prefix() -> None:
    route = parse("apparel.orders.sale_completed")
    assert route.application == "apparel"
    assert route.module == "orders"
    assert route.event == "sale_completed"
    assert application_of("apparel.catalog.product_created") == "apparel"


@pytest.mark.parametrize("name", ["", "apparel", "apparel.", ".orders.x", "noprefix"])
def test_a_malformed_name_is_refused(name: str) -> None:
    with pytest.raises(UnknownApplicationEvent):
        parse(name)


async def test_a_registered_event_reaches_its_consumer() -> None:
    register()
    seen: list[dict] = []

    @consumes("apparel.ai.agent_escalated")
    async def record(payload: dict) -> None:
        seen.append(payload)

    try:
        assert consumers_for("apparel.ai.agent_escalated") == (record,)
        assert await dispatch("apparel.ai.agent_escalated", {"reason": "refund"}) == 1
        # A consumer is handed the envelope, not the bare payload: the tenant and
        # the event id are what make its work attributable and repeatable.
        assert seen[0]["type"] == "apparel.ai.agent_escalated"
        assert seen[0]["payload"] == {"reason": "refund"}
    finally:
        # The registry is process-wide; leave it as the test found it.
        from app.platform.events import routing

        routing._CONSUMERS["apparel.ai.agent_escalated"].remove(record)


async def test_an_event_nobody_consumes_is_an_error_not_a_silent_drop() -> None:
    register()
    unhandled = event_names()[0]
    assert consumers_for(unhandled) == ()
    with pytest.raises(NoConsumer):
        await dispatch(unhandled, {})


async def test_an_unknown_type_is_refused() -> None:
    with pytest.raises(UnknownApplicationEvent):
        await dispatch("apparel.orders.not_a_real_event", {})


def test_every_declared_event_is_a_routable_name() -> None:
    register()
    names = event_names()
    assert names, "the apparel manifest declares no events"
    for name in names:
        route = parse(name)
        assert route.application == "apparel"
        assert route.module and route.event


# --- apparel consumers: the mapping each handler writes -------------------


def test_an_escalation_maps_to_one_attributable_audit_row() -> None:
    from app.applications.apparel.consumers import escalation_audit

    row = escalation_audit(
        {
            "type": "apparel.ai.agent_escalated",
            "payload": {"conversation_id": "c-1", "reason": "refund"},
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "workspace_id": "22222222-2222-2222-2222-222222222222",
            "event_id": "evt-9",
        }
    )
    assert row["action"] == "apparel.ai.escalated"
    assert row["resource_type"] == "ai_conversation"
    assert row["resource_id"] == "c-1"
    assert str(row["tenant_id"]) == "11111111-1111-1111-1111-111111111111"
    assert row["after"]["reason"] == "refund"
    assert row["after"]["event_id"] == "evt-9"


def test_a_sale_maps_to_one_attributable_audit_row() -> None:
    from app.applications.apparel.consumers import sale_audit

    row = sale_audit(
        {
            "type": "apparel.sales.sale_completed",
            "payload": {"sale_id": "s-7", "total": "250.00", "currency": "EGP"},
            "tenant_id": None,
            "event_id": "evt-10",
        }
    )
    assert row["action"] == "apparel.sales.sale_completed"
    assert row["resource_type"] == "sale"
    assert row["resource_id"] == "s-7"
    assert row["after"]["total"] == "250.00"
    assert row["tenant_id"] is None


def test_a_malformed_tenant_id_does_not_become_a_row() -> None:
    from app.applications.apparel.consumers import escalation_audit

    row = escalation_audit({"payload": {}, "tenant_id": "not-a-uuid"})
    assert row["tenant_id"] is None


def test_every_consumed_event_is_declared_by_the_manifest() -> None:
    from app.applications.apparel.consumers import CONSUMED_EVENTS

    register()
    declared = set(event_names())
    assert set(CONSUMED_EVENTS) <= declared


def test_consumed_events_are_wired_to_a_handler() -> None:
    import app.applications.apparel.consumers as apparel_consumers

    apparel_consumers.register()
    for name in apparel_consumers.CONSUMED_EVENTS:
        assert consumers_for(name), f"{name} is declared consumed with no handler"
