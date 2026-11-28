"""WhatsApp Embedded Signup — the click-to-connect flow (DB-free guards).

The owner's requirement: press the WhatsApp icon, Meta's own window opens,
the store owner signs in with THEIR Meta account, and the number lands
connected in our system. These tests pin the server half of that contract:

* both routes are mounted and reachable;
* the start route fails LOUDLY when the console setup is missing (an
  operator must hear which env var), and never leaks the app secret;
* the completion payload is validated before any provider call;
* the WABA subscription is not optional — an unsubscribed WABA receives
  nothing, so a refused subscription must fail the connect.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import get_settings
from app.core.errors import ExternalProviderError, ValidationError
from app.applications.apparel.modules.customers import meta_whatsapp_signup as signup

_START = "/api/v1/integrations/whatsapp/embedded-signup/start"
_COMPLETE = "/api/v1/integrations/whatsapp/embedded-signup/complete"


def test_both_routes_are_mounted() -> None:
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    assert _START in paths
    assert _COMPLETE in paths


def test_start_refuses_loudly_when_unconfigured(monkeypatch) -> None:
    """The operator must hear WHICH var is missing, not Meta's cryptic error."""
    monkeypatch.setattr(
        signup,
        "get_settings",
        lambda: type(
            "S",
            (),
            {"meta_app_id": "app", "meta_app_secret": "secret", "meta_whatsapp_config_id": ""},
        )(),
    )
    with pytest.raises(ValidationError, match="META_WHATSAPP_CONFIG_ID"):
        signup._whatsapp_config()


def test_completion_payload_is_validated_before_any_provider_call() -> None:
    from app.applications.apparel.modules.customers.meta_whatsapp_signup import WhatsAppSignupCompleteBody

    with pytest.raises(ValueError):
        WhatsAppSignupCompleteBody(code="short", waba_id="1", phone_number_id="2")
    body = WhatsAppSignupCompleteBody(code="AQD" + "x" * 20, waba_id="123", phone_number_id="456")
    assert body.waba_id == "123"
    with pytest.raises(ValueError):
        WhatsAppSignupCompleteBody(code="AQD" + "x" * 20, waba_id="../../me", phone_number_id="456")


async def test_code_exchange_reports_a_rejected_code_as_a_refusal() -> None:
    """Meta answering an error body is the OWNER's problem to fix (retry the
    popup), not a transient outage — the distinction drives the UI copy."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, json={"error": {"message": "bad code"}})
        )
    ) as client:
        with pytest.raises(ValidationError):
            await signup._exchange_code_for_token(client, app_id="a", app_secret="s", code="x" * 20)


async def test_code_exchange_keeps_outages_retryable() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={}))
    ) as client:
        with pytest.raises(ExternalProviderError) as exc_info:
            await signup._exchange_code_for_token(client, app_id="a", app_secret="s", code="x" * 20)
    assert exc_info.value.retryable is True


async def test_a_refused_waba_subscription_fails_the_connect() -> None:
    """Connecting a number that can never receive is worse than failing."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, json={"error": {"message": "no permission"}})
        )
    ) as client:
        with pytest.raises(ExternalProviderError, match="webhook subscription"):
            await signup._subscribe_app_to_waba(client, waba_id="1", token="t")


async def test_a_graph_error_body_cannot_be_mistaken_for_a_successful_subscription() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"error": {"message": "denied"}})
        )
    ) as client:
        with pytest.raises(ExternalProviderError, match="webhook subscription"):
            await signup._subscribe_app_to_waba(client, waba_id="1", token="t")


async def test_a_successful_subscription_passes() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"success": True}))
    ) as client:
        await signup._subscribe_app_to_waba(client, waba_id="1", token="t")


async def test_signup_rejects_a_phone_number_from_a_different_waba() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": [{"id": "other-phone"}]})
        )
    ) as client:
        with pytest.raises(ValidationError, match="does not belong"):
            await signup._verify_phone_belongs_to_waba(
                client, waba_id="123", phone_number_id="456", token="t"
            )


async def test_signup_accepts_a_phone_number_in_its_selected_waba() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": [{"id": "456"}]})
        )
    ) as client:
        await signup._verify_phone_belongs_to_waba(
            client, waba_id="123", phone_number_id="456", token="t"
        )


