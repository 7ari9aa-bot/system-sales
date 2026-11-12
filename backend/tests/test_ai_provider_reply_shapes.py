"""Whatever model a shop plugs in, the reply the merchant reads is the ANSWER, not the thinking.

The sales assistant's model is a per-shop setting and the platform default changes, so the chat
parser cannot assume one vendor's reply shape. These are the shapes real OpenAI-compatible
endpoints return: plain text, a reasoning model that keeps its thinking inline in <think> tags,
one that puts it in a separate field, a list of content parts, and an empty content.
"""

from __future__ import annotations

import httpx
import pytest

from app.modules.ai.providers import AIProvider

BASE_URL = "https://api.test/v1"


async def _content(message: dict):
    body = {"model": "m", "choices": [{"message": message}], "usage": {}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await AIProvider().chat(
            base_url=BASE_URL,
            api_key="k",
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            _client=client,
        )
    return result.content


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ({"content": "الإيراد ارتفع 12%"}, "الإيراد ارتفع 12%"),
        ({"content": "<think>لازم أحسب الأول</think>الإيراد ارتفع 12%"}, "الإيراد ارتفع 12%"),
        ({"content": "<think>\nسطر\nتاني\n</think>\n\nالإيراد 5"}, "الإيراد 5"),
        ({"content": "<THINK>x</THINK>الرد"}, "الرد"),
        ({"content": "الرد", "reasoning": "تفكير منفصل", "reasoning_content": "كمان"}, "الرد"),
        (
            {"content": [{"type": "text", "text": "جزء 1 "}, {"type": "text", "text": "جزء 2"}]},
            "جزء 1 جزء 2",
        ),
        (
            {"content": [{"type": "reasoning", "text": "تفكير"}, {"type": "text", "text": "الرد"}]},
            "الرد",
        ),
        ({"content": ""}, None),
        ({"content": None}, None),
        ({"content": "<think>تفكير بس</think>"}, None),
        ({"content": "  \n "}, None),
    ],
)
async def test_the_merchant_reads_the_answer_whatever_shape_the_model_replies_in(message, expected):
    assert await _content(message) == expected


async def test_an_unclosed_think_block_is_not_shown_as_an_answer():
    # A model cut off mid-thought has produced no answer; showing its half-thought is wrong.
    assert await _content({"content": "<think>لسه بفكر في"}) is None


async def test_a_tool_call_turn_with_no_text_keeps_content_empty():
    body = {
        "model": "m",
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "revenue", "arguments": "{}"}}
                    ],
                }
            }
        ],
        "usage": {},
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await AIProvider().chat(
            base_url=BASE_URL,
            api_key="k",
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            _client=client,
        )
    assert result.content is None
    assert [c.name for c in result.tool_calls] == ["revenue"]
