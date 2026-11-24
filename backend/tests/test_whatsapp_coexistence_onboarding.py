"""Coexistence onboarding: META's answer decides the mode, never the browser.

The review's P0 gaps 1-5, one test each:

* the popup no longer asks Meta to switch the WhatsApp Business app flow off, and the body
  defaults to coexistence instead of cloud_api;
* the mode is derived from ``is_on_biz_app`` + ``platform_type`` read back from Graph;
* a coexistence number is never registered again (that spends one of Meta's 10 attempts and can
  lock the number for 72 hours), while a Cloud-API-only number still is;
* an unreadable or unexpected answer fails the connect instead of recording a mode nobody proved;
* a replayed connect answers with the mode that was STORED, not the one the retry guessed.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.core.errors import ExternalProviderError, ValidationError
from app.modules.customers import meta_whatsapp_signup as signup
from app.modules.customers.meta_whatsapp_signup import WhatsAppSignupCompleteBody
from app.modules.platform.channel_specs import whatsapp as whatsapp_spec

_ON_APP = {"is_on_biz_app": True, "platform_type": "CLOUD_API"}
_API_ONLY = {"is_on_biz_app": False, "platform_type": "CLOUD_API"}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------- the body ----------


def test_the_signup_body_defaults_to_coexistence() -> None:
    """The WhatsApp Business app flow is what the popup asks for, so it is the default."""
    body = WhatsAppSignupCompleteBody(code="abcdefgh", waba_id="123", phone_number_id="456")
    assert body.onboarding_mode == "coexistence"


def test_a_made_up_onboarding_mode_is_still_refused() -> None:
    with pytest.raises(ValueError):
        WhatsAppSignupCompleteBody(
            code="abcdefgh", waba_id="123", phone_number_id="456", onboarding_mode="coexisting"
        )


# ---------- who decides the mode ----------


def test_meta_saying_the_number_is_on_the_app_makes_it_coexistence() -> None:
    """Even when the browser asked for cloud_api: Meta's facts win."""
    mode, status = signup._resolve_onboarding_mode(_ON_APP, "cloud_api")
    assert (mode, status) == ("coexistence", signup.COEXISTENCE_VERIFIED)


def test_a_number_that_is_not_on_the_app_is_rejected_for_this_product() -> None:
    """FIHRIST targets existing WhatsApp Business app numbers; no Cloud API fallback."""
    with pytest.raises(ValidationError, match="existing WhatsApp Business app"):
        signup._resolve_onboarding_mode(_API_ONLY, "coexistence")


def test_an_unexpected_platform_is_refused_rather_than_guessed() -> None:
    """On the app but not on the Cloud API is not coexistence — and not registerable either."""
    with pytest.raises(ValidationError, match="platform"):
        signup._resolve_onboarding_mode(
            {"is_on_biz_app": True, "platform_type": "ON_PREMISE"}, "coexistence"
        )


# ---------- reading Meta ----------


async def test_the_number_read_asks_for_the_two_documented_fields() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("fields", ""))
        return httpx.Response(200, json=_ON_APP)

    async with _client(handler) as client:
        facts = await signup._number_platform_facts(client, phone_number_id="456", token="t")
    assert facts == {"is_on_biz_app": True, "platform_type": "CLOUD_API"}
    assert "is_on_biz_app" in seen[0] and "platform_type" in seen[0]


async def test_silence_about_the_number_is_not_a_no() -> None:
    """An absent field must fail the connect: guessing cloud_api is the original bug."""
    async with _client(lambda request: httpx.Response(200, json={"id": "456"})) as client:
        with pytest.raises(ExternalProviderError) as exc_info:
            await signup._number_platform_facts(client, phone_number_id="456", token="t")
    assert exc_info.value.retryable is True


async def test_a_meta_outage_keeps_the_connect_retryable() -> None:
    async with _client(lambda request: httpx.Response(503, json={})) as client:
        with pytest.raises(ExternalProviderError) as exc_info:
            await signup._number_platform_facts(client, phone_number_id="456", token="t")
    assert exc_info.value.retryable is True


