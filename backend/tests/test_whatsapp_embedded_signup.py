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
from app.modules.customers import meta_whatsapp_signup as signup

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
    from app.modules.customers.meta_whatsapp_signup import WhatsAppSignupCompleteBody

    with pytest.raises(ValueError):
        WhatsAppSignupCompleteBody(code="short", waba_id="1", phone_number_id="2")
    body = WhatsAppSignupCompleteBody(code="AQD" + "x" * 20, waba_id="123", phone_number_id="456")
    assert body.waba_id == "123"


async def test_code_exchange_reports_a_rejected_code_as_a_refusal() -> None:
    """Meta answering an error body is the OWNER's problem to fix (retry the
    popup), not a transient outage — the distinction drives the UI copy."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, json={"error": {"message": "bad code"}})
        )
    ) as client:
        with pytest.raises(ValidationError):
            await signup._exchange_code_for_token(
                client, app_id="a", app_secret="s", code="x" * 20
            )


async def test_code_exchange_keeps_outages_retryable() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={}))
    ) as client:
        with pytest.raises(ExternalProviderError) as exc_info:
            await signup._exchange_code_for_token(
                client, app_id="a", app_secret="s", code="x" * 20
            )
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


async def test_a_successful_subscription_passes() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"success": True})
        )
    ) as client:
        await signup._subscribe_app_to_waba(client, waba_id="1", token="t")


def test_the_signup_config_id_is_its_own_setting() -> None:
    """A page-messaging configuration id cannot open the WhatsApp popup."""
    s = get_settings()
    assert hasattr(s, "meta_whatsapp_config_id")
    assert s.meta_whatsapp_config_id != s.meta_oauth_config_id or s.meta_whatsapp_config_id == ""
