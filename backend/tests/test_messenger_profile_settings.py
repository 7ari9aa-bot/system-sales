"""Messenger Platform settings: greeting, Get Started, menu, ice breakers, labels.

Verified before building: nothing in the backend touched /me/messenger_profile at all, so none of
these settings had a lifecycle. Each test pins the exact JSON Meta documents.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.errors import ValidationError
from app.applications.apparel.modules.conversations.gateway.messenger_profile import MessengerProfile

TOKEN = "page-token"


def _record(payload: dict | None = None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload or {"result": "success"})

    return seen, httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_greeting_posts_metas_documented_shape():
    seen, transport = _record()
    async with httpx.AsyncClient(transport=transport) as http:
        await MessengerProfile().set_greeting(http, token=TOKEN, text="أهلاً بيك في المتجر")
    body = json.loads(seen[0].content)
    assert body == {"greeting": [{"locale": "default", "text": "أهلاً بيك في المتجر"}]}
    assert seen[0].url.path.endswith("/me/messenger_profile")


@pytest.mark.asyncio
async def test_get_started_and_menu_and_ice_breakers_use_their_own_fields():
    seen, transport = _record()
    profile = MessengerProfile()
    async with httpx.AsyncClient(transport=transport) as http:
        await profile.set_get_started(http, token=TOKEN)
        await profile.set_persistent_menu(
            http,
            token=TOKEN,
            items=[{"type": "postback", "title": "المنتجات", "payload": "PRODUCTS"}],
        )
        await profile.set_ice_breakers(
            http, token=TOKEN, questions=[{"question": "الشحن كام؟", "payload": "SHIPPING"}]
        )
    bodies = [json.loads(r.content) for r in seen]
    assert bodies[0] == {"get_started": {"payload": "GET_STARTED"}}
    assert bodies[1]["persistent_menu"][0]["call_to_actions"][0]["payload"] == "PRODUCTS"
    assert bodies[1]["persistent_menu"][0]["composer_input_disabled"] is False
    assert bodies[2] == {
        "ice_breakers": [
            {
                "locale": "default",
                "call_to_actions": [{"question": "الشحن كام؟", "payload": "SHIPPING"}],
            }
        ]
    }


@pytest.mark.asyncio
async def test_metas_limits_are_enforced_before_the_call():
    seen, transport = _record()
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(ValidationError):
            await MessengerProfile().set_ice_breakers(
                http,
                token=TOKEN,
                questions=[{"question": f"q{i}", "payload": "P"} for i in range(4)],
            )
        with pytest.raises(ValidationError):
            await MessengerProfile().set_persistent_menu(
                http,
                token=TOKEN,
                items=[{"type": "postback", "title": "t", "payload": "P"}] * 6,
            )
        with pytest.raises(ValidationError):
            await MessengerProfile().set_greeting(http, token=TOKEN, text="x" * 161)
    assert seen == []


@pytest.mark.asyncio
async def test_labels_go_on_the_conversation_and_removal_uses_fields():
    seen, transport = _record()
    profile = MessengerProfile()
    async with httpx.AsyncClient(transport=transport) as http:
        await profile.add_labels(http, token=TOKEN, psid="PSID1", labels=["VIP"])
        await profile.remove_labels(http, token=TOKEN, psid="PSID1", labels=["VIP"])
    assert json.loads(seen[0].content) == {"custom_labels": ["VIP"]}
    assert seen[0].url.path.endswith("/PSID1/custom_labels")
    assert seen[1].method == "DELETE"
    assert seen[1].url.params["fields"] == "VIP"


@pytest.mark.asyncio
async def test_metas_refusal_is_carried_not_swallowed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 100, "message": "Invalid parameter"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(Exception) as exc:
            await MessengerProfile().set_get_started(http, token=TOKEN)
    assert "Invalid parameter" in str(exc.value)
