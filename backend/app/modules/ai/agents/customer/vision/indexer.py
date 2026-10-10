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

import logging
import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.storage import get_storage
from app.modules.ai.agents.customer.vision.retrieval import MODEL_VERSION
from app.modules.ai.models import ProductEmbedding
from app.modules.ai.providers import MultimodalContent
from app.modules.ai.tools import sellable_product_statuses

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.modules.ai.providers import MultimodalEmbeddingProvider

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

# Reconciliation variant: ONLY images lacking an embedding for the CURRENT
# model+version. A model change empties the matching set (new model_version
# matches nothing) and the sweep re-indexes the whole catalog by itself —
# the same lever a manual full re-index used to pull.
_IMAGES_MISSING_SQL = sa.text(
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
      AND NOT EXISTS (
          SELECT 1 FROM product_embeddings pe
          WHERE pe.product_image_id = pi.id
            AND pe.model = :model
            AND pe.model_version = :model_version
      )
    ORDER BY pi.id
    """
)


async def index_product_images(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    batch_size: int = 16,
    model_version: str = MODEL_VERSION,
    only_missing: bool = False,
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
    statuses = sorted(sellable_product_statuses())

    params: dict = {"tenant_id": str(tenant_id), "sellable": statuses}
    if only_missing:
        params.update(model=settings.ai_embedding_vision_model, model_version=model_version)
        rows = (await session.execute(_IMAGES_MISSING_SQL, params)).all()
    else:
        rows = (await session.execute(_IMAGES_SQL, params)).all()

    indexed = 0
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        contents = []
        for row in chunk:
            image_url = get_storage().resolve_product_image_url(row.url, tenant_id=tenant_id)
            if row.alt:
                contents.append(MultimodalContent(image=image_url, text=row.alt))
            else:
                contents.append(MultimodalContent(image=image_url))
        if _provider is not None:
            vectors = await _provider.embed(
                base_url=settings.ai_embedding_vision_base_url,
                api_key=settings.ai_embedding_vision_api_key,
                model=settings.ai_embedding_vision_model,
                contents=contents,
                expected_dimensions=settings.ai_embedding_vision_dimensions,
                _client=_client,
            )
        else:
            # Governed default (see retrieval): budget, egress, breaker, record.
            from app.modules.ai.gateway import AIGateway

            vectors = await AIGateway().embed_vision(
                session, tenant_id, contents=contents, _client=_client
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


async def sweep_unindexed_product_images(*, batch_size: int = 16) -> int:
    """6.3's operational half: keep the catalog's embeddings current FOREVER.

    ``index_product_images`` existed only as a manual CLI, so production sat
    at images=1 / embeddings=0 — the vision feature silently matched nothing.
    This sweep enumerates every tenant holding sellable product images that
    lack an embedding for the CURRENT model, indexes them through the
    governed gateway (budget, egress, breaker, record), and commits per
    tenant so one tenant's provider failure cannot roll the others back.

    Idempotent by construction: the ``only_missing`` selection plus the
    UNIQUE (image, model, version) upsert mean the hourly run is the initial
    backfill, the reconciliation for failed batches, and the model-change
    re-index — the same lever a manual full re-index used to pull.
    """
    import logging

    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.db import SessionLocal, bind_tenant

    logger = logging.getLogger(__name__)
    settings = get_settings()
    statuses = sorted(sellable_product_statuses())
    indexed_total = 0

    # The enumeration is CROSS-TENANT by definition, and product_images is a
    # tenant-scoped RLS table: an unbound app-role session sees zero rows.
    # Catalog enumeration therefore rides the ADMIN connection (the same role
    # the migration itself runs under); per-tenant indexing stays on the app
    # role with the GUC bound.
    admin_engine = create_async_engine(settings.database_url_admin)
    try:
        async with admin_engine.connect() as conn:
            tenant_ids = (
                (
                    await conn.execute(
                        sa.text(
                            """
                        SELECT DISTINCT pi.tenant_id
                        FROM product_images pi
                        JOIN products p ON p.id = pi.product_id
                        WHERE p.status = ANY(:sellable)
                          AND pi.url IS NOT NULL
                          AND pi.url <> ''
                          AND NOT EXISTS (
                              SELECT 1 FROM product_embeddings pe
                              WHERE pe.product_image_id = pi.id
                                AND pe.model = :model
                                AND pe.model_version = :model_version
                          )
                        """
                        ),
                        {
                            "sellable": statuses,
                            "model": settings.ai_embedding_vision_model,
                            "model_version": MODEL_VERSION,
                        },
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await admin_engine.dispose()

    for tenant_id in tenant_ids:
        try:
            async with SessionLocal() as session:
                await bind_tenant(session, tenant_id)
                stats = await index_product_images(
                    session,
                    tenant_id,
                    batch_size=batch_size,
                    only_missing=True,
                )
                await session.commit()
                indexed_total += stats["indexed"]
        except Exception:  # noqa: BLE001 — one tenant's provider must not stop the rest
            logger.warning("vision.indexing_sweep_failed tenant=%s", tenant_id, exc_info=True)
    return indexed_total
