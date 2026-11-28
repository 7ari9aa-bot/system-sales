"""The channel badge must not be green just because one webhook arrived.

Meta's app-level subscription (the dashboard ticks) cannot be read with a Page token, so the
diagnostic inferred it from traffic — and a single `messages` delivery made the whole channel look
healthy. A staff reply typed in Meta's own inbox (`message_echoes`) or a human taking the thread
(`messaging_handovers`) would then be dropped with the screen showing everything fine.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.applications.apparel.modules.conversations.routers.webhooks import webhook_fields
from app.applications.apparel.modules.customers.meta_channel_diagnostics import (
    DASHBOARD_FIELDS,
    REQUIRED_FIELDS,
    build_report,
)
from app.applications.apparel.modules.customers.meta_scopes import FACEBOOK_PAGE_SCOPES, MESSENGER_SCOPES

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)


# ------------------------------------------------------- what a delivery proves


def test_a_page_comment_proves_the_feed_field():
    payload = {"entry": [{"id": "p", "changes": [{"field": "feed", "value": {}}]}]}
    assert webhook_fields(payload) == ["feed"]


def test_a_customer_message_proves_messages_only():
    payload = {"entry": [{"messaging": [{"message": {"mid": "m1", "text": "hi"}}]}]}
    assert webhook_fields(payload) == ["messages"]


def test_an_echo_proves_message_echoes_not_messages():
    payload = {
        "entry": [{"messaging": [{"message": {"mid": "m2", "text": "رد الموظف", "is_echo": True}}]}]
    }
    assert webhook_fields(payload) == ["message_echoes"]


def test_a_takeover_proves_messaging_handovers():
    payload = {"entry": [{"messaging": [{"take_thread_control": {"new_owner_app_id": 1}}]}]}
    assert webhook_fields(payload) == ["messaging_handovers"]


def test_a_whatsapp_template_update_proves_its_own_field():
    payload = {"entry": [{"id": "waba", "changes": [{"field": "message_template_status_update"}]}]}
    assert webhook_fields(payload) == ["message_template_status_update"]


# ------------------------------------------------------- the field lists


def test_whatsapp_checks_account_quality_and_templates_not_messages_only():
    fields = DASHBOARD_FIELDS["whatsapp_business_account"]

    assert "messages" in fields
    assert "account_update" in fields
    assert "phone_number_quality_update" in fields
    assert "message_template_status_update" in fields


def test_every_required_field_is_also_a_dashboard_field():
    for obj, required in REQUIRED_FIELDS.items():
        assert set(required) <= set(DASHBOARD_FIELDS[obj]), obj


# ------------------------------------------------------- the verdict


def _report(seen_fields: dict[str, str]) -> dict:
    return build_report(
        provider="messenger",
        status="active",
        config={"account_id": "page-1"},
        webhook_health={
            "last_webhook_at": NOW.isoformat(),
            "seen_fields": seen_fields,
        },
        recorded_scopes=list(MESSENGER_SCOPES.split(",")) + list(FACEBOOK_PAGE_SCOPES),
        subscription={"state": "ok", "fields": list(DASHBOARD_FIELDS["page"])},
        permissions={
            "state": "ok",
            "granted": list(MESSENGER_SCOPES.split(",")) + list(FACEBOOK_PAGE_SCOPES),
        },
        server_webhook_ready=True,
        api_base_url="https://api.example",
        now=NOW,
    )


def _check(report: dict, key: str) -> dict:
    """A check carries its stable `key`; the human text sits in summary/action/detail."""
    return next(c for c in report["checks"] if c["key"] == key)


def test_messages_arriving_alone_do_not_make_the_channel_green():
    report = _report({"messages": (NOW - timedelta(minutes=5)).isoformat()})

    dashboard = _check(report, "dashboard_webhook")
    assert dashboard["status"] == "warning"
    assert "message_echoes" in dashboard["detail"]["unseen_fields"]
    assert report["state"] != "ok"


def test_every_required_field_delivered_is_green():
    seen = {field: NOW.isoformat() for field in REQUIRED_FIELDS["page"]}

    report = _report(seen)

    dashboard = _check(report, "dashboard_webhook")
    assert dashboard["status"] == "ok"
    assert report["state"] == "ok"


def test_a_field_never_delivered_is_named_with_what_to_do():
    report = _report({"messages": NOW.isoformat()})

    dashboard = _check(report, "dashboard_webhook")
    assert "messaging_handovers" in dashboard["detail"]["unseen_fields"]
    assert "Meta app dashboard" in dashboard["action"]
