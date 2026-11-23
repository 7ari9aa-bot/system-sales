"""A Meta channel's health report names each thing that can stop messages arriving.

"Connected" only means the login worked. Messages also need the Page subscribed, every field
ticked, the dashboard webhook set and the server able to verify Meta's signature. Each is its own
check with its own fix, and a Meta outage must read as "unknown", never as a failed request.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.modules.customers import meta_channel_diagnostics as d
from app.modules.customers.meta_oauth import subscribed_fields
from app.modules.customers.meta_scopes import FACEBOOK_PAGE_SCOPES, MESSENGER_SCOPES

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
ALL_MESSENGER = MESSENGER_SCOPES.split(",")


def _report(provider="messenger", **overrides):
    args = {
        "provider": provider,
        "status": "active",
        "config": {},
        # A delivery for every field the channel depends on: since the diagnostic stopped treating
        # one `messages` event as proof for all of them, a healthy channel means each one arrived.
        "webhook_health": {
            "last_webhook_at": (NOW - timedelta(hours=1)).isoformat(),
            "seen_fields": {
                f: (NOW - timedelta(hours=1)).isoformat()
                for f in d.REQUIRED_FIELDS[d.WEBHOOK_OBJECT[provider][0]]
            },
        },
        "recorded_scopes": ALL_MESSENGER + list(FACEBOOK_PAGE_SCOPES),
        "subscription": {"state": "ok", "fields": subscribed_fields(provider).split(",")},
        "permissions": None,
        "server_webhook_ready": True,
        "api_base_url": "https://api.example.com",
        "now": NOW,
    }
    args.update(overrides)
    return d.build_report(**args)


def _by_key(report) -> dict:
    return {c["key"]: c for c in report["checks"]}


# ------------------------------------------------------------------ the happy path


def test_a_healthy_channel_is_all_ok() -> None:
    report = _report()
    assert report["state"] == d.OK
    assert {c["status"] for c in report["checks"]} == {d.OK}


def test_the_callback_to_register_is_named_per_meta_object() -> None:
    assert (
        _report("messenger")["callback_url"] == "https://api.example.com/api/v1/webhooks/meta/page"
    )
    assert (
        _report("facebook")["callback_url"] == "https://api.example.com/api/v1/webhooks/meta/page"
    )
    assert (
        _report("instagram")["callback_url"] == "https://api.example.com/api/v1/webhooks/instagram"
    )
    assert _report("whatsapp")["callback_url"] == "https://api.example.com/api/v1/webhooks/whatsapp"
    assert _report("instagram")["webhook_object"] == "instagram"
    assert _report("whatsapp")["webhook_object"] == "whatsapp_business_account"


# ------------------------------------------------------------------ connection


@pytest.mark.parametrize(
    ("status", "expected"),
    [("reauth_required", d.ERROR), ("restricted", d.WARNING), ("disconnected", d.ERROR)],
)
def test_the_connection_check_follows_the_channel_status(status, expected) -> None:
    check = _by_key(_report(status=status))["connection"]
    assert check["status"] == expected
    assert check["action"]


# ------------------------------------------------------------------ permissions


def test_a_missing_permission_is_named() -> None:
    report = _report(recorded_scopes=["pages_show_list"])
    check = _by_key(report)["permissions"]
    assert check["status"] == d.ERROR  # pages_messaging missing: chat cannot work
    assert "pages_messaging" in check["detail"]["missing"]
    assert check["detail"]["source"] == "recorded"


def test_what_meta_says_now_beats_what_we_recorded() -> None:
    """The owner can revoke a permission later; the live answer is the truth."""
    report = _report(
        recorded_scopes=ALL_MESSENGER,
        permissions={"state": d.OK, "granted": ["pages_show_list"]},
    )
    check = _by_key(report)["permissions"]
    assert check["status"] == d.ERROR
    assert check["detail"]["source"] == "meta"


def test_a_facebook_channel_missing_only_a_posting_permission_is_a_warning() -> None:
    report = _report("facebook", recorded_scopes=ALL_MESSENGER)
    check = _by_key(report)["permissions"]
    assert check["status"] == d.WARNING
    assert "pages_manage_posts" in check["detail"]["missing"]


def test_instagram_names_its_own_scopes() -> None:
    report = _report("instagram", recorded_scopes=["pages_messaging", "instagram_manage_messages"])
    missing = _by_key(report)["permissions"]["detail"]["missing"]
    # instagram_manage_insights joined the required set: the post view calls /{media_id}/insights.
    assert missing == [
        "instagram_manage_comments",
        "instagram_content_publish",
        "instagram_manage_insights",
    ]


def test_unreadable_permissions_are_unknown_not_an_error() -> None:
    report = _report(recorded_scopes=None, permissions={"state": d.UNKNOWN})
    assert _by_key(report)["permissions"]["status"] == d.UNKNOWN


def test_whatsapp_has_no_page_permission_check() -> None:
    assert "permissions" not in _by_key(_report("whatsapp"))


# ------------------------------------------------------------------ server


def test_a_server_that_cannot_verify_meta_is_an_error() -> None:
    check = _by_key(_report(server_webhook_ready=False))["server_webhook"]
    assert check["status"] == d.ERROR
    assert "verify token" in check["summary"]


# ------------------------------------------------------------------ asset subscription


def test_a_page_not_subscribed_to_our_app_is_an_error() -> None:
    check = _by_key(_report(subscription={"state": "missing", "apps_listed": 2}))[
        "asset_subscription"
    ]
    assert check["status"] == d.ERROR


def test_a_subscription_missing_fields_names_them() -> None:
    sub = {"state": "ok", "fields": ["messages"]}
    check = _by_key(_report(subscription=sub))["asset_subscription"]
    assert check["status"] == d.WARNING
    assert "message_reads" in check["detail"]["missing_fields"]


def test_facebook_needs_feed_and_messenger_does_not() -> None:
    messenger_fields = subscribed_fields("messenger").split(",")
    assert (
        _by_key(_report("messenger", subscription={"state": "ok", "fields": messenger_fields}))[
            "asset_subscription"
        ]["status"]
        == d.OK
    )
    check = _by_key(_report("facebook", subscription={"state": "ok", "fields": messenger_fields}))[
        "asset_subscription"
    ]
    assert check["status"] == d.WARNING
    assert "feed" in check["detail"]["missing_fields"]


def test_a_refused_probe_carries_metas_own_error() -> None:
    sub = {"state": d.ERROR, "meta": {"code": 190, "message": "expired"}}
    check = _by_key(_report(subscription=sub))["asset_subscription"]
    assert check["status"] == d.ERROR
    assert check["detail"]["meta"]["code"] == 190


def test_an_unreachable_meta_is_unknown_not_an_error() -> None:
    check = _by_key(_report(subscription={"state": d.UNKNOWN}))["asset_subscription"]
    assert check["status"] == d.UNKNOWN


def test_a_channel_that_was_not_probed_has_no_subscription_check() -> None:
    assert "asset_subscription" not in _by_key(_report(subscription=None))


def test_whatsapp_only_needs_messages() -> None:
    report = _report("whatsapp", subscription={"state": "ok", "fields": ["messages"]})
    assert _by_key(report)["asset_subscription"]["status"] == d.OK


# ------------------------------------------------------------------ the dashboard webhook


def test_a_channel_that_never_received_anything_is_told_what_to_set_in_the_dashboard() -> None:
    report = _report(webhook_health={})
    check = _by_key(report)["dashboard_webhook"]
    assert check["status"] == d.WARNING
    assert check["detail"]["callback_url"] == "https://api.example.com/api/v1/webhooks/meta/page"
    assert "message_reads" in check["detail"]["fields"]
    assert check["detail"]["object"] == "page"


def test_one_delivery_proves_only_its_own_field() -> None:
    """The old rule: any webhook at all made the dashboard check green.

    That hid a real fault — a staff reply typed in Meta's own inbox arrives as `message_echoes`,
    which is a SEPARATE dashboard tick. A store with `messages` alone saw a healthy channel and
    lost every reply its staff typed on Meta's side.
    """
    only_messages = _report(
        webhook_health={
            "last_webhook_at": (NOW - timedelta(hours=1)).isoformat(),
            "seen_fields": {"messages": (NOW - timedelta(hours=1)).isoformat()},
        }
    )
    check = _by_key(only_messages)["dashboard_webhook"]
    assert check["status"] == d.WARNING
    assert "message_echoes" in check["detail"]["unseen_fields"]
    assert only_messages["state"] != d.OK

    assert _by_key(_report())["dashboard_webhook"]["status"] == d.OK


def test_a_disconnected_channel_is_not_told_to_set_the_dashboard() -> None:
    report = _report(status="disconnected", webhook_health={}, subscription=None)
    assert "dashboard_webhook" not in _by_key(report)


# ------------------------------------------------------------------ failures and quiet


def test_failed_events_surface_the_last_error() -> None:
    health = {
        "last_webhook_at": NOW.isoformat(),
        "consecutive_failures": 4,
        "last_error": "boom",
        "last_failure_at": NOW.isoformat(),
    }
    check = _by_key(_report(webhook_health=health, failed_events=7))["recent_failures"]
    assert check["status"] == d.ERROR
    assert check["detail"]["last_error"] == "boom"
    assert check["detail"]["failed_events"] == 7


def test_one_failure_is_only_a_warning() -> None:
    health = {"last_webhook_at": NOW.isoformat(), "consecutive_failures": 1}
    assert _by_key(_report(webhook_health=health))["recent_failures"]["status"] == d.WARNING


def test_dead_events_alone_are_reported_even_with_no_streak() -> None:
    report = _report(failed_events=2)
    assert _by_key(report)["recent_failures"]["status"] == d.WARNING


def test_a_long_silence_is_a_warning_after_three_days() -> None:
    health = {"last_webhook_at": (NOW - timedelta(days=5)).isoformat()}
    check = _by_key(_report(webhook_health=health))["recent_activity"]
    assert check["status"] == d.WARNING
    assert "5 days" in check["summary"]


def test_two_quiet_days_are_not_a_problem() -> None:
    health = {"last_webhook_at": (NOW - timedelta(days=2)).isoformat()}
    assert "recent_activity" not in _by_key(_report(webhook_health=health))


def test_the_overall_state_is_the_worst_check() -> None:
    report = _report(subscription={"state": "missing"}, server_webhook_ready=False)
    assert report["state"] == d.ERROR
    assert _report(subscription={"state": d.UNKNOWN})["state"] == d.UNKNOWN


def test_a_report_never_contains_a_token() -> None:
    health = {"last_webhook_at": NOW.isoformat(), "consecutive_failures": 1, "last_error": "x"}
    text = repr(_report(webhook_health=health, config={"token": "SECRET-TOKEN"}))
    assert "SECRET-TOKEN" not in text


# ------------------------------------------------------------------ the probes


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_the_subscription_probe_finds_our_app_and_its_fields() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "OTHER", "subscribed_fields": ["feed"]},
                    {"id": "APP", "subscribed_fields": ["messages", "feed"]},
                ]
            },
        )

    async with _client(handler) as http:
        out = await d.probe_subscription(http, asset_id="111", token="TOK", app_id="APP")
    assert out == {"state": "ok", "fields": ["feed", "messages"]}
    assert seen[0].headers["authorization"] == "Bearer TOK"
    assert "access_token" not in seen[0].url.params


async def test_an_app_not_in_the_list_is_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "OTHER", "subscribed_fields": ["feed"]}]})

    async with _client(handler) as http:
        out = await d.probe_subscription(http, asset_id="1", token="T", app_id="APP")
    assert out["state"] == "missing"


async def test_an_empty_list_is_missing() -> None:
    async with _client(lambda r: httpx.Response(200, json={"data": []})) as http:
        out = await d.probe_subscription(http, asset_id="1", token="T", app_id="APP")
    assert out["state"] == "missing"


async def test_a_refusal_keeps_metas_error() -> None:
    body = {"error": {"code": 190, "error_subcode": 463, "message": "Session expired"}}
    async with _client(lambda r: httpx.Response(400, json=body)) as http:
        out = await d.probe_subscription(http, asset_id="1", token="T", app_id="APP")
    assert out["state"] == d.ERROR
    assert out["meta"]["code"] == 190
    assert out["meta"]["subcode"] == 463


async def test_an_unreachable_meta_is_unknown() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with _client(handler) as http:
        assert (await d.probe_subscription(http, asset_id="1", token="T", app_id="A"))[
            "state"
        ] == d.UNKNOWN
        assert (await d.probe_permissions(http, token="T"))["state"] == d.UNKNOWN


async def test_an_unreadable_answer_is_unknown() -> None:
    async with _client(lambda r: httpx.Response(200, text="<html>")) as http:
        out = await d.probe_subscription(http, asset_id="1", token="T", app_id="A")
    assert out["state"] == d.UNKNOWN


async def test_the_permission_probe_keeps_only_granted() -> None:
    body = {
        "data": [
            {"permission": "pages_messaging", "status": "granted"},
            {"permission": "pages_manage_posts", "status": "declined"},
            {"permission": "read_insights", "status": "expired"},
        ]
    }
    async with _client(lambda r: httpx.Response(200, json=body)) as http:
        out = await d.probe_permissions(http, token="T")
    assert out == {"state": "ok", "granted": ["pages_messaging"]}


async def test_with_no_app_id_the_first_listed_app_is_used() -> None:
    body = {"data": [{"id": "X", "subscribed_fields": ["messages"]}]}
    async with _client(lambda r: httpx.Response(200, json=body)) as http:
        out = await d.probe_subscription(http, asset_id="1", token="T", app_id=None)
    assert out == {"state": "ok", "fields": ["messages"]}
