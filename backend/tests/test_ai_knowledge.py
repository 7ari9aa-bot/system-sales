"""Knowledge base + memory tests — pgvector against the real database."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.modules.ai import gateway as ai_gateway
from app.modules.ai.knowledge import (
    add_memory,
    ingest_knowledge,
    search_knowledge,
    search_memory,
)
from app.modules.ai.providers import EmbeddingProvider

VECTOR_DIM = 1536


class _NoModelSettings:
    ai_provider_primary = ""


class _ConfiguredSettings:
    ai_provider_primary = "openai"
    ai_api_key_primary = "test-key"
    ai_base_url_primary = "https://api.test/v1"
    ai_model_primary = "text-embedding-test"


def _patch_fixed_embeddings(monkeypatch, value: float = 0.01) -> None:
    async def fake_embed(self, *, base_url, api_key, model, texts, _client=None):
        return [[value] * VECTOR_DIM for _ in texts]

    monkeypatch.setattr(EmbeddingProvider, "embed", fake_embed)


async def test_ingest_without_embedding_model_stays_pending(db, tenant_ctx, monkeypatch):
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _NoModelSettings())
    item = await ingest_knowledge(
        db, tenant_ctx.tenant_id, title="Shipping policy", content="Ships in 2 days"
    )
    assert item.status == "pending"
    assert item.embedding is None
    assert item.source_type == "text"


async def test_ingest_indexes_with_vector_and_search_finds_it(db, tenant_ctx, monkeypatch):
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _ConfiguredSettings())
    _patch_fixed_embeddings(monkeypatch)

    item = await ingest_knowledge(
        db,
        tenant_ctx.tenant_id,
        title="Return policy",
        content="Customers have 14 days to return items.",
    )
    assert item.status == "indexed"
    assert item.embedding is not None
    assert len(item.embedding) == VECTOR_DIM

    results = await search_knowledge(db, tenant_ctx.tenant_id, "return window", limit=5)
    assert len(results) == 1
    found, distance = results[0]
    assert found.id == item.id
    assert found.title == "Return policy"
    # Identical vectors -> cosine distance ~0 (always within [0, 2]).
    assert 0.0 <= distance <= 2.0


async def test_search_empty_index_returns_empty_list(db, tenant_ctx, monkeypatch):
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _ConfiguredSettings())
    _patch_fixed_embeddings(monkeypatch)
    assert await search_knowledge(db, tenant_ctx.tenant_id, "anything") == []


async def test_knowledge_results_are_tenant_scoped(db, tenant_ctx, monkeypatch):
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _ConfiguredSettings())
    _patch_fixed_embeddings(monkeypatch)
    await ingest_knowledge(
        db, tenant_ctx.tenant_id, title="Tenant A doc", content="belongs to tenant A"
    )
    results = await search_knowledge(db, tenant_ctx.tenant_id, "tenant A")
    assert results
    assert {item.tenant_id for item, _d in results} == {tenant_ctx.tenant_id}


async def test_add_memory_and_search_memory(db, tenant_ctx, monkeypatch):
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _ConfiguredSettings())
    _patch_fixed_embeddings(monkeypatch, value=0.02)

    memory = await add_memory(
        db,
        tenant_ctx.tenant_id,
        customer_id=None,
        conversation_id=None,
        kind="preference",
        content="Customer prefers blue gadgets",
        embedding=[0.02] * VECTOR_DIM,
    )
    assert memory.kind == "preference"
    assert memory.embedding is not None

    results = await search_memory(db, tenant_ctx.tenant_id, "favorite color", limit=3)
    assert len(results) == 1
    found, distance = results[0]
    assert found.id == memory.id
    assert 0.0 <= distance <= 2.0


async def test_add_memory_requires_kind_and_content(db, tenant_ctx):
    memory = await add_memory(
        db,
        tenant_ctx.tenant_id,
        customer_id=None,
        conversation_id=None,
        kind="fact",
        content="No embedding stored",
        embedding=None,
    )
    assert memory.embedding is None

    # Searching with no embedding model configured raises a validation error.
    with pytest.raises(ValidationError, match="embedding"):
        await search_memory(db, tenant_ctx.tenant_id, "anything")
