"""A Page subscription belongs to ONE app: the merge must never borrow or drop another app's fields.

`/{page_id}/subscribed_apps` lists every app on the Page, and Meta REPLACES the field list on
every POST. Reading it without matching our own app id copied other apps' fields onto ours, and a
failed read looked exactly like "we have none", so the POST could wipe fields another capability
had added. These tests pin the three cases: other app ignored, read failure is not an empty list,
and our own existing fields survive the merge.
"""

from __future__ import annotations

import httpx
import pytest

from app.modules.conversations.gateway.base import ExternalProviderError
from app.modules.customers import meta_oauth

APP_ID = "111"
OTHER_APP = "222"


def _fields_sent(request: httpx.Request) -> list[str]:
    return str(request.url.params.get("subscribed_fields", "")).split(",")


@pytest.mark.asyncio
async def test_another_apps_fields_are_not_copied_onto_ours():
    entries = [
        {"id": OTHER_APP, "subscribed_fields": ["leadgen", "messages"]},
        {"id": APP_ID, "subscribed_fields": ["message_reads"]},
    ]
    sent: list[list[str]] = []

    def post(request):
        sent.append(_fields_sent(request))
        return httpx.Response(200, json={"success": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: (
                post(request)
                if request.method == "POST"
                else httpx.Response(200, json={"data": entries})
            )
        )
    ) as client:
        await meta_oauth._subscribe_page_to_app(
            client, page_id="p1", page_token="tok", provider="messenger", app_id=APP_ID
        )

    fields = sent[0]
    assert "message_reads" in fields
    assert "leadgen" not in fields, "another app's field was copied onto ours"


@pytest.mark.asyncio
async def test_a_failed_read_is_unknown_not_an_empty_subscription():
    async def failing(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(500, json={"error": {"message": "boom"}})
        return httpx.Response(200, json={"success": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(failing)) as client:
        kept = await meta_oauth._existing_subscribed_fields(
            client, page_id="p1", page_token="tok", app_id=APP_ID
        )

    assert kept is None, "a failed read must not look like 'this app has no fields'"


@pytest.mark.asyncio
async def test_our_own_fields_survive_the_merge():
    entries = [{"id": APP_ID, "subscribed_fields": ["feed", "mention"]}]
    sent: list[list[str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            sent.append(_fields_sent(request))
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"data": entries})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await meta_oauth._subscribe_page_to_app(
            client, page_id="p1", page_token="tok", provider="messenger", app_id=APP_ID
        )

    fields = sent[0]
    assert {"feed", "mention", "messages", "message_echoes"} <= set(fields)


@pytest.mark.asyncio
async def test_a_refused_subscription_is_an_error_not_a_silent_success():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"success": False})
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ExternalProviderError):
            await meta_oauth._subscribe_page_to_app(
                client, page_id="p1", page_token="tok", provider="messenger", app_id=APP_ID
            )
