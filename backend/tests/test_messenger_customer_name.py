"""A Messenger customer shows with a name, not a number, and a failed lookup loses nothing.

The webhook carries only the page-scoped id, so ``customer_name`` was always None. The name comes
from Graph ``/{psid}?fields=name,profile_pic`` with the Page token. Meta may refuse, so every
failure means "no name" and the message is still ingested.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.modules.conversations.gateway.base import InboundMessage
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.messenger import messenger_adapter

TENANT = uuid.uuid4()


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ------------------------------------------------------------------ the adapter call


async def test_the_name_and_picture_come_from_graph_with_the_page_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"name": "Sara Ahmed", "profile_pic": "https://p/1.jpg"})

    async with _client(handler) as http:
        profile = await messenger_adapter.fetch_profile(
            {"api_key": "PAGE-TOKEN"}, "PSID-1", _client=http
        )
    assert profile == {"name": "Sara Ahmed", "profile_pic": "https://p/1.jpg"}
    [req] = seen
    assert req.url.path.endswith("/PSID-1")
    assert req.url.params["fields"] == "name,profile_pic"
    assert req.headers["authorization"] == "Bearer PAGE-TOKEN"
    assert "access_token" not in req.url.params  # the token never rides in the URL


async def test_a_page_token_under_the_facebook_key_works_too() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "Omar"})

    async with _client(handler) as http:
        profile = await messenger_adapter.fetch_profile(
            {"page_access_token": "T"}, "P", _client=http
        )
    assert profile == {"name": "Omar"}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"error": {"code": 100}}),
        httpx.Response(403, json={"error": {"code": 10}}),
        httpx.Response(429, json={}),
        httpx.Response(500, text="oops"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"name": "   "}),
        httpx.Response(200, json=["not", "a", "dict"]),
        httpx.Response(200, text="not json"),
    ],
)
async def test_every_refusal_or_oddity_is_just_no_name(response) -> None:
    async with _client(lambda request: response) as http:
        assert await messenger_adapter.fetch_profile({"api_key": "T"}, "P", _client=http) is None


async def test_a_network_failure_is_just_no_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with _client(handler) as http:
        assert await messenger_adapter.fetch_profile({"api_key": "T"}, "P", _client=http) is None


@pytest.mark.parametrize(("credentials", "psid"), [({}, "P"), ({"api_key": "T"}, ""), (None, "P")])
async def test_no_token_or_no_id_makes_no_call(credentials, psid) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no Graph call expected")

    async with _client(handler) as http:
        assert await messenger_adapter.fetch_profile(credentials, psid, _client=http) is None


# ------------------------------------------------------------------ the enrichment step


class _Redis:
    def __init__(self, initial=None):
        self.store = dict(initial or {})
        self.sets: list[tuple[str, str, int]] = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        self.sets.append((key, value, ex))


class _Adapter:
    def __init__(self, profiles=None, boom=False):
        self.profiles = profiles or {}
        self.boom = boom
        self.calls: list[str] = []

    async def fetch_profile(self, credentials, psid):
        self.calls.append(psid)
        if self.boom:
            raise RuntimeError("meta exploded")
        return self.profiles.get(psid)


def _msg(ref="U1", name=None) -> InboundMessage:
    return InboundMessage(
        channel="messenger",
        channel_message_id=f"m-{uuid.uuid4()}",
        customer_ref=ref,
        customer_name=name,
    )


@pytest.fixture
def wiring(monkeypatch):
    redis = _Redis()
    creds = {"api_key": "T"}

    async def credentials(session, tenant_id, provider):
        return creds

    monkeypatch.setattr("app.core.redis.get_redis_or_none", lambda: redis)
    monkeypatch.setattr(
        "app.modules.platform.services.channel_access.channel_credentials_config", credentials
    )
    return redis


async def _fill(adapter, messages):
    await IngestService.fill_customer_names(
        None, tenant_id=TENANT, adapter=adapter, channel="messenger", messages=messages
    )


async def test_a_nameless_sender_gets_their_name(wiring) -> None:
    adapter = _Adapter({"U1": {"name": "Sara"}})
    messages = [_msg("U1")]
    await _fill(adapter, messages)
    assert messages[0].customer_name == "Sara"


async def test_one_lookup_serves_every_message_from_that_sender(wiring) -> None:
    adapter = _Adapter({"U1": {"name": "Sara"}})
    messages = [_msg("U1"), _msg("U1"), _msg("U1")]
    await _fill(adapter, messages)
    assert adapter.calls == ["U1"]
    assert {m.customer_name for m in messages} == {"Sara"}


async def test_a_second_delivery_uses_the_cache_not_graph(wiring) -> None:
    adapter = _Adapter({"U1": {"name": "Sara"}})
    await _fill(adapter, [_msg("U1")])
    again = [_msg("U1")]
    await _fill(adapter, again)
    assert adapter.calls == ["U1"]  # still one call
    assert again[0].customer_name == "Sara"


async def test_a_sender_Meta_will_not_name_is_remembered_for_a_shorter_time(wiring) -> None:
    adapter = _Adapter({})
    await _fill(adapter, [_msg("U9")])
    await _fill(adapter, [_msg("U9")])
    assert adapter.calls == ["U9"]  # the refusal is cached too: no retry on every message
    [(_, value, ttl)] = wiring.sets
    assert value == ""
    assert ttl == IngestService._NO_PROFILE_TTL_SECONDS < IngestService._PROFILE_TTL_SECONDS


async def test_a_name_the_webhook_already_gave_is_not_looked_up(wiring) -> None:
    adapter = _Adapter({"U1": {"name": "Other"}})
    messages = [_msg("U1", name="Already Named")]
    await _fill(adapter, messages)
    assert adapter.calls == []
    assert messages[0].customer_name == "Already Named"


async def test_two_senders_are_looked_up_separately(wiring) -> None:
    adapter = _Adapter({"U1": {"name": "A"}, "U2": {"name": "B"}})
    messages = [_msg("U1"), _msg("U2")]
    await _fill(adapter, messages)
    assert [m.customer_name for m in messages] == ["A", "B"]


async def test_a_lookup_that_explodes_never_loses_the_message(wiring) -> None:
    adapter = _Adapter(boom=True)
    messages = [_msg("U1")]
    await _fill(adapter, messages)  # must not raise
    assert messages[0].customer_name is None


async def test_an_adapter_without_profiles_is_untouched(wiring) -> None:
    class Plain:
        pass

    messages = [_msg("U1")]
    await _fill(Plain(), messages)
    assert messages[0].customer_name is None


async def test_a_disconnected_channel_means_no_lookup(monkeypatch) -> None:
    async def none(session, tenant_id, provider):
        return None

    monkeypatch.setattr("app.core.redis.get_redis_or_none", lambda: _Redis())
    monkeypatch.setattr(
        "app.modules.platform.services.channel_access.channel_credentials_config", none
    )
    adapter = _Adapter({"U1": {"name": "Sara"}})
    messages = [_msg("U1")]
    await _fill(adapter, messages)
    assert adapter.calls == []
    assert messages[0].customer_name is None


async def test_no_redis_still_works(monkeypatch) -> None:
    async def credentials(session, tenant_id, provider):
        return {"api_key": "T"}

    monkeypatch.setattr("app.core.redis.get_redis_or_none", lambda: None)
    monkeypatch.setattr(
        "app.modules.platform.services.channel_access.channel_credentials_config", credentials
    )
    adapter = _Adapter({"U1": {"name": "Sara"}})
    messages = [_msg("U1")]
    await _fill(adapter, messages)
    assert messages[0].customer_name == "Sara"


def test_only_messenger_can_look_a_person_up() -> None:
    from app.modules.conversations.gateway.instagram import instagram_adapter
    from app.modules.conversations.gateway.whatsapp import whatsapp_adapter

    assert callable(getattr(messenger_adapter, "fetch_profile", None))
    assert not hasattr(whatsapp_adapter, "fetch_profile")
    assert not hasattr(instagram_adapter, "fetch_profile")
