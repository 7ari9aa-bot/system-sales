"""The channel connection layer — one spec per channel, one registry.

Pins the invariants the settings screen and the webhook dispatcher both lean on:

* every connectable channel has a spec with Arabic display metadata;
* the connect endpoint's provider Literal matches the registry (drift guard);
* verification dispatches per provider with the ORIGINAL exception semantics
  (ExternalProviderError vs ValidationError — the router maps them differently);
* the Facebook channel is end-to-end: spec → adapter → webhook route → policy.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.errors import ExternalProviderError, ValidationError
from app.modules.conversations.gateway.registry import ADAPTERS, get_adapter
from app.modules.conversations.policy import policy_for
from app.modules.platform.channel_specs.registry import (
    CONNECTION_SPECS,
    get_connection_spec,
    list_connection_specs,
)

_META_OK = {"id": "111", "name": "The Store"}


def _meta_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_every_connectable_channel_has_an_organized_spec() -> None:
    """One file per channel; the registry carries them all, in owner order."""
    names = [spec.name for spec in list_connection_specs()]
    assert names == ["whatsapp", "facebook", "messenger", "instagram", "telegram", "webchat"]
    for spec in CONNECTION_SPECS.values():
        assert spec.display_name, f"{spec.name} lacks an Arabic display name"
        assert spec.identity_field, f"{spec.name} lacks its tenant-resolution key"
        assert spec.setup_notes, f"{spec.name} lacks webhook setup notes"


def test_the_schema_provider_literal_matches_the_registry() -> None:
    """Drift guard: a channel added to the specs MUST reach the connect API."""
    from app.modules.customers.schemas import IntegrationConnectBody

    allowed = set(
        IntegrationConnectBody.model_fields["provider"].annotation.__args__  # type: ignore[attr-defined]
    )
    assert allowed == set(CONNECTION_SPECS)


def test_the_message_adapter_registry_matches_the_connection_registry() -> None:
    """A connectable channel with a webhook must have a message adapter."""
    for name in CONNECTION_SPECS:
        if name == "webchat":
            continue  # webchat messages do not arrive through provider webhooks
        assert get_adapter(name) is not None, f"{name} connects but cannot message"
    assert "facebook" in ADAPTERS


def test_field_allow_lists_are_derived_not_duplicated() -> None:
    from app.modules.customers.router import _CHANNEL_CONFIG_FIELDS, _CHANNEL_CREDENTIAL_FIELDS

    assert _CHANNEL_CREDENTIAL_FIELDS["whatsapp"] == frozenset({"access_token"})
    assert _CHANNEL_CREDENTIAL_FIELDS["facebook"] == frozenset({"page_access_token"})
    assert _CHANNEL_CONFIG_FIELDS["whatsapp"] == frozenset({"phone_number_id"})
    assert set(_CHANNEL_CREDENTIAL_FIELDS) == set(CONNECTION_SPECS)
    assert set(_CHANNEL_CONFIG_FIELDS) == set(CONNECTION_SPECS)


async def test_facebook_verification_rejects_a_mismatched_page_id() -> None:
    spec = get_connection_spec("facebook")
    assert spec is not None

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v26.0/999"
        return httpx.Response(200, json={"id": "111", "name": "Other Page"})

    async with _meta_client(handler) as client:
        with pytest.raises(ValidationError, match="does not match"):
            await spec.verify({"page_access_token": "EAAG"}, {"page_id": "999"}, client=client)


async def test_facebook_verification_returns_safe_identity() -> None:
    spec = get_connection_spec("facebook")
    assert spec is not None

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer EAAG"
        return httpx.Response(200, json={"id": "111", "name": "The Store"})

    async with _meta_client(handler) as client:
        verified = await spec.verify(
            {"page_access_token": "EAAG"}, {"page_id": "111"}, client=client
        )
    assert verified.identity_config == {"account_id": "111"}
    assert verified.display_name == "The Store"


async def test_graph_outage_is_retryable_not_a_credential_refusal() -> None:
    """429/5xx must stay ExternalProviderError(retryable) — the settings UI
    offers a retry; it must NOT claim the credentials are wrong."""
    spec = get_connection_spec("whatsapp")
    assert spec is not None

    async with _meta_client(lambda request: httpx.Response(500, json={"error": "boom"})) as client:
        with pytest.raises(ExternalProviderError) as exc_info:
            await spec.verify({"access_token": "t"}, {"phone_number_id": "1"}, client=client)
    assert exc_info.value.retryable is True


async def test_unsupported_provider_fails_the_same_way_as_before() -> None:
    from app.modules.platform.integration_verifier import verify_channel_credentials

    with pytest.raises(ValidationError, match="not supported"):
        await verify_channel_credentials("pigeon", {}, {})


def test_facebook_messaging_policy_mirrors_messenger() -> None:
    """A Facebook page has Meta's 24h window and supports templates."""
    fb = policy_for("facebook")
    ms = policy_for("messenger")
    assert fb.window_hours == ms.window_hours == 24
    assert fb.supports_templates is True


def test_the_webhook_route_accepts_facebook() -> None:
    """The generic /webhooks/{channel} dispatcher must admit the new channel.

    The route path is parametrized, so the honest check is the guard SET the
    dispatcher consults plus the route's presence in the app schema.
    """
    from app.main import create_app
    from app.modules.conversations.router import _WEBHOOK_CHANNELS

    assert "facebook" in _WEBHOOK_CHANNELS
    assert "/api/v1/webhooks/{channel}" in create_app().openapi()["paths"]


def test_facebook_adapter_reuses_the_meta_parsing() -> None:
    """A Messenger-style payload parses identically under the facebook name."""
    adapter = get_adapter("facebook")
    assert adapter is not None
    payload = {
        "entry": [
            {
                "id": "111",
                "messaging": [
                    {
                        "sender": {"id": "customer-1"},
                        "recipient": {"id": "111"},
                        "message": {"mid": "m.fb.1", "text": "عايز أعرف السعر"},
                    }
                ],
            }
        ]
    }
    assert adapter.resolve_tenant_key(payload) == "111"
    messages = adapter.parse_inbound(payload)
    assert len(messages) == 1
    assert messages[0].channel == "facebook"
    assert messages[0].body == "عايز أعرف السعر"
