"""A Messenger thread starts as a page-scoped number; this turns it into a name and a face.

The read is Meta's GET /{psid}?fields=name,profile_pic. It can be refused — someone who has not
messaged the page has not consented — and a refusal must leave the number in place and never
break the message that triggered the enrichment.
"""

from __future__ import annotations

import uuid

import httpx

from app.applications.apparel.modules.conversations.gateway.base import ProviderCredentials
from app.applications.apparel.modules.conversations.gateway.messenger import messenger_adapter

CREDS = ProviderCredentials(config={"api_key": "PAGE-TOKEN"})


def _client(payload, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/PSID-1")
        assert request.url.params.get("fields") == "name,profile_pic"
        assert request.url.params.get("access_token") == "PAGE-TOKEN"
        return httpx.Response(status, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_a_name_and_a_photo_come_back_for_a_psid():
    profile = await messenger_adapter.get_user_profile(
        CREDS,
        "PSID-1",
        _client({"name": "Hamed Adel", "profile_pic": "https://cdn.example/p.jpg"}),
    )
    assert profile == {"name": "Hamed Adel", "profile_pic": "https://cdn.example/p.jpg"}


async def test_a_refusal_is_none_not_an_exception():
    profile = await messenger_adapter.get_user_profile(
        CREDS, "PSID-1", _client({"error": {"message": "(#200) not allowed"}}, status=403)
    )
    assert profile is None


async def test_an_empty_answer_is_none():
    assert await messenger_adapter.get_user_profile(CREDS, "PSID-1", _client({})) is None


async def test_no_token_means_no_call():
    assert (
        await messenger_adapter.get_user_profile(
            ProviderCredentials(config={}), "PSID-1", _client({"name": "x"})
        )
        is None
    )


async def test_the_service_names_the_customer_and_keeps_a_manual_name(monkeypatch):
    from app.applications.apparel.modules.conversations import customer_profile as cp

    class _Customer:
        def __init__(self, name):
            self.id = uuid.uuid4()
            self.name = name

    class _Identity:
        def __init__(self):
            self.external_id = "PSID-1"
            self.extra = {}

    class _Customers:
        def __init__(self, identity):
            self.identity = identity

        async def channel_identity(self, *_a, **_k):
            return self.identity

    identity = _Identity()
    monkeypatch.setattr(cp, "customers", lambda: _Customers(identity))

    async def _profile(_creds, _psid):
        return {"name": "Hamed Adel", "profile_pic": None}

    original = messenger_adapter.get_user_profile
    messenger_adapter.get_user_profile = _profile
    try:
        numbered = _Customer("1471701105025616")
        assert (
            await cp.CustomerProfileService.enrich_messenger(None, uuid.uuid4(), numbered, {})
            is True
        )
        assert numbered.name == "Hamed Adel"

        identity.extra = {}  # a week has not passed; the second customer is a fresh read
        named = _Customer("عميل المحل")
        assert (
            await cp.CustomerProfileService.enrich_messenger(None, uuid.uuid4(), named, {}) is True
        )
        assert named.name == "عميل المحل"  # a typed name is never overwritten
    finally:
        messenger_adapter.get_user_profile = original


async def test_a_refusal_is_recorded_so_it_is_not_retried_on_every_message(monkeypatch):
    from app.applications.apparel.modules.conversations import customer_profile as cp

    class _Customer:
        id = uuid.uuid4()
        name = "1471701105025616"

    class _Identity:
        external_id = "PSID-1"

        def __init__(self):
            self.extra = {}

    identity = _Identity()

    class _Customers:
        async def channel_identity(self, *_a, **_k):
            return identity

    monkeypatch.setattr(cp, "customers", lambda: _Customers())

    async def _none(_creds, _psid):
        return None

    original = messenger_adapter.get_user_profile
    messenger_adapter.get_user_profile = _none
    try:
        assert (
            await cp.CustomerProfileService.enrich_messenger(None, uuid.uuid4(), _Customer(), {})
            is False
        )
        assert identity.extra["profile_ok"] is False
        assert identity.extra["profile_at"]
    finally:
        messenger_adapter.get_user_profile = original
