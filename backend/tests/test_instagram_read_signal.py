"""Seen and "typing…" on the CUSTOMER's Instagram, sent as Graph sender actions.

On Instagram they are two plain sender actions, `mark_seen` when an agent opens the
chat and `typing_on` while the agent writes. They are visible to the customer, so the
rules matter: only when we have a customer message, only inside the reply window, and a
failure never blocks the agent (the route reports it as `sent: false`).
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.modules.conversations import read_signal_service as svc
from app.modules.conversations.gateway.base import ExternalProviderError, ProviderCredentials
from app.modules.conversations.gateway.instagram import InstagramAdapter
from app.modules.conversations.read_signal_service import ReadSignalService

CREDS = ProviderCredentials(config={"api_key": "tok", "account_id": "1784"})


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---- the request Meta receives (no database) -------------------------------------


@pytest.mark.parametrize("action", ["mark_seen", "typing_on", "typing_off"])
def test_a_sender_action_is_only_the_recipient_and_the_action(action: str) -> None:
    assert InstagramAdapter.build_sender_action("c1", action) == {
        "recipient": {"id": "c1"},
        "sender_action": action,
    }


def test_an_unknown_action_is_refused_before_anything_is_sent() -> None:
    with pytest.raises(ValueError):
        InstagramAdapter.build_sender_action("c1", "react")


@pytest.mark.asyncio
async def test_it_posts_to_the_account_with_the_bearer_token() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"recipient_id": "c1"})

    await InstagramAdapter().send_sender_action(CREDS, "c1", "typing_on", _client=_client(handler))
    assert seen["url"].endswith("/1784/messages")
    assert seen["auth"] == "Bearer tok"
    assert seen["json"] == {"recipient": {"id": "c1"}, "sender_action": "typing_on"}


@pytest.mark.asyncio
async def test_a_refusal_is_an_error_the_service_will_swallow() -> None:
    refused = httpx.Response(400, json={"error": {"message": "nope", "code": 100}})
    with pytest.raises(ExternalProviderError):
        await InstagramAdapter().send_sender_action(
            CREDS, "c1", "mark_seen", _client=_client(lambda r: refused)
        )


# ---- the service: when a signal goes out (fakes, no database) --------------------


class _FakeAdapter:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    async def send_sender_action(self, credentials, customer_ref, action) -> None:
        if self.fail:
            raise ExternalProviderError("down")
        self.calls.append(f"{customer_ref}:{action}")


@pytest.fixture
def wire(monkeypatch):
    """Patch the three database lookups; return the adapter that records the actions."""
    adapter = _FakeAdapter()

    async def newest(*_a, **_k):
        return state["newest"]

    async def ref(*_a, **_k):
        return state["ref"]

    state = {"newest": "mid.1", "ref": "customer-1", "allowed": True}
    monkeypatch.setattr(ReadSignalService, "latest_inbound_provider_id", staticmethod(newest))
    monkeypatch.setattr(ReadSignalService, "_customer_ref", staticmethod(ref))
    monkeypatch.setattr(svc, "get_adapter", lambda channel: adapter)
    monkeypatch.setattr(
        svc.MessagingPolicyService,
        "evaluate",
        staticmethod(lambda conversation: SimpleNamespace(allowed=state["allowed"])),
    )
    return adapter, state


def _conversation(channel: str = "instagram"):
    return SimpleNamespace(id=uuid.uuid4(), channel=channel, customer_id=uuid.uuid4())


async def _config() -> dict:
    return {"api_key": "tok", "account_id": "1784"}


async def _send(conversation, *, typing: bool, loader=_config):
    return await ReadSignalService.send(
        None, uuid.uuid4(), conversation, typing=typing, load_channel_config=loader
    )


@pytest.mark.asyncio
async def test_opening_a_chat_marks_it_seen_and_nothing_else(wire) -> None:
    adapter, _ = wire
    result = await _send(_conversation(), typing=False)
    assert result.sent is True
    assert adapter.calls == ["customer-1:mark_seen"]


@pytest.mark.asyncio
async def test_typing_adds_typing_on_after_seen(wire) -> None:
    adapter, _ = wire
    assert (await _send(_conversation(), typing=True)).sent is True
    assert adapter.calls == ["customer-1:mark_seen", "customer-1:typing_on"]


@pytest.mark.asyncio
async def test_a_closed_window_sends_nothing(wire) -> None:
    adapter, state = wire
    state["allowed"] = False
    result = await _send(_conversation(), typing=True)
    assert (result.sent, result.skipped) == (False, "window_closed")
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_no_customer_message_means_no_signal(wire) -> None:
    adapter, state = wire
    state["newest"] = None
    result = await _send(_conversation(), typing=False)
    assert (result.sent, result.skipped) == (False, "no_message")
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_a_shop_without_instagram_connected_sends_nothing(wire) -> None:
    async def nothing():
        return None

    adapter, _ = wire
    result = await _send(_conversation(), typing=False, loader=nothing)
    assert (result.sent, result.skipped) == (False, "not_connected")
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_a_chat_with_no_instagram_identity_sends_nothing(wire) -> None:
    adapter, state = wire
    state["ref"] = None
    result = await _send(_conversation(), typing=False)
    assert (result.sent, result.skipped) == (False, "no_customer")
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_a_provider_failure_is_reported_never_raised(wire, monkeypatch) -> None:
    monkeypatch.setattr(svc, "get_adapter", lambda channel: _FakeAdapter(fail=True))
    result = await _send(_conversation(), typing=True)
    assert (result.sent, result.skipped) == (False, "provider_error")


@pytest.mark.asyncio
async def test_other_channels_are_still_refused(wire) -> None:
    adapter, _ = wire
    result = await _send(_conversation("messenger"), typing=False)
    assert (result.sent, result.skipped) == (False, "channel")
    assert adapter.calls == []
