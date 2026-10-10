"""Vision reranker (spec §12.1) — image-vs-image rerank over the candidates.

Wraps RerankerProvider and maps its caller-order indexes back to candidates.
A failed rerank is the CALLER's problem: the pipeline catches
ExternalProviderError and the decision engine caps the confidence at MEDIUM
(never HIGH) — this module only fails loudly with the provider's error.

When a session and tenant are provided the call rides the gateway's
governed rerank path (budget, egress, breaker, ModelCall record); the bare
provider path remains for unit tests and offline calibration seams.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.ai.agents.customer.vision.schemas import Candidate
from app.modules.ai.providers import RerankerProvider, RerankResult


def _map_scores(
    candidates: list[Candidate], results: list[RerankResult]
) -> list[tuple[Candidate, float]]:
    scored: list[tuple[Candidate, float]] = []
    for entry in results:
        if not 0 <= entry.index < len(candidates):
            raise ValueError(f"rerank index {entry.index} outside 0..{len(candidates) - 1}")
        scored.append((candidates[entry.index], entry.score))
    return scored


async def rerank_candidates(
    candidates: list[Candidate],
    *,
    query_image: str,
    top_n: int | None = None,
    session: AsyncSession | None = None,
    tenant_id: uuid.UUID | None = None,
    _reranker: RerankerProvider | None = None,
    _client=None,
) -> list[tuple[Candidate, float]]:
    """Rerank the customer photo against candidate product photos.

    Returns (candidate, score) pairs, best score first — RerankerProvider
    preserves caller-order indexes and sorts them descending, so result
    index i maps straight back to ``candidates[i]``. An index outside the
    input range is a provider contract break and fails loudly rather than
    silently shifting every mapping after it.
    """
    if not candidates:
        return []
    if session is not None and tenant_id is not None and _reranker is None:
        from app.modules.ai.gateway import AIGateway

        results = await AIGateway().rerank_vision(
            session,
            tenant_id,
            query=query_image,
            documents=[{"image": c.image_url} for c in candidates],
            top_n=top_n,
            _client=_client,
        )
        return _map_scores(candidates, results)

    settings = get_settings()
    reranker = _reranker or RerankerProvider()
    results = await reranker.rerank(
        base_url=settings.ai_reranker_base_url,
        api_key=settings.ai_reranker_api_key,
        model=settings.ai_reranker_model,
        query=query_image,
        documents=[{"image": c.image_url} for c in candidates],
        top_n=top_n,
        _client=_client,
    )
    return _map_scores(candidates, results)
