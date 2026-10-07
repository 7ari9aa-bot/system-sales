"""Vision reranker tests (spec §12.1) — mocked provider, no database.

Pins the contract the decision engine depends on: caller-order indexes map
straight back to candidates, an out-of-range index fails loudly instead of
silently shifting every mapping after it, and an empty candidate list never
reaches the provider at all.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.ai.agents.customer.vision.reranker import rerank_candidates
from app.modules.ai.agents.customer.vision.schemas import Candidate
from app.modules.ai.providers import RerankResult


def _candidate(rank: int) -> Candidate:
    return Candidate(
        product_id=uuid.uuid4(),
        product_title=f"Product {rank}",
        image_id=uuid.uuid4(),
        image_url=f"https://cdn.test/{rank}.png",
        retrieval_rank=rank,
    )


class _FakeReranker:
    """RerankerProvider-shaped stub — same kwargs, scripted results."""

    def __init__(self, results: list[RerankResult]):
        self.results = results
        self.calls: list[dict] = []

    async def rerank(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        query: str,
        documents: list[dict],
        top_n: int | None = None,
        _client=None,
    ) -> list[RerankResult]:
        self.calls.append({"query": query, "documents": documents, "top_n": top_n})
        return self.results


async def test_empty_candidates_never_reach_the_provider():
    reranker = _FakeReranker(results=[])
    scored = await rerank_candidates([], query_image="https://c.test/q.png", _reranker=reranker)
    assert scored == []
    assert reranker.calls == []


async def test_indexes_map_back_to_caller_order():
    # Provider returns caller-order indexes sorted by score: index 2 first.
    candidates = [_candidate(1), _candidate(2), _candidate(3)]
    reranker = _FakeReranker(
        results=[
            RerankResult(index=2, score=0.91),
            RerankResult(index=0, score=0.63),
        ]
    )
    scored = await rerank_candidates(
        candidates, query_image="https://c.test/q.png", _reranker=reranker
    )
    assert [(c.product_title, round(s, 2)) for c, s in scored] == [
        ("Product 3", 0.91),
        ("Product 1", 0.63),
    ]


async def test_documents_carry_candidate_images_in_caller_order():
    candidates = [_candidate(1), _candidate(2)]
    reranker = _FakeReranker(results=[RerankResult(index=0, score=0.5)])
    await rerank_candidates(candidates, query_image="https://c.test/q.png", _reranker=reranker)
    assert reranker.calls[0]["documents"] == [
        {"image": "https://cdn.test/1.png"},
        {"image": "https://cdn.test/2.png"},
    ]
    assert reranker.calls[0]["query"] == "https://c.test/q.png"


async def test_top_n_passes_through_to_the_provider():
    reranker = _FakeReranker(results=[RerankResult(index=0, score=0.5)])
    await rerank_candidates(
        [_candidate(1)],
        query_image="https://c.test/q.png",
        top_n=1,
        _reranker=reranker,
    )
    assert reranker.calls[0]["top_n"] == 1


async def test_out_of_range_index_fails_loudly():
    # A provider contract break: index 5 into a 2-candidate list would
    # silently shift every mapping after it — it must raise instead.
    reranker = _FakeReranker(results=[RerankResult(index=5, score=0.9)])
    with pytest.raises(ValueError, match="outside 0..1"):
        await rerank_candidates(
            [_candidate(1), _candidate(2)],
            query_image="https://c.test/q.png",
            _reranker=reranker,
        )
