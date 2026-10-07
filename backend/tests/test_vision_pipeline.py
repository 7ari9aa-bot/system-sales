"""Vision pipeline tests (spec §12.2/§12.3) — mocked stages, no database.

The pipeline is the LAST place the model-visible contract is enforced, so
these pin the result shape (business fields only — no URLs, no scores, no
distances) and the reranker-down behavior: keep going on the embedding order,
confidence capped at MEDIUM, verification still running.
"""

from __future__ import annotations

import uuid

from app.core.errors import ExternalProviderError
from app.modules.ai.agents.customer.vision import pipeline
from app.modules.ai.agents.customer.vision.schemas import Candidate, Confidence


def _candidate(rank: int) -> Candidate:
    return Candidate(
        product_id=uuid.uuid4(),
        product_title=f"Product {rank}",
        image_id=uuid.uuid4(),
        image_url=f"https://cdn.test/{rank}.png",
        retrieval_rank=rank,
    )


async def test_result_carries_business_fields_only(monkeypatch):
    seen: dict = {}

    async def fake_retrieve(session, tenant_id, *, image_url, text_hint=None, **kw):
        seen["hint"] = text_hint
        return [_candidate(1), _candidate(2)]

    async def fake_rerank(candidates, *, query_image, **kw):
        return [(candidates[1], 0.9), (candidates[0], 0.6)]

    async def fake_verify(session, tenant_id, product_ids):
        return {p: {"verified": True, "available_variants": 2} for p in product_ids}

    monkeypatch.setattr(pipeline, "retrieve_candidates", fake_retrieve)
    monkeypatch.setattr(pipeline, "rerank_candidates", fake_rerank)
    monkeypatch.setattr(pipeline, "verify_products", fake_verify)

    result = await pipeline.run_vision_match(None, uuid.uuid4(), image_url="https://c.test/q.png")

    dumped = repr(result.candidates)
    assert "http" not in dumped, "no URLs in the model-visible result (§12.3)"
    assert "score" not in dumped and "distance" not in dumped and "image" not in dumped
    # Clear winner at 0.9 with a 0.3 gap, winner inside the embedding top-3.
    assert result.confidence is Confidence.HIGH
    assert [c["title"] for c in result.candidates] == ["Product 2", "Product 1"]
    assert all(c["verified"] and c["available_variants"] == 2 for c in result.candidates)
    assert result.as_of
    assert seen["hint"] is None


async def test_reranker_failure_never_yields_high(monkeypatch):
    async def fake_retrieve(session, tenant_id, *, image_url, text_hint=None, **kw):
        return [_candidate(1)]

    def boom(*args, **kwargs):
        raise ExternalProviderError("rerank down")

    async def fake_verify(session, tenant_id, product_ids):
        return {p: {"verified": False, "available_variants": 0} for p in product_ids}

    monkeypatch.setattr(pipeline, "retrieve_candidates", fake_retrieve)
    monkeypatch.setattr(pipeline, "rerank_candidates", boom)
    monkeypatch.setattr(pipeline, "verify_products", fake_verify)

    result = await pipeline.run_vision_match(None, uuid.uuid4(), image_url="https://c.test/q.png")

    # §12.2: capped at MEDIUM with the pipeline still delivering candidates
    # and their (negative) verification, rather than failing the turn.
    assert result.confidence is Confidence.MEDIUM
    assert result.reason == "reranker_unavailable"
    assert result.candidates[0]["verified"] is False
    assert result.candidates[0]["available_variants"] == 0


async def test_no_candidates_short_circuits_before_rerank(monkeypatch):
    async def fake_retrieve(session, tenant_id, *, image_url, text_hint=None, **kw):
        return []

    calls: list[str] = []

    async def fake_rerank(*args, **kwargs):
        calls.append("rerank")
        return []

    monkeypatch.setattr(pipeline, "retrieve_candidates", fake_retrieve)
    monkeypatch.setattr(pipeline, "rerank_candidates", fake_rerank)

    result = await pipeline.run_vision_match(
        None, uuid.uuid4(), image_url="https://c.test/q.png", text_hint="abaya"
    )
    assert result.confidence is Confidence.LOW
    assert result.reason == "no_candidates"
    assert result.candidates == []
    assert calls == []
