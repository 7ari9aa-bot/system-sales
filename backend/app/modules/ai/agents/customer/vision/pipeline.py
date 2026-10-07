"""Vision pipeline (spec §12) — retrieval → rerank → decision → verification.

Orchestrates the four stages into one MatchResult and is the LAST place the
model-visible contract is enforced: the result carries product ids, titles
and verification flags ONLY — no image URLs, no cosine distances, no reranker
scores (§12.3), so a prompt-injected customer cannot fish internals out of
the reply and thresholds can move without touching the reply surface.

A failed reranker caps the confidence at MEDIUM (never HIGH, §12.2) and the
pipeline keeps going on the embedding order rather than failing the turn.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ExternalProviderError
from app.modules.ai.agents.customer.vision.decision import ScoredCandidate, decide
from app.modules.ai.agents.customer.vision.reranker import rerank_candidates
from app.modules.ai.agents.customer.vision.retrieval import retrieve_candidates
from app.modules.ai.agents.customer.vision.schemas import Confidence, MatchResult
from app.modules.ai.agents.customer.vision.verifier import verify_products

# Candidates surfaced to the model after verification (§12.3): enough to
# present a match plus its close alternatives, small enough to read.
MAX_RESULT_CANDIDATES = 5


async def run_vision_match(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    image_url: str,
    text_hint: str | None = None,
) -> MatchResult:
    """One customer photo (+ optional hint) through the whole vision stack."""
    candidates = await retrieve_candidates(
        session, tenant_id, image_url=image_url, text_hint=text_hint
    )
    if not candidates:
        return MatchResult(confidence=Confidence.LOW, reason="no_candidates")

    try:
        scored = await rerank_candidates(candidates, query_image=image_url)
        reranker_ok = True
    except ExternalProviderError:
        # §12.2: a dead reranker NEVER yields HIGH. Keep the embedding order
        # so the reply can still present "this looks like ..." with the
        # decision engine's uncertainty caveat attached.
        scored = [(candidate, 0.0) for candidate in candidates]
        reranker_ok = False

    decision_input = [
        ScoredCandidate(candidate=candidate, score=score, embedding_rank=candidate.retrieval_rank)
        for candidate, score in scored
    ]
    confidence, reason = decide(decision_input, reranker_ok=reranker_ok)

    verified = await verify_products(
        session, tenant_id, [candidate.product_id for candidate, _ in scored]
    )
    result_candidates = [
        {
            "product_id": str(candidate.product_id),
            "title": candidate.product_title,
            "verified": verified.get(candidate.product_id, {}).get("verified", False),
            "available_variants": verified.get(candidate.product_id, {}).get(
                "available_variants", 0
            ),
        }
        for candidate, _score in scored[:MAX_RESULT_CANDIDATES]
    ]
    return MatchResult(
        confidence=confidence,
        candidates=result_candidates,
        reason=reason,
        as_of=datetime.now(UTC).isoformat(),
    )