async def test_signup_searches_paginated_phone_number_lists() -> None:
    calls = 0

    def respond(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "first-page-phone"}],
                    "paging": {
                        "next": "https://graph.facebook.com/next",
                        "cursors": {"after": "cursor"},
                    },
                },
            )
        return httpx.Response(200, json={"data": [{"id": "456"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await signup._verify_phone_belongs_to_waba(
            client, waba_id="123", phone_number_id="456", token="t"
        )
    assert calls == 2


async def test_phone_membership_does_not_accept_a_redirect_body_as_success() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(302, json={"data": [{"id": "456"}]})
        )
    ) as client:
        with pytest.raises(ValidationError):
            await signup._verify_phone_belongs_to_waba(
                client, waba_id="123", phone_number_id="456", token="t"
            )


def test_the_signup_config_id_is_its_own_setting() -> None:
    """A page-messaging configuration id cannot open the WhatsApp popup."""
    s = get_settings()
    assert hasattr(s, "meta_whatsapp_config_id")
    assert (
        s.meta_whatsapp_config_id != s.meta_instagram_config_id or s.meta_whatsapp_config_id == ""
    )


# --- registering the number: Meta only lets a REGISTERED number send and receive -----------------


def _meta(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_an_unregistered_number_is_registered_with_a_six_digit_pin() -> None:
    """A number not CONNECTED yet is registered; the PIN we set is handed back to be kept."""
    calls: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = {} if request.method == "GET" else __import__("json").loads(request.content)
        calls.append((request.method, request.url.path, body))
        if request.method == "GET":
            return httpx.Response(200, json={"status": "PENDING"})
        return httpx.Response(200, json={"success": True})

    async with _meta(handler) as client:
        pin = await signup._register_phone_number(client, phone_number_id="555", token="t")

    assert pin is not None and len(pin) == 6 and pin.isdigit()
    method, path, body = calls[-1]
    assert (method, path.endswith("/555/register")) == ("POST", True)
    assert body == {"messaging_product": "whatsapp", "pin": pin}


async def test_a_number_that_is_already_connected_is_not_registered_again() -> None:
    """Registering again burns one of Meta's 10 attempts per 72 hours for a working number."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        return httpx.Response(200, json={"status": "CONNECTED"})

    async with _meta(handler) as client:
        pin = await signup._register_phone_number(client, phone_number_id="555", token="t")

    assert pin is None
    assert seen == ["GET"], "a CONNECTED number must not be POSTed to /register"


async def test_the_pin_is_random_not_a_constant() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status": "PENDING"})
        return httpx.Response(200, json={"success": True})

    async with _meta(handler) as client:
        pins = {
            await signup._register_phone_number(client, phone_number_id="5", token="t")
            for _ in range(8)
        }
    assert len(pins) > 1


async def test_the_72_hour_attempt_limit_is_reported_and_not_retried() -> None:
    """Error 133016 locks the number for 72 hours: say so, and never loop on it."""
    posts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.method == "GET":
            return httpx.Response(200, json={"status": "PENDING"})
        posts += 1
        return httpx.Response(400, json={"error": {"code": 133016, "message": "limit"}})

    async with _meta(handler) as client:
        with pytest.raises(ExternalProviderError, match="72 hours") as exc_info:
            await signup._register_phone_number(client, phone_number_id="5", token="t")
    assert exc_info.value.retryable is False
    assert posts == 1


async def test_any_other_refusal_fails_the_connect_instead_of_storing_a_dead_number() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status": "PENDING"})
        return httpx.Response(400, json={"error": {"code": 100, "message": "nope"}})

    async with _meta(handler) as client:
        with pytest.raises(ExternalProviderError, match="refused to register"):
            await signup._register_phone_number(client, phone_number_id="5", token="t")


async def test_an_unreachable_meta_is_a_clear_error_not_a_stack_trace() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status": "PENDING"})
        raise httpx.ConnectError("down")

    async with _meta(handler) as client:
        with pytest.raises(ExternalProviderError, match="Could not reach Meta"):
            await signup._register_phone_number(client, phone_number_id="5", token="t")


async def test_a_network_failure_reading_the_display_name_does_not_fail_the_signup() -> None:
    """The name is cosmetic; the owner already finished Meta's popup."""
    import httpx

    from app.applications.apparel.modules.customers.meta_whatsapp_signup import _phone_display_name

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as http:
        assert await _phone_display_name(http, phone_number_id="1", token="t") is None
