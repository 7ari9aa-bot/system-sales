"""AIProvider / EmbeddingProvider unit tests — mocked HTTP, no database."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.errors import ExternalProviderError, ValidationError
from app.modules.ai.providers import AIProvider, EmbeddingProvider

BASE_URL = "https://api.test/v1"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _chat_body(content="pong", with_tool_calls=None):
    message: dict = {"content": content}
    if with_tool_calls is not None:
        message["tool_calls"] = with_tool_calls
    return {
        "model": "gpt-test",
        "choices": [{"message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 4},
    }


async def test_chat_parses_content_and_usage():
    async with _client(lambda request: httpx.Response(200, json=_chat_body("hello"))) as client:
        result = await AIProvider().chat(
            base_url=BASE_URL,
            api_key="k",
            model="gpt-test",
            messages=[{"role": "user", "content": "hi"}],
            _client=client,
        )
    assert result.content == "hello"
    assert result.tool_calls == []
    assert result.tokens_in == 9
    assert result.tokens_out == 4
    assert result.raw_model == "gpt-test"


async def test_chat_parses_tool_calls_with_json_arguments():
    body = _chat_body(
        content=None,
        with_tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "search_products",
                    "arguments": json.dumps({"query": "widget", "limit": 5}),
                },
            }
        ],
    )
    async with _client(lambda request: httpx.Response(200, json=body)) as client:
        result = await AIProvider().chat(
            base_url=BASE_URL,
            api_key="k",
            model="gpt-test",
            messages=[{"role": "user", "content": "find widgets"}],
            _client=client,
        )
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.id == "call_1"
    assert call.name == "search_products"
    assert call.arguments == {"query": "widget", "limit": 5}


async def test_chat_sends_openai_payload_and_auth_header():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_chat_body())

    tools = [{"type": "function", "function": {"name": "check_stock", "parameters": {}}}]
    async with _client(handler) as client:
        await AIProvider().chat(
            base_url=BASE_URL,
            api_key="secret-key",
            model="gpt-test",
            messages=[{"role": "user", "content": "hi"}],
            tools=tools,
            temperature=0.2,
            max_tokens=128,
            _client=client,
        )
    assert captured["url"] == f"{BASE_URL}/chat/completions"
    assert captured["auth"] == "Bearer secret-key"
    assert captured["body"]["model"] == "gpt-test"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["body"]["tools"] == tools
    assert captured["body"]["temperature"] == 0.2
    assert captured["body"]["max_tokens"] == 128


async def test_chat_http_401_raises_external_provider_error():
    async with _client(lambda request: httpx.Response(401, json={"error": "bad key"})) as client:
        with pytest.raises(ExternalProviderError) as exc_info:
            await AIProvider().chat(
                base_url=BASE_URL,
                api_key="bad",
                model="gpt-test",
                messages=[{"role": "user", "content": "hi"}],
                _client=client,
            )
    assert exc_info.value.details["status_code"] == 401


async def test_chat_malformed_response_raises():
    async with _client(lambda request: httpx.Response(200, json={"unexpected": True})) as client:
        with pytest.raises(ExternalProviderError, match="malformed"):
            await AIProvider().chat(
                base_url=BASE_URL,
                api_key="k",
                model="gpt-test",
                messages=[{"role": "user", "content": "hi"}],
                _client=client,
            )


async def test_chat_network_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with _client(handler) as client:
        with pytest.raises(ExternalProviderError, match="chat request failed"):
            await AIProvider().chat(
                base_url=BASE_URL,
                api_key="k",
                model="gpt-test",
                messages=[{"role": "user", "content": "hi"}],
                _client=client,
            )


async def test_embed_returns_vectors_ordered_by_index():
    body = {
        "data": [
            {"index": 1, "embedding": [0.2, 0.2, 0.2]},
            {"index": 0, "embedding": [0.1, 0.1, 0.1]},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{BASE_URL}/embeddings"
        assert json.loads(request.content)["input"] == ["a", "b"]
        return httpx.Response(200, json=body)

    async with _client(handler) as client:
        vectors = await EmbeddingProvider().embed(
            base_url=BASE_URL,
            api_key="k",
            model="embed-test",
            texts=["a", "b"],
            _client=client,
        )
    assert vectors == [[0.1, 0.1, 0.1], [0.2, 0.2, 0.2]]


async def test_embed_http_error_and_malformed_raise():
    async with _client(lambda request: httpx.Response(500, json={})) as client:
        with pytest.raises(ExternalProviderError):
            await EmbeddingProvider().embed(
                base_url=BASE_URL, api_key="k", model="m", texts=["a"], _client=client
            )

    async with _client(lambda request: httpx.Response(200, json={"nope": 1})) as client:
        with pytest.raises(ExternalProviderError, match="malformed"):
            await EmbeddingProvider().embed(
                base_url=BASE_URL, api_key="k", model="m", texts=["a"], _client=client
            )


# ---------------------------------------------------------------------------
# S6 egress guard — every transport refuses a non-public base_url before any
# request is built. The base_url can come from tenant model_configs, so this
# is the open-proxy boundary; the vision transports below are covered too,
# because they are gateways out of the process just as much as chat is.
# ---------------------------------------------------------------------------

_BAD_URLS = [
    "http://169.254.169.254/v1",  # cloud instance metadata (link-local)
    "http://localhost:8000/v1",  # our own API, past the edge
    "http://10.1.2.3:9000/v1",  # RFC1918 private literal
    "https://metadata.google.internal/v1",  # GCP metadata hostname
    "https://user:pass@api.test/v1",  # embedded credentials
    "ftp://api.test/v1",  # non-http scheme
]


@pytest.mark.parametrize("bad_url", _BAD_URLS)
async def test_chat_refuses_non_public_base_url(bad_url):
    with pytest.raises(ValidationError):
        await AIProvider().chat(
            base_url=bad_url,
            api_key="k",
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            _client=None,
        )


@pytest.mark.parametrize("bad_url", _BAD_URLS)
async def test_embed_refuses_non_public_base_url(bad_url):
    with pytest.raises(ValidationError):
        await EmbeddingProvider().embed(
            base_url=bad_url, api_key="k", model="m", texts=["a"], _client=None
        )


@pytest.mark.parametrize("bad_url", _BAD_URLS)
async def test_vision_transports_refuse_non_public_base_url(bad_url):
    from app.modules.ai.providers import (
        MultimodalContent,
        MultimodalEmbeddingProvider,
        RerankerProvider,
    )

    with pytest.raises(ValidationError):
        await MultimodalEmbeddingProvider().embed(
            base_url=bad_url,
            api_key="k",
            model="m",
            contents=[MultimodalContent(text="a", image="https://x.test/i.png")],
            _client=None,
        )
    with pytest.raises(ValidationError):
        await RerankerProvider().rerank(
            base_url=bad_url,
            api_key="k",
            model="m",
            query="q",
            documents=[{"text": "doc"}],
            _client=None,
        )


async def test_public_base_url_passes_the_guard():
    """A normal https host name is not touched by the guard — the transport
    call below reaching the (mock) request proves the guard passed it."""
    async with _client(lambda request: httpx.Response(200, json=_chat_body())) as client:
        result = await AIProvider().chat(
            base_url=BASE_URL,
            api_key="k",
            model="gpt-test",
            messages=[{"role": "user", "content": "hi"}],
            _client=client,
        )
    assert result.content == "pong"
