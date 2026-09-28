"""MultimodalEmbeddingProvider / RerankerProvider unit tests — mocked HTTP, no database.

These two transports carry the Customer Agent's vision pipeline (§12): the
multimodal embedding speaks DashScope's native schema, the reranker speaks
Jina's. The tests pin the wire format the pipeline depends on — one vector per
input item, caller-order indexes out of the reranker — plus the failure modes
the decision engine must not run on (dim drift, out-of-range scores).
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.errors import ExternalProviderError
from app.modules.ai.providers import (
    MultimodalContent,
    MultimodalEmbeddingProvider,
    RerankerProvider,
)

DASH_URL = "https://dashscope.test/api/v1"
JINA_URL = "https://rerank.test/v1"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _dash_body(vectors: list[list[float]]) -> dict:
    return {
        "output": {
            "embeddings": [
                {"index": i, "embedding": v, "type": "text" if i == 0 else "image"}
                for i, v in enumerate(vectors)
            ]
        },
        "usage": {"total_tokens": 12},
    }


async def test_embed_text_image_and_combined_items_share_one_space():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_dash_body([[0.1] * 768, [0.2] * 768, [0.3] * 768]),
        )

    contents = [
        MultimodalContent(text="abaya سوداء"),
        MultimodalContent(image="https://cdn.test/red.png"),
        MultimodalContent(image="data:image/png;base64,AAA", text="red t-shirt"),
    ]
    async with _client(handler) as client:
        vectors = await MultimodalEmbeddingProvider().embed(
            base_url=DASH_URL,
            api_key="k",
            model="tongyi-embedding-vision-flash",
            contents=contents,
            expected_dimensions=768,
            _client=client,
        )

    assert captured["url"] == (
        f"{DASH_URL}/services/embeddings/multimodal-embedding/multimodal-embedding"
    )
    # The wire shape: one item per input, image and text together in ONE item.
    assert captured["body"]["model"] == "tongyi-embedding-vision-flash"
    assert captured["body"]["input"]["contents"] == [
        {"text": "abaya سوداء"},
        {"image": "https://cdn.test/red.png"},
        {"image": "data:image/png;base64,AAA", "text": "red t-shirt"},
    ]
    assert len(vectors) == 3
    assert all(len(v) == 768 for v in vectors)


async def test_embed_dim_drift_fails_loudly():
    body = _dash_body([[0.1] * 512])
    async with _client(lambda request: httpx.Response(200, json=body)) as client:
        with pytest.raises(ExternalProviderError, match="768-dim"):
            await MultimodalEmbeddingProvider().embed(
                base_url=DASH_URL,
                api_key="k",
                model="tongyi-embedding-vision-flash",
                contents=[MultimodalContent(text="x")],
                expected_dimensions=768,
                _client=client,
            )


async def test_embed_dashscope_error_body_is_surfaced():
    # DashScope native errors: {"code", "message"} — the message must survive
    # into the exception ("Model not exist." beats a bare status code).
    async with _client(
        lambda request: httpx.Response(
            400, json={"code": "InvalidParameter", "message": "Model not exist."}
        )
    ) as client:
        with pytest.raises(ExternalProviderError, match="Model not exist."):
            await MultimodalEmbeddingProvider().embed(
                base_url=DASH_URL,
                api_key="k",
                model="nope",
                contents=[MultimodalContent(text="x")],
                _client=client,
            )


async def test_embed_empty_contents_and_blank_item_are_rejected():
    provider = MultimodalEmbeddingProvider()
    with pytest.raises(ValueError, match="empty"):
        await provider.embed(
            base_url=DASH_URL, api_key="k", model="m", contents=[], _client=None
        )
    body = _dash_body([[0.1] * 768])
    async with _client(lambda request: httpx.Response(200, json=body)) as client:
        with pytest.raises(ValueError, match="text or an image"):
            await provider.embed(
                base_url=DASH_URL,
                api_key="k",
                model="m",
                contents=[MultimodalContent()],
                _client=client,
            )


async def test_rerank_orders_by_score_and_keeps_caller_indexes():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        # Deliberately NOT sorted by score: the provider must enforce the
        # descending contract itself.
        return httpx.Response(
            200,
            json={
                "model": "jina-reranker-m0",
                "results": [
                    {"index": 2, "relevance_score": 0.42},
                    {"index": 0, "relevance_score": 0.91},
                    {"index": 1, "relevance_score": 0.63},
                ],
                "usage": {"total_tokens": 56},
            },
        )

    documents = [
        {"image": "https://a.test/1.png"},
        {"image": "https://b.test/2.png"},
        {"text": "a red shirt"},
    ]
    async with _client(handler) as client:
        results = await RerankerProvider().rerank(
            base_url=JINA_URL,
            api_key="k",
            model="jina-reranker-m0",
            query="https://customer.test/photo.png",
            documents=documents,
            top_n=3,
            _client=client,
        )

    assert captured["url"] == f"{JINA_URL}/rerank"
    assert captured["body"]["top_n"] == 3
    assert captured["body"]["query"] == "https://customer.test/photo.png"
    assert captured["body"]["documents"] == documents
    assert [(r.index, round(r.score, 2)) for r in results] == [(0, 0.91), (1, 0.63), (2, 0.42)]


async def test_rerank_out_of_range_score_fails_instead_of_poisoning_thresholds():
    async with _client(
        lambda request: httpx.Response(
            200, json={"results": [{"index": 0, "relevance_score": 1.42}]}
        )
    ) as client:
        with pytest.raises(ExternalProviderError, match=r"outside \[0, 1\]"):
            await RerankerProvider().rerank(
                base_url=JINA_URL,
                api_key="k",
                model="jina-reranker-m0",
                query="q",
                documents=[{"text": "doc"}],
                _client=client,
            )


async def test_rerank_http_and_network_errors_raise():
    limited = httpx.Response(429, json={"detail": "rate limited"})
    async with _client(lambda request: limited) as client:
        with pytest.raises(ExternalProviderError) as exc_info:
            await RerankerProvider().rerank(
                base_url=JINA_URL,
                api_key="k",
                model="jina-reranker-m0",
                query="q",
                documents=[{"text": "d"}],
                _client=client,
            )
    assert exc_info.value.details["status_code"] == 429

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with _client(handler) as client:
        with pytest.raises(ExternalProviderError, match="rerank request failed"):
            await RerankerProvider().rerank(
                base_url=JINA_URL,
                api_key="k",
                model="jina-reranker-m0",
                query="q",
                documents=[{"text": "d"}],
                _client=client,
            )
