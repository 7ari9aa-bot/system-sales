"""Vision retrieval tests (spec §12.1) — real pgvector, mocked embedding.

The DB side is what can silently break this pipeline (a vector cast, a
DISTINCT ON grouping, the per-product cap), so these run against real
PostgreSQL with the embedding provider mocked: one fixed query vector per
test, seeded product images at known cosine distances.
"""

from __future__ import annotations

import uuid

from app.modules.ai.agents.customer.vision.retrieval import retrieve_candidates
from app.modules.ai.models import ProductEmbedding
from app.modules.catalog.models import Product, ProductImage


def _unit(dim: int, value: float = 1.0) -> list[float]:
    """A 768-dim unit vector along ``dim`` — cosine distances stay exact."""
    vector = [0.0] * 768
    vector[dim] = value
    return vector


async def _seed_product(db, tenant_id, *, title: str, status: str = "active") -> Product:
    product = Product(
        tenant_id=tenant_id,
        title=title,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}",
        status=status,
    )
    db.add(product)
    await db.flush()
    return product


async def _seed_image(db, tenant_id, product: Product, url: str) -> ProductImage:
    image = ProductImage(tenant_id=tenant_id, product_id=product.id, url=url)
    db.add(image)
    await db.flush()
    return image


async def _seed_embedding(
    db, tenant_id, image: ProductImage, vector: list[float]
) -> ProductEmbedding:
    embedding = ProductEmbedding(
        tenant_id=tenant_id,
        product_image_id=image.id,
        product_id=image.product_id,
        vector=vector,
        model="tongyi-embedding-vision-flash",
        model_version="1",
        content_kind="image",
    )
    db.add(embedding)
    await db.flush()
    return embedding


class _FixedEmbedding:
    """MultimodalEmbeddingProvider-shaped stub returning one scripted vector."""

    def __init__(self, vector: list[float]):
        self.vector = vector
        self.calls: list[list] = []

    async def embed(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        contents: list,
        expected_dimensions: int | None = None,
        _client=None,
    ) -> list[list[float]]:
        self.calls.append([item.payload() for item in contents])
        return [self.vector]


async def test_best_image_per_product_and_rank_by_distance(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    near = await _seed_product(db, tenant_id, title="Blue Abaya")
    far = await _seed_product(db, tenant_id, title="Red Dress")

    near_close = await _seed_image(db, tenant_id, near, "https://cdn.test/near-1.png")
    near_far = await _seed_image(db, tenant_id, near, "https://cdn.test/near-2.png")
    far_image = await _seed_image(db, tenant_id, far, "https://cdn.test/far-1.png")
    await _seed_embedding(db, tenant_id, near_close, _unit(0))  # distance 0.0
    await _seed_embedding(db, tenant_id, near_far, _unit(1, 0.8))  # distance 0.2
    await _seed_embedding(db, tenant_id, far_image, _unit(2))  # distance 1.0

    candidates = await retrieve_candidates(
        db, tenant_id, image_url="https://c.test/q.png", _embedding=_FixedEmbedding(_unit(0))
    )

    assert [c.product_title for c in candidates] == ["Blue Abaya", "Red Dress"]
    # The best image per product wins: near-1 (distance 0), never near-2.
    assert candidates[0].image_url == "https://cdn.test/near-1.png"
    assert candidates[0].retrieval_rank == 1
    assert candidates[1].retrieval_rank == 2


async def test_query_rides_image_plus_text_hint_in_one_item(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    product = await _seed_product(db, tenant_id, title="Blue Abaya")
    image = await _seed_image(db, tenant_id, product, "https://cdn.test/a.png")
    await _seed_embedding(db, tenant_id, image, _unit(0))

    embedding = _FixedEmbedding(_unit(0))
    await retrieve_candidates(
        db,
        tenant_id,
        image_url="https://c.test/q.png",
        text_hint="abaya كحلي",
        _embedding=embedding,
    )
    # One item carries BOTH the photo and the hint — one vector per item.
    assert embedding.calls == [[{"image": "https://c.test/q.png", "text": "abaya كحلي"}]]


async def test_cap_limits_candidates_and_products_without_embeddings_are_invisible(
    db, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    for rank in range(4):
        product = await _seed_product(db, tenant_id, title=f"Product {rank}")
        image = await _seed_image(
            db, tenant_id, product, f"https://cdn.test/p{rank}.png"
        )
        await _seed_embedding(db, tenant_id, image, _unit(rank))

    # A draft product with NO embedding row (the indexer skips it) must
    # never surface, however close its (nonexistent) vector would be.
    ghost = await _seed_product(db, tenant_id, title="Ghost", status="draft")
    await _seed_image(db, tenant_id, ghost, "https://cdn.test/ghost.png")

    candidates = await retrieve_candidates(
        db,
        tenant_id,
        image_url="https://c.test/q.png",
        max_candidates=2,
        _embedding=_FixedEmbedding(_unit(0)),
    )
    assert len(candidates) == 2
    # Distance 0.0 outranks the tied 1.0s deterministically; the ties
    # themselves may arrive in any order, so only the winner is pinned.
    assert candidates[0].product_title == "Product 0"
    assert all(c.product_title != "Ghost" for c in candidates)


async def test_other_tenants_embeddings_are_invisible(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    product = await _seed_product(db, tenant_id, title="Mine")
    image = await _seed_image(db, tenant_id, product, "https://cdn.test/mine.png")
    await _seed_embedding(db, tenant_id, image, _unit(0))

    other_tenant = uuid.uuid4()
    candidates = await retrieve_candidates(
        db, other_tenant, image_url="https://c.test/q.png", _embedding=_FixedEmbedding(_unit(0))
    )
    assert candidates == []