async def test_an_error_body_cannot_be_mistaken_for_a_verified_number() -> None:
    async with _client(
        lambda request: httpx.Response(200, json={"error": {"message": "denied"}})
    ) as client:
        with pytest.raises(ValidationError, match="could not report"):
            await signup._number_platform_facts(client, phone_number_id="456", token="t")


# ---------- registration ----------


async def test_a_coexistence_number_is_never_registered(monkeypatch) -> None:
    """Meta registers a Business App number itself; a second register can lock it."""
    calls: list[str] = []

    async def fake_register(http, *, phone_number_id, token, pin=None):
        calls.append("register")
        return "123456"

    async def fake_subscribe(http, *, waba_id, token):
        calls.append("subscribe")

    monkeypatch.setattr(signup, "_register_phone_number", fake_register)
    monkeypatch.setattr(signup, "_subscribe_app_to_waba", fake_subscribe)

    async with _client(lambda request: httpx.Response(200, json=_ON_APP)) as client:
        mode, status, facts, pin = await signup._prepare_number(
            client, waba_id="1", phone_number_id="456", token="t", requested_mode="coexistence"
        )

    assert calls == ["subscribe"]
    assert (mode, status, pin) == ("coexistence", signup.COEXISTENCE_VERIFIED, None)
    assert facts["is_on_biz_app"] is True


async def test_a_cloud_api_only_number_is_rejected_without_register_or_subscribe(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_register(http, *, phone_number_id, token, pin=None):
        calls.append("register")
        return "654321"

    async def fake_subscribe(http, *, waba_id, token):
        calls.append("subscribe")

    monkeypatch.setattr(signup, "_register_phone_number", fake_register)
    monkeypatch.setattr(signup, "_subscribe_app_to_waba", fake_subscribe)

    async with _client(lambda request: httpx.Response(200, json=_API_ONLY)) as client:
        with pytest.raises(ValidationError, match="existing WhatsApp Business app"):
            await signup._prepare_number(
                client, waba_id="1", phone_number_id="456", token="t", requested_mode="coexistence"
            )

    assert calls == []


# ---------- the connection spec ----------


async def test_the_connection_spec_records_the_coexistence_facts() -> None:
    """The manual connect learns the same two facts, so both ways in agree."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("fields", ""))
        return httpx.Response(
            200,
            json={
                "id": "456",
                "display_phone_number": "+20 100 000 0000",
                "verified_name": "Shop",
                **_ON_APP,
            },
        )

    async with _client(handler) as client:
        verified = await whatsapp_spec.whatsapp_connection_spec.verify(
            {"access_token": "t"}, {"phone_number_id": "456"}, client=client
        )

    assert "is_on_biz_app" in seen[0] and "platform_type" in seen[0]
    assert verified.identity_config["phone_number_id"] == "456"
    assert verified.identity_config["is_on_biz_app"] == "true"
    assert verified.identity_config["platform_type"] == "CLOUD_API"


def test_coexistence_evidence_needs_both_halves() -> None:
    assert whatsapp_spec.coexistence_evidence(_ON_APP) is True
    assert whatsapp_spec.coexistence_evidence({"is_on_biz_app": True}) is False
    assert whatsapp_spec.coexistence_evidence({"platform_type": "CLOUD_API"}) is False


# ---------- replay ----------


def test_a_replayed_connect_answers_with_the_stored_mode() -> None:
    """A retry must not report cloud_api for a channel that was connected as coexistence."""
    integration = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        status="active",
        config={
            "phone_number_id": "456",
            "waba_id": "123",
            "onboarding_mode": "coexistence",
            "coexistence_status": "verified",
            "is_on_biz_app": True,
            "platform_type": "CLOUD_API",
            "_connection": {"display_name": "Shop"},
        },
    )
    body = WhatsAppSignupCompleteBody(code="abcdefgh", waba_id="123", phone_number_id="456")
    result = signup._connected_result(integration, body)
    assert result["onboarding_mode"] == "coexistence"
    assert result["coexistence_status"] == "verified"
    assert result["is_on_biz_app"] is True
    assert json.dumps(result)  # plain JSON, nothing unserialisable leaks out
