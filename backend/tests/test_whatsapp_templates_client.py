"""WhatsApp template client: what it validates locally and what it sends to Meta."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.circuit_breaker import reset_breakers
from app.core.errors import ExternalProviderError, ValidationError
from app.applications.apparel.modules.conversations.gateway import whatsapp_templates as wt

CREDS = {"access_token": "tok", "waba_id": "555"}


@pytest.fixture(autouse=True)
def _closed_breaker():
    reset_breakers()
    yield
    reset_breakers()


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ------------------------------------------------------------- local validation


def test_name_must_be_lowercase_underscore():
    assert wt.check_name("order_ready_2") == "order_ready_2"
    for bad in ("Order", "order-ready", "طلب", "", "a b"):
        with pytest.raises(ValidationError):
            wt.check_name(bad)


def test_body_variables_must_be_sequential():
    assert wt.check_positional("hi {{1}} and {{2}} ok", where="body") == 2
    with pytest.raises(ValidationError, match="no gap"):
        wt.check_positional("hi {{1}} and {{3}} ok", where="body")


def test_body_may_not_start_or_end_with_a_variable():
    with pytest.raises(ValidationError, match="start or end"):
        wt.check_positional("{{1}} your order", where="body")
    with pytest.raises(ValidationError, match="start or end"):
        wt.check_positional("your order {{1}}", where="body")
    assert wt.check_positional("your order {{1}} is ready", where="body") == 1


def test_a_variable_needs_an_example_value():
    with pytest.raises(ValidationError, match="example"):
        wt.build_components(body="hi {{1}}, ready")
    parts = wt.build_components(body="hi {{1}}, ready", body_examples=["Omar"])
    assert parts == [
        {"type": "BODY", "text": "hi {{1}}, ready", "example": {"body_text": [["Omar"]]}}
    ]


def test_components_are_ordered_header_body_footer_buttons():
    parts = wt.build_components(
        body="ready",
        header_text="Order",
        footer="Thanks",
        buttons=[{"type": "QUICK_REPLY", "text": "OK"}],
    )
    assert [p["type"] for p in parts] == ["HEADER", "BODY", "FOOTER", "BUTTONS"]


def test_length_limits():
    with pytest.raises(ValidationError):
        wt.build_components(body="x" * 1025)
    with pytest.raises(ValidationError):
        wt.build_components(body="ok", header_text="h" * 61)
    with pytest.raises(ValidationError):
        wt.build_components(body="ok", footer="f" * 61)
    with pytest.raises(ValidationError, match="footer cannot carry"):
        wt.build_components(body="ok", footer="hi {{1}}")


def test_button_rules():
    ok = [{"type": "URL", "text": "Track", "url": "https://x.co/t/{{1}}", "example": "123"}]
    assert wt.build_components(body="ok", buttons=ok)[-1]["buttons"][0]["example"] == ["123"]
    with pytest.raises(ValidationError, match="https"):
        wt.build_components(
            body="ok", buttons=[{"type": "URL", "text": "Go", "url": "http://x.co"}]
        )
    with pytest.raises(ValidationError, match="end with"):
        wt.build_components(
            body="ok", buttons=[{"type": "URL", "text": "Go", "url": "https://x.co/{{1}}/y"}]
        )
    with pytest.raises(ValidationError, match="at most 2 URL"):
        wt.build_components(
            body="ok",
            buttons=[{"type": "URL", "text": f"L{i}", "url": "https://x.co"} for i in range(3)],
        )
    with pytest.raises(ValidationError, match="phone"):
        wt.build_components(
            body="ok", buttons=[{"type": "PHONE_NUMBER", "text": "Call", "phone_number": "abc"}]
        )
    with pytest.raises(ValidationError, match="at most 10"):
        wt.build_components(
            body="ok", buttons=[{"type": "QUICK_REPLY", "text": f"b{i}"} for i in range(11)]
        )


def test_meta_status_mapping_never_invents_sendable():
    assert wt.our_status("APPROVED") == "approved"
    assert wt.our_status("rejected") == "rejected"
    assert wt.our_status("PENDING") == "submitted"
    assert wt.our_status("FLAGGED") is None  # unknown stays unknown, never "approved"
    assert wt.our_status(None) is None


# ------------------------------------------------------------------- HTTP calls


async def test_create_posts_to_the_waba_with_validated_payload():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": "9001", "status": "PENDING", "category": "UTILITY"})

    out = await wt.whatsapp_template_client.create(
        CREDS,
        name="order_ready",
        language="ar",
        category="utility",
        components=wt.build_components(body="جاهز"),
        _client=_client(handler),
    )
    assert out["id"] == "9001"
    assert seen["url"].endswith("/555/message_templates")
    assert seen["auth"] == "Bearer tok"
    assert seen["body"]["category"] == "UTILITY"
    assert seen["body"]["name"] == "order_ready"


async def test_create_refuses_a_bad_category_without_calling_meta():
    called = False

    def handler(req):
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    with pytest.raises(ValidationError):
        await wt.whatsapp_template_client.create(
            CREDS,
            name="x",
            language="ar",
            category="PROMO",
            components=[],
            _client=_client(handler),
        )
    assert called is False


async def test_missing_waba_id_says_to_reconnect():
    with pytest.raises(ExternalProviderError, match="reconnect"):
        await wt.whatsapp_template_client.list({"access_token": "t"})


async def test_meta_error_is_surfaced():
    def handler(req):
        return httpx.Response(400, json={"error": {"message": "Invalid parameter"}})

    with pytest.raises(ExternalProviderError, match="Invalid parameter"):
        await wt.whatsapp_template_client.create(
            CREDS,
            name="x",
            language="ar",
            category="UTILITY",
            components=wt.build_components(body="ok"),
            _client=_client(handler),
        )


async def test_a_200_without_an_id_is_a_failure():
    def handler(req):
        return httpx.Response(200, json={"status": "PENDING"})

    with pytest.raises(ExternalProviderError, match="no id"):
        await wt.whatsapp_template_client.create(
            CREDS,
            name="x",
            language="ar",
            category="UTILITY",
            components=wt.build_components(body="ok"),
            _client=_client(handler),
        )


async def test_list_follows_every_page():
    pages = {
        "first": {
            "data": [{"id": "1", "name": "a", "status": "APPROVED"}],
            "paging": {"next": "https://graph.facebook.com/v27.0/555/message_templates?after=B"},
        },
        "second": {"data": [{"id": "2", "name": "b", "status": "PENDING"}]},
    }
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(200, json=pages["second" if "after=B" in str(req.url) else "first"])

    items = await wt.whatsapp_template_client.list(CREDS, _client=_client(handler))
    assert [i["id"] for i in items] == ["1", "2"]
    assert len(calls) == 2


async def test_delete_by_name_requires_success_true():
    def ok(req):
        assert req.method == "DELETE"
        assert req.url.params["name"] == "order_ready"
        return httpx.Response(200, json={"success": True})

    await wt.whatsapp_template_client.delete(CREDS, name="order_ready", _client=_client(ok))

    def refused(req):
        return httpx.Response(200, json={"success": False})

    with pytest.raises(ExternalProviderError, match="refused"):
        await wt.whatsapp_template_client.delete(
            CREDS, name="order_ready", _client=_client(refused)
        )
