"""P1-6: the vision provider calls ride the same governance as chat/embed.

The vision modules used to call MultimodalEmbeddingProvider/RerankerProvider
directly — real spend with no budget reservation, no data-egress gate, no
endpoint breaker and no ModelCall row. These tests pin the gateway methods
and the wiring that routes retrieval through them.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.core.errors import ValidationError
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import AIBudgetReservation, AIProviderPolicy, ModelCall
from app.modules.ai.providers import MultimodalContent


class _StubVisionSettings:
    ai_embedding_vision_provider = "dashscope"
    ai_embedding_vision_base_url = "https://vision.test/api/v1"
    ai_embedding_vision_api_key = "vision-key"
    ai_embedding_vision_model = "vision-embed-test"
    ai_embedding_vision_dimensions = 3
    ai_reranker_provider = "jina"
    ai_reranker_base_url = "https://rerank.test/v1"
    ai_reranker_api_key = "rerank-key"
    ai_reranker_model = "rerank-test"


def _embed_ok_response():
    return httpx.Response(
        200,
        json={"output": {"embeddings": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}},
    )


async def test_embed_vision_reserves_records_and_calls_provider(db, tenant_ctx, monkeypatch):
    monkeypatch.setattr("app.modules.ai.gateway.get_settings", lambda: _StubVisionSettings())
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        seen["payload"] = request.read()
        return _embed_ok_response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        vectors = await AIGateway().embed_vision(
            db,
            tenant_ctx.tenant_id,
            contents=[MultimodalContent(image="https://c.test/x.png", text="red abaya")],
            _client=client,
        )

    assert vectors == [[0.1, 0.2, 0.3]]
    assert seen["auth"] == "Bearer vision-key"
    assert "contents" in seen["payload"].decode()

    call = (
        (await db.execute(select(ModelCall).where(ModelCall.tenant_id == tenant_ctx.tenant_id)))
        .scalars()
        .one()
    )
    assert call.alias == "vision_embedding"
    assert call.provider == "dashscope"
    assert call.model == "vision-embed-test"
    assert call.tokens_in > 0
    assert call.status == "ok"

    reservation = (
        (
            await db.execute(
                select(AIBudgetReservation).where(
                    AIBudgetReservation.tenant_id == tenant_ctx.tenant_id
                )
            )
        )
        .scalars()
        .one()
    )
    assert reservation.status == "settled"


async def test_embed_vision_blocked_by_egress_policy(db, tenant_ctx, monkeypatch):
    monkeypatch.setattr("app.modules.ai.gateway.get_settings", lambda: _StubVisionSettings())
    db.add(
        AIProviderPolicy(
            tenant_id=tenant_ctx.tenant_id,
            provider="dashscope",
            status="denied",
        )
    )
    await db.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("provider must not be called when egress policy denies")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValidationError, match="data-egress"):
            await AIGateway().embed_vision(
                db,
                tenant_ctx.tenant_id,
                contents=[MultimodalContent(image="https://c.test/x.png")],
                _client=client,
            )

    call = (
        (await db.execute(select(ModelCall).where(ModelCall.tenant_id == tenant_ctx.tenant_id)))
        .scalars()
        .one()
    )
    assert call.status == "error"


async def test_rerank_vision_records_and_scores(db, tenant_ctx, monkeypatch):
    monkeypatch.setattr("app.modules.ai.gateway.get_settings", lambda: _StubVisionSettings())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.4},
                    {"index": 0, "relevance_score": 0.9},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await AIGateway().rerank_vision(
            db,
            tenant_ctx.tenant_id,
            query="https://c.test/q.png",
            documents=[{"image": "https://c.test/a.png"}, {"image": "https://c.test/b.png"}],
            _client=client,
        )

    assert [(r.index, r.score) for r in results] == [(0, 0.9), (1, 0.4)]
    call = (
        (await db.execute(select(ModelCall).where(ModelCall.tenant_id == tenant_ctx.tenant_id)))
        .scalars()
        .one()
    )
    assert call.alias == "vision_rerank"
    assert call.status == "ok"


async def test_retrieve_candidates_rides_the_governed_path(db, tenant_ctx, monkeypatch):
    from app.modules.ai.agents.customer.vision import retrieval

    seen: dict = {}

    class _StubGateway:
        async def embed_vision(self, session, tenant_id, *, contents, _client=None):
            seen["contents"] = contents
            seen["tenant_id"] = tenant_id
            return [[0.0, 0.0, 0.0]]

    monkeypatch.setattr("app.modules.ai.gateway.AIGateway", _StubGateway)

    candidates = await retrieval.retrieve_candidates(
        db, tenant_ctx.tenant_id, image_url="https://c.test/q.png"
    )

    assert seen["tenant_id"] == tenant_ctx.tenant_id
    assert seen["contents"][0].image == "https://c.test/q.png"
    # Empty catalog: the governed call happened, the vector query returns none.
    assert candidates == []
