"""One honest state per capability: no dead button without a reason, no false green.

A channel that receives `messages` is not a healthy channel: a staff reply typed in Meta's own
inbox (`message_echoes`), a human taking the thread (`messaging_handovers`) or an edited message
(`message_edits`) would still be dropped. Each capability is therefore judged on its own scopes,
its own asset-subscription fields and the fields Meta has actually delivered.
"""

from __future__ import annotations

from app.modules.customers import capability_states as cs
from app.modules.customers.meta_channel_diagnostics import build_report
from app.modules.customers.meta_oauth import subscribed_fields

#: What our own connect flow subscribes the Page to, so the asset-subscription check is honest.
OUR_FIELDS = subscribed_fields("messenger").split(",")


def _state(capabilities, key):
    return next(c["state"] for c in capabilities if c["key"] == key)


# ---------------------------------------------------------------- the states themselves


def test_a_channel_that_never_connected_is_not_called_available():
    caps = cs.evaluate("messenger", connected=False, granted_scopes=set())

    assert {c["state"] for c in caps} == {cs.NEEDS_CONNECTION}


def test_messages_arriving_does_not_make_staff_reply_sync_available():
    caps = cs.evaluate(
        "messenger",
        connected=True,
        granted_scopes={"pages_messaging"},
        subscription_fields={"messages", "message_echoes", "messaging_handovers"},
        seen_fields={"messages"},
    )

    assert _state(caps, "inbox") == cs.AVAILABLE
    assert _state(caps, "staff_reply_sync") == cs.DASHBOARD_FIELD_MISSING
    assert _state(caps, "handover") == cs.DASHBOARD_FIELD_MISSING
    reason = next(c for c in caps if c["key"] == "staff_reply_sync")["reason"]
    assert "message_echoes" in reason


def test_a_missing_scope_is_a_permission_state_not_a_generic_failure():
    caps = cs.evaluate(
        "instagram",
        connected=True,
        granted_scopes={"instagram_business_manage_messages"},
        subscription_fields={"messages", "comments", "mentions", "messaging_handovers"},
        seen_fields={"messages"},
    )

    assert _state(caps, "direct") == cs.AVAILABLE
    assert _state(caps, "comments") == cs.NEEDS_PERMISSION
    reason = next(c for c in caps if c["key"] == "comments")["reason"]
    assert "instagram_business_manage_comments" in reason


def test_a_field_missing_from_the_asset_subscription_is_named_as_such():
    caps = cs.evaluate(
        "messenger",
        connected=True,
        granted_scopes={"pages_messaging"},
        subscription_fields={"messages"},
        seen_fields={"messages"},
    )

    assert _state(caps, "staff_reply_sync") == cs.ASSET_SUBSCRIPTION_MISSING


def test_an_unreadable_subscription_is_unverified_not_broken():
    caps = cs.evaluate(
        "messenger",
        connected=True,
        granted_scopes={"pages_messaging"},
        subscription_fields=None,
        seen_fields={"messages"},
        subscription_known=False,
    )

    assert _state(caps, "inbox") == cs.NO_LIVE_EVENT_VERIFIED


def test_whatsapp_template_status_is_its_own_capability():
    caps = cs.evaluate(
        "whatsapp",
        connected=True,
        granted_scopes=set(),
        subscription_fields={"messages", "account_update", "phone_number_quality_update",
                             "message_template_status_update"},
        seen_fields={"messages"},
    )

    assert _state(caps, "messages") == cs.AVAILABLE
    assert _state(caps, "templates") == cs.AVAILABLE, "subscription is enough; no live field needed"


def test_whatsapp_gaps_are_labelled_honestly():
    caps = cs.evaluate("whatsapp", connected=True, granted_scopes=set(),
                       subscription_fields={"messages"}, seen_fields={"messages"})

    assert _state(caps, "flows") == cs.NOT_IMPLEMENTED, "ours to build, not Meta's limit"
    assert _state(caps, "calls") == cs.REGION_RESTRICTED


def test_every_declared_capability_gets_a_known_state():
    for provider in ("messenger", "facebook", "instagram", "whatsapp"):
        caps = cs.evaluate(provider, connected=True, granted_scopes=None,
                           subscription_fields=None, seen_fields=set(),
                           subscription_known=False)
        assert caps, provider
        for cap in caps:
            assert cap["state"] in cs.STATES, (provider, cap)


# ---------------------------------------------------------------- inside the report


def _report(**over):
    base = dict(
        provider="messenger",
        status="active",
        config={"page_id": "1"},
        webhook_health={"last_webhook_at": "2026-11-22T10:00:00Z",
                        "seen_fields": {"messages": "2026-11-22T10:00:00Z"}},
        recorded_scopes=["pages_messaging", "pages_show_list", "pages_read_engagement",
                         "pages_manage_metadata", "pages_manage_engagement",
                         "pages_manage_posts", "read_insights", "business_management"],
        subscription={"state": "ok", "fields": list(OUR_FIELDS)},
        permissions=None,
        server_webhook_ready=True,
        api_base_url="https://api.example.com",
    )
    base.update(over)
    return build_report(**base)


def test_a_messenger_channel_with_only_messages_is_not_reported_healthy():
    report = _report()

    assert report["state"] == "warning"
    caps = {c["key"]: c["state"] for c in report["capabilities"]}
    assert caps["inbox"] == cs.AVAILABLE
    assert caps["staff_reply_sync"] == cs.DASHBOARD_FIELD_MISSING


def test_once_every_field_has_delivered_the_capabilities_go_green():
    report = _report(
        webhook_health={
            "last_webhook_at": "2026-11-22T10:00:00Z",
            "seen_fields": {"messages": "2026-11-22T10:00:00Z",
                            "message_echoes": "2026-11-22T10:00:00Z",
                            "messaging_handovers": "2026-11-22T10:00:00Z"},
        }
    )

    assert report["state"] == "ok"
    caps = {c["key"]: c["state"] for c in report["capabilities"]}
    assert caps["inbox"] == cs.AVAILABLE
    assert caps["staff_reply_sync"] == cs.AVAILABLE
    assert caps["handover"] == cs.AVAILABLE


def test_an_unconnected_channel_reports_every_capability_as_needing_connection():
    report = _report(status="disconnected", subscription=None)

    assert {c["state"] for c in report["capabilities"]} == {cs.NEEDS_CONNECTION}
