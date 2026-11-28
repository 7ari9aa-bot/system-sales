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
        assert seen == [{"reason": "refund"}]
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
