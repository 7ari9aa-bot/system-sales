"""Vision indexer (spec §12.6) — offline embedding of approved product media.

One vector per approved catalog image, pinned to the embedding model by the
UNIQUE constraint (uq_product_embeddings_image_model_version): re-running is
an idempotent upsert, and a provider-model change is a full re-index by
construction — a row for the old model simply stops matching retrieval's
model filter. Catalog reads ride parameter-bound ``sa.text()`` SQL (the
read-model precedent; a NEW cross-module import site would raise the boundary
ratchet), and only images of SELLABLE products are embedded, so retrieval can
never surface a draft or archived product.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.ai.agents.customer.vision.retrieval import MODEL_VERSION
from app.modules.ai.models import ProductEmbedding
from app.modules.ai.providers import MultimodalContent, MultimodalEmbeddingProvider
from app.modules.ai.tools import sellable_product_statuses

_IMAGES_SQL = sa.text(
    """
    SELECT pi.id    AS image_id,
           pi.url   AS url,
           pi.alt   AS alt,
           pi.product_id AS product_id
    FROM product_images pi
    JOIN products p ON p.id = pi.product_id
    WHERE pi.tenant_id = :tenant_id
      AND p.status = ANY(:sellable)
      AND pi.url IS NOT NULL
      AND pi.url <> ''
    ORDER BY pi.id
    """
)


async def index_product_images(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    batch_size: int = 16,
    model_version: str = MODEL_VERSION,
    _provider: MultimodalEmbeddingProvider | None = None,
    _client=None,
) -> dict:
    """Embed every approved product image and upsert its vector.

    Idempotent: a second run over unchanged images rewrites the same rows
    (ON CONFLICT on image+model+version) and reports the same totals. Each
    item carries the image plus its alt text when present — the same
    image+caption shape the retrieval query embeds, so both sides land in
    one vector space.
    """
    settings = get_settings()
    provider = _provider or MultimodalEmbeddingProvider()
    statuses = sorted(sellable_product_statuses())

    rows = (
        await session.execute(
            _IMAGES_SQL, {"tenant_id": str(tenant_id), "sellable": statuses}
        )
    ).all()

    indexed = 0
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        contents = []
        for row in chunk:
            if row.alt:
                contents.append(MultimodalContent(image=row.url, text=row.alt))
            else:
                contents.append(MultimodalContent(image=row.url))
        vectors = await provider.embed(
            base_url=settings.ai_embedding_vision_base_url,
            api_key=settings.ai_embedding_vision_api_key,
            model=settings.ai_embedding_vision_model,
            contents=contents,
            expected_dimensions=settings.ai_embedding_vision_dimensions,
            _client=_client,
        )
        for row, vector in zip(chunk, vectors, strict=True):
            content_kind = "image+text" if row.alt else "image"
            stmt = (
                pg_insert(ProductEmbedding)
                .values(
                    tenant_id=tenant_id,
                    product_image_id=row.image_id,
                    product_id=row.product_id,
                    vector=vector,
                    model=settings.ai_embedding_vision_model,
                    model_version=model_version,
                    content_kind=content_kind,
                )
                .on_conflict_do_update(
                    index_elements=["product_image_id", "model", "model_version"],
                    set_={"vector": vector, "content_kind": content_kind},
                )
            )
            await session.execute(stmt)
            indexed += 1
    await session.flush()
    return {
        "indexed": indexed,
        "batches": (len(rows) + batch_size - 1) // batch_size,
    }
