"""Vision retrieval (spec §12.1) — embed the customer photo, take pgvector's
cosine top-30, group per product, cap ~10.

The vector query is parameter-bound ``sa.text()`` SQL on purpose: it reads
catalog tables cross-module (the customers/timeline read-model precedent) and
a NEW cross-module import site would raise the boundary ratchet
(tests/test_module_boundaries.py, baseline 99). Every statement stays
tenant-filtered twice over — ``WHERE tenant_id`` plus the RLS policy on the
GUC the session runs under.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.storage import get_storage
from app.modules.ai.agents.customer.vision.schemas import Candidate
from app.modules.ai.providers import MultimodalContent, MultimodalEmbeddingProvider

# §12.1: cosine top-30, best image per product, capped at ~10 candidates.
EMBEDDING_TOP_K = 30
MAX_CANDIDATES = 10
# The vector space is pinned per model+version (§12.6): retrieval and indexer
# must compare and write the SAME generation, so the version lives here and
# the indexer imports it.
MODEL_VERSION = "1"

_RETRIEVAL_SQL = sa.text(
    """
    WITH nearest AS (
        SELECT pe.product_id  AS product_id,
               p.title        AS product_title,
               pi.id          AS image_id,
               pi.url         AS image_url,
               pe.vector <=> CAST(:qvec AS vector) AS distance
        FROM product_embeddings pe
        JOIN product_images pi ON pi.id = pe.product_image_id
        JOIN products p ON p.id = pe.product_id
        WHERE pe.tenant_id = :tenant_id
          AND pe.model = :model
          AND pe.model_version = :model_version
        ORDER BY distance
        LIMIT :top_k
    ),
    per_product AS (
        SELECT DISTINCT ON (product_id)
            product_id, product_title, image_id, image_url, distance
        FROM nearest
        ORDER BY product_id, distance
    )
    SELECT product_id, product_title, image_id, image_url
    FROM per_product
    ORDER BY distance
    LIMIT :cap
    """
)


def _vector_literal(vector: list[float]) -> str:
    """pgvector's text form: '[0.1,0.2,...]' — bound as one string parameter."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


async def retrieve_candidates(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    image_url: str,
    text_hint: str | None = None,
    top_k: int = EMBEDDING_TOP_K,
    max_candidates: int = MAX_CANDIDATES,
    _embedding: MultimodalEmbeddingProvider | None = None,
    _client=None,
) -> list[Candidate]:
    """Embed the customer photo (+ optional text hint) and return at most
    ``max_candidates`` product-level candidates, best cosine distance first.

    ``retrieval_rank`` is 1-based and IS the decision engine's agreement
    input — the decision reads the rank, never the distance.
    """
    settings = get_settings()
    embedding = _embedding or MultimodalEmbeddingProvider()
    contents = [MultimodalContent(image=image_url, text=text_hint)]
    (vector,) = await embedding.embed(
        base_url=settings.ai_embedding_vision_base_url,
        api_key=settings.ai_embedding_vision_api_key,
        model=settings.ai_embedding_vision_model,
        contents=contents,
        expected_dimensions=settings.ai_embedding_vision_dimensions,
        _client=_client,
    )
    qvec = _vector_literal(vector)

    rows = (
        await session.execute(
            _RETRIEVAL_SQL,
            {
                "qvec": qvec,
                "tenant_id": str(tenant_id),
                "model": settings.ai_embedding_vision_model,
                "model_version": MODEL_VERSION,
                "top_k": top_k,
                "cap": max_candidates,
            },
        )
    ).all()
    return [
        Candidate(
            product_id=row.product_id,
            product_title=row.product_title,
            image_id=row.image_id,
            image_url=get_storage().resolve_product_image_url(
                row.image_url, tenant_id=tenant_id
            ),
            retrieval_rank=rank,
        )
        for rank, row in enumerate(rows, start=1)
    ]
