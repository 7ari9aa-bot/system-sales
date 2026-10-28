"""Jina as the vision embedding provider: request shape, ordering, dimension guard, errors."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.errors import ExternalProviderError
from app.modules.ai.providers import JinaMultimodalEmbeddingProvider, MultimodalContent

BASE = "https://api.jina.ai/v1"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _vec(n: int, fill: float = 0.1) -> list[float]:
    return [fill] * n


@pytest.mark.asyncio
async def test_request_shape_and_ordering() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        # Returned out of order on purpose: the provider must restore the caller's order.
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": _vec(768, 0.2)},
                    {"index": 0, "embedding": _vec(768, 0.1)},
                ]
            },
        )

    async with _client(handler) as client:
        vectors = await JinaMultimodalEmbeddingProvider().embed(
            base_url=BASE,
            api_key="k",
            model="jina-clip-v2",
            contents=[
                MultimodalContent(image="https://x/a.jpg", text="caption"),
                MultimodalContent(text="قميص"),
            ],
            expected_dimensions=768,
            _client=client,
        )

    assert seen["url"] == f"{BASE}/embeddings"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "jina-clip-v2"
    assert seen["body"]["dimensions"] == 768
    assert seen["body"]["normalized"] is True
    # One content item is ONE input: image+caption is sent as the image alone.
    assert seen["body"]["input"] == [{"image": "https://x/a.jpg"}, {"text": "قميص"}]
    assert vectors[0][0] == pytest.approx(0.1) and vectors[1][0] == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_wrong_dimension_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": _vec(1024)}]})

    async with _client(handler) as client:
        with pytest.raises(ExternalProviderError, match="768"):
            await JinaMultimodalEmbeddingProvider().embed(
                base_url=BASE,
                api_key="k",
                model="jina-clip-v2",
                contents=[MultimodalContent(text="x")],
                expected_dimensions=768,
                _client=client,
            )


@pytest.mark.asyncio
async def test_missing_vector_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": _vec(768)}]})

    async with _client(handler) as client:
        with pytest.raises(ExternalProviderError, match="expected 2 vectors"):
            await JinaMultimodalEmbeddingProvider().embed(
                base_url=BASE,
                api_key="k",
                model="jina-clip-v2",
                contents=[MultimodalContent(text="a"), MultimodalContent(text="b")],
                _client=client,
            )


@pytest.mark.asyncio
async def test_http_error_surfaces_the_provider_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid API key"})

    async with _client(handler) as client:
        with pytest.raises(ExternalProviderError, match="401: Invalid API key") as info:
            await JinaMultimodalEmbeddingProvider().embed(
                base_url=BASE,
                api_key="bad",
                model="jina-clip-v2",
                contents=[MultimodalContent(text="a")],
                _client=client,
            )
    assert info.value.details["status_code"] == 401


@pytest.mark.asyncio
async def test_private_base_url_is_blocked_by_the_egress_guard() -> None:
    with pytest.raises(Exception):  # noqa: B017 - guard raises its own validation error
        await JinaMultimodalEmbeddingProvider().embed(
            base_url="http://169.254.169.254",
            api_key="k",
            model="m",
            contents=[MultimodalContent(text="a")],
        )
