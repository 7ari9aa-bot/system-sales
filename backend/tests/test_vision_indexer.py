"""Vision indexer tests (spec §12.6) — real upserts, mocked embedding.

Pins the contract retrieval depends on: only sellable products' images get
embedded, alt text rides the item as image+text, and re-running is an
idempotent upsert — same totals, no duplicate rows, same vectors.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.modules.ai.agents.customer.vision.indexer import index_product_images
from app.modules.ai.models import ProductEmbedding
from app.modules.catalog.models import Product, ProductImage


def _unit(dim: int) -> list[float]:
    vector = [0.0] * 768
    vector[dim] = 1.0
    return vector


class _ScriptedEmbedding:
    """Returns one distinct vector per item — keyed by the item's index."""

    def __init__(self):
        self.calls: list[int] = []

    async def embed(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        contents: list,
        expected_dimensions: int | None = None,
        _client=None,
    ):
        self.calls.append(len(contents))
        return [_unit(len(self.calls) + i) for i in range(len(contents))]


async def _seed_product(db, tenant_id, *, title: str, status: str = "active"):
    product = Product(
        tenant_id=tenant_id,
        title=title,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}",
        status=status,
    )
    db.add(product)
    await db.flush()
    return product


async def _seed_image(db, tenant_id, product: Product, url: str, alt: str | None = None):
    image = ProductImage(tenant_id=tenant_id, product_id=product.id, url=url, alt=alt)
    db.add(image)
    await db.flush()
    return image


async def _count(db, tenant_id) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(ProductEmbedding)
            .where(ProductEmbedding.tenant_id == tenant_id)
        )
    ).scalar_one()


async def test_embeds_sellable_only_and_records_content_kind(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    product = await _seed_product(db, tenant_id, title="Blue Abaya")
    with_alt = await _seed_image(db, tenant_id, product, "https://cdn.test/a.png", alt="abaya كحلي")
    plain = await _seed_image(db, tenant_id, product, "https://cdn.test/b.png")
    draft = await _seed_product(db, tenant_id, title="Hidden", status="draft")
    await _seed_image(db, tenant_id, draft, "https://cdn.test/hidden.png")

    provider = _ScriptedEmbedding()
    stats = await index_product_images(db, tenant_id, _provider=provider)

    assert stats == {"indexed": 2, "batches": 1}
    assert await _count(db, tenant_id) == 2

    rows = {
        r.product_image_id: r
        for r in (
            await db.execute(
                select(ProductEmbedding).where(ProductEmbedding.tenant_id == tenant_id)
            )
        ).scalars()
    }
    assert rows[with_alt.id].content_kind == "image+text"
    assert rows[plain.id].content_kind == "image"
    assert rows[with_alt.id].model_version == "1"


async def test_rerun_is_idempotent_no_duplicate_rows(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    product = await _seed_product(db, tenant_id, title="Blue Abaya")
    await _seed_image(db, tenant_id, product, "https://cdn.test/a.png")
    await _seed_image(db, tenant_id, product, "https://cdn.test/b.png")

    provider = _ScriptedEmbedding()
    first = await index_product_images(db, tenant_id, _provider=provider)
    second = await index_product_images(db, tenant_id, _provider=provider)

    assert first == {"indexed": 2, "batches": 1}
    assert second == first
    assert await _count(db, tenant_id) == 2  # upsert, never duplicate rows


async def test_batching_one_provider_call_per_chunk(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    product = await _seed_product(db, tenant_id, title="Batched")
    for i in range(3):
        await _seed_image(db, tenant_id, product, f"https://cdn.test/{i}.png")

    provider = _ScriptedEmbedding()
    stats = await index_product_images(db, tenant_id, batch_size=2, _provider=provider)

    assert stats == {"indexed": 3, "batches": 2}
    assert provider.calls == [2, 1]
