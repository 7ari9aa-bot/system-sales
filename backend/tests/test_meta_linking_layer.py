"""The shared linking layer: one Page connection, its capabilities, and the facts behind them.

The report's linking-layer gaps (a), (b), (d), (e) and (f). These tests are written to fail on the
mistakes the report kept finding: a subscription that shrinks, a reconnect that asks for everything,
a backfill with no bounds, and an event that is parsed but never persisted.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.modules.customers.meta_linking import (
    CAPABILITY_FIELDS,
    CAPABILITY_SCOPES,
    EVENT_REGISTRY,
    MetaPageConnection,
    PageSubscriptionManager,
    backfill_bounds,
    backfill_supported,
    missing_scopes,
    reconnect_plan,
    registry_rows,
    required_fields,
)


def _integration(**config):
    base = {
        "page_id": "PAGE1",
        "_connection": {"granted_scopes": ["pages_messaging"], "display_name": "متجر"},
    }
    base.update(config)
    return SimpleNamespace(provider="facebook", status="active", config=base, credentials="enc")


def test_the_page_connection_reads_the_row_without_inventing_anything():
    connection = MetaPageConnection.from_integration(_integration())
    assert connection.page_id == "PAGE1"
    assert connection.connected is True
    assert connection.has_token is True
    assert connection.granted_scopes == frozenset({"pages_messaging"})
    # Never measured, so never claimed.
    assert connection.subscribed_fields is None
    assert connection.page_tasks is None


def test_a_row_with_nothing_in_it_claims_nothing():
    connection = MetaPageConnection.from_integration(
        SimpleNamespace(provider="instagram", status="disconnected", config=None, credentials=None)
    )
    assert connection.page_id is None
    assert connection.connected is False
    assert connection.has_token is False
    assert connection.capability_states()


def test_facebook_management_does_not_need_messenger_scopes():
    """The separation the owner asked for, stated once and tested."""
    assert "pages_messaging" not in CAPABILITY_SCOPES["facebook"]
    assert CAPABILITY_SCOPES["messenger"] == ("pages_messaging",)


def test_the_field_set_is_a_union_so_no_capability_is_unsubscribed():
    union = required_fields(("facebook", "messenger"))
    assert "feed" in union and "messages" in union and "message_echoes" in union
    # Order is stable, so two workers compute the same request.
    assert union == required_fields(("messenger", "facebook"))


def test_a_failed_read_never_becomes_a_write():
    """The exact bug from P0-3: a GET that failed must not produce a shorter POST."""
    manager = PageSubscriptionManager("PAGE1")
    plan = manager.plan(("facebook", "messenger"), current=None)
    assert plan["write"] is False
    assert "could not be read" in plan["reason"]


def test_a_field_meta_added_is_kept_not_dropped():
    manager = PageSubscriptionManager("PAGE1")
    plan = manager.plan(("messenger",), current=["messages", "some_future_field"])
    assert "some_future_field" in plan["fields"]


def test_nothing_is_written_when_everything_is_already_subscribed():
    manager = PageSubscriptionManager("PAGE1")
    plan = manager.plan(("messenger",), current=required_fields(("messenger",)))
    assert plan["write"] is False
    assert plan["add"] == []


def test_a_missing_field_is_the_only_thing_added():
    manager = PageSubscriptionManager("PAGE1")
    plan = manager.plan(("messenger",), current=["messages"])
    assert plan["write"] is True
    assert "message_echoes" in plan["add"]
    assert "messages" not in plan["add"]


@pytest.mark.asyncio
async def test_updates_for_one_page_are_serialised():
    """Two concurrent updates for one Page must not interleave their Graph writes."""
    manager = PageSubscriptionManager("PAGE-SERIAL")
    order: list[str] = []

    async def write(fields):
        order.append("start")
        await asyncio.sleep(0.01)
        order.append("end")
        return {"ok": True, "fields": fields}

    await asyncio.gather(
        manager.apply(("messenger",), current=["messages"], write=write),
        manager.apply(("facebook",), current=["messages"], write=write),
    )
    assert order == ["start", "end", "start", "end"]


@pytest.mark.asyncio
async def test_a_no_op_update_never_calls_meta():
    manager = PageSubscriptionManager("PAGE-NOOP")
    called: list[list[str]] = []

    async def write(fields):
        called.append(fields)

    plan = await manager.apply(("messenger",), current=required_fields(("messenger",)), write=write)
    assert plan["write"] is False
    assert called == []


def test_reconnect_asks_only_for_the_missing_capability_scopes():
    connection = MetaPageConnection(
        provider="facebook",
        page_id="PAGE1",
        asset_id="PAGE1",
        status="active",
        has_token=True,
        granted_scopes=frozenset({"pages_messaging"}),
        subscribed_fields=frozenset(required_fields(("messenger",))),
        seen_fields=frozenset(CAPABILITY_FIELDS["messenger"]),
    )
    plan = reconnect_plan(connection, "facebook")
    assert plan["action"] == "request_scopes"
    assert "pages_manage_posts" in plan["scopes"]
    # It must not re-ask for what Messenger already holds.
    assert "pages_messaging" not in plan["scopes"]
    # And Messenger itself needs nothing.
    assert reconnect_plan(connection, "messenger")["action"] == "none"


def test_a_dead_token_is_not_a_missing_permission():
    connection = MetaPageConnection(
        provider="facebook",
        page_id="PAGE1",
        asset_id="PAGE1",
        status="active",
        has_token=False,
        granted_scopes=frozenset({"pages_messaging"}),
    )
    plan = reconnect_plan(connection, "messenger")
    assert plan["failure"] == "token"
    assert plan["action"] == "reconnect_account"


def test_a_webhook_problem_is_not_a_token_problem():
    connection = MetaPageConnection(
        provider="facebook",
        page_id="PAGE1",
        asset_id="PAGE1",
        status="active",
        has_token=True,
        granted_scopes=frozenset({"pages_messaging"}),
        subscribed_fields=frozenset({"messages"}),
        seen_fields=frozenset({"messages"}),
    )
    plan = reconnect_plan(connection, "messenger")
    assert plan["action"] == "fix_subscription"
    assert "message_echoes" in plan["fields"]


def test_an_unreadable_subscription_says_so_instead_of_guessing():
    connection = MetaPageConnection(
        provider="facebook",
        page_id="PAGE1",
        asset_id="PAGE1",
        status="active",
        has_token=True,
        granted_scopes=frozenset({"pages_messaging"}),
        subscribed_fields=None,
    )
    plan = reconnect_plan(connection, "messenger")
    assert plan["action"] == "fix_subscription"
    assert "re-check" in plan["reason"]


def test_a_disconnected_channel_asks_to_connect_first():
    connection = MetaPageConnection(
        provider="facebook", page_id=None, asset_id=None, status="disconnected", has_token=False
    )
    assert reconnect_plan(connection, "messenger")["action"] == "connect"


def test_whatsapp_has_no_backfill_because_meta_has_no_history_api():
    supported, why = backfill_supported("whatsapp")
    assert supported is False
    assert "no history API" in why


def test_every_backfillable_provider_has_bounded_limits():
    for provider in ("messenger", "instagram"):
        bounds = backfill_bounds(provider)
        assert bounds.max_pages > 0 and bounds.max_items > 0 and bounds.max_days > 0
        assert bounds.rate_limit_per_minute > 0
    # An unknown provider gets the most conservative bounds, never unlimited.
    unknown = backfill_bounds("telegram")
    assert unknown.max_items <= 25


def test_every_registered_event_says_what_it_persists_and_what_it_does():
    """An event that is parsed but not persisted is the bug this registry exists to catch."""
    for spec in EVENT_REGISTRY:
        assert spec.persist, spec.field_name
        assert spec.effect, spec.field_name
        assert spec.diagnostic == "delivered"
    fields = {(spec.object, spec.field_name) for spec in EVENT_REGISTRY}
    assert ("page", "message_echoes") in fields
    assert ("page", "messaging_handovers") in fields
    assert ("page", "message_edits") in fields
    assert ("instagram", "live_comments") in fields
    assert ("instagram", "story_insights") in fields
    assert ("whatsapp_business_account", "account_update") in fields


def test_the_registry_rows_are_plain_and_serialisable():
    rows = registry_rows()
    assert rows and all(
        set(row) == {"object", "field", "classify", "persist", "effect", "diagnostic"}
        for row in rows
    )


def test_missing_scopes_says_nothing_when_nothing_was_measured():
    assert missing_scopes("messenger", None) == ()
    assert missing_scopes("messenger", ["pages_messaging"]) == ()
    assert missing_scopes("messenger", []) == ("pages_messaging",)
