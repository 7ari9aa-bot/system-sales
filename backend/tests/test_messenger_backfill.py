"""The backfill walk: capped, retryable, and built on Meta's own stable ids."""

from __future__ import annotations

import httpx
import pytest

from app.modules.conversations.gateway.messenger_backfill import MessengerBackfill

TOKEN = "page-token"


def _paged(pages: list[dict], messages: dict[str, list] | None = None):
    calls: list[str] = []
    messages = messages or {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/messages"):
            cid = request.url.path.split("/")[-2]
            return httpx.Response(200, json={"data": messages.get(cid, [])})
        if "after=c2" in str(request.url):
            return httpx.Response(200, json=pages[1])
        return httpx.Response(200, json=pages[0])

    return calls, httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_it_reads_the_conversations_and_their_messages():
    pages = [
        {
            "data": [{"id": "t_1"}, {"id": "t_2"}],
            "paging": {"next": "https://graph.facebook.com/v23.0/P1/conversations?after=c2"},
        },
        {"data": [{"id": "t_3"}], "paging": {}},
    ]
    calls, transport = _paged(pages, {"t_1": [{"id": "m_1"}]})
    async with httpx.AsyncClient(transport=transport) as http:
        result = await MessengerBackfill().walk(http, page_id="P1", token=TOKEN)

    assert result.conversation_ids == ["t_1", "t_2", "t_3"]
    assert result.message_ids == ["m_1"]
    assert result.pages_read == 2
    assert result.stopped == "exhausted"


@pytest.mark.asyncio
async def test_the_cap_stops_the_walk_and_says_so():
    pages = [{"data": [{"id": f"t_{i}"} for i in range(5)], "paging": {"next": "https://x?after=c2"}}]
    calls, transport = _paged(pages)
    async with httpx.AsyncClient(transport=transport) as http:
        result = await MessengerBackfill().walk(
            http, page_id="P1", token=TOKEN, max_conversations=3, with_messages=False
        )
    assert len(result.conversations) == 3
    assert result.stopped == "capped"
    assert len(calls) == 1  # stopped before asking Meta for another page


@pytest.mark.asyncio
async def test_a_rate_limit_is_reported_as_retryable_not_as_an_empty_inbox():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limit"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await MessengerBackfill().walk(http, page_id="P1", token=TOKEN)
    assert result.stopped == "error"
    assert "rate limit" in (result.error or "")
    assert result.conversations == []


@pytest.mark.asyncio
async def test_running_it_twice_yields_the_same_ids_so_a_retry_cannot_duplicate():
    pages = [{"data": [{"id": "t_1"}], "paging": {}}]
    _, transport = _paged(pages, {"t_1": [{"id": "m_1"}]})
    async with httpx.AsyncClient(transport=transport) as http:
        first = await MessengerBackfill().walk(http, page_id="P1", token=TOKEN)
        second = await MessengerBackfill().walk(http, page_id="P1", token=TOKEN)
    assert first.conversation_ids == second.conversation_ids
    assert first.message_ids == second.message_ids
