"""§158 — memory write governance.

A memory claim must own its full provenance — source, actor, created_at,
verified_at, confidence — and staff must be able to review, edit, delete and
INVALIDATE it. The model carried source/verified_at/confidence (c5c6fc1ae836)
but had no actor (who recorded this?) and no way to take a memory out of
service: the AI runtime keeps recalling every row forever, expired or not,
because add_memory never stores an expiry and search_memory never filters on
one. These tests pin the missing half before it is implemented.

DB cases are CI-only (no local Postgres); the static model check is the local
RED. Embeddings are stubbed the same way test_ai_knowledge.py stubs them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.ai import gateway as ai_gateway
from app.modules.ai.knowledge import add_memory, search_memory
from app.modules.ai.models import Memory
from app.modules.ai.providers import EmbeddingProvider

VECTOR_DIM = 1536


class _ConfiguredSettings:
    ai_provider_primary = "openai"
    ai_api_key_primary = "test-key"
    ai_base_url_primary = "https://api.test/v1"
    ai_model_primary = "text-embedding-test"


def _patch_fixed_embeddings(monkeypatch, value: float = 0.01) -> None:
    async def fake_embed(self, *, base_url, api_key, model, texts, _client=None, dimensions=None):
        return [[value] * VECTOR_DIM for _ in texts]

    monkeypatch.setattr(EmbeddingProvider, "embed", fake_embed)


# ---------------------------------------------------------------------------
# 1. The claim owns its actor and a lifecycle state (§158)
# ---------------------------------------------------------------------------


def test_memory_model_declares_actor_and_status_columns() -> None:
    """RED (static, runs everywhere): actor_id answers "who recorded this",
    status answers "is it still in service" — invalidate must be expressible
    without deleting the audit trail."""
    columns = set(Memory.__table__.c.keys())
    assert {"actor_id", "status", "invalidated_at"} <= columns


async def test_add_memory_stamps_actor_and_defaults_active(db, tenant_ctx) -> None:
    memory = await add_memory(
        db,
        tenant_ctx.tenant_id,
        customer_id=None,
        conversation_id=None,
        kind="fact",
        content="Customer asked for invoice in EUR",
        actor_id=tenant_ctx.user.id,
    )
    assert memory.actor_id == tenant_ctx.user.id
    assert memory.status == "active"
    assert memory.invalidated_at is None


# ---------------------------------------------------------------------------
# 2. Recall filters what governance marks out of service (§158)
# ---------------------------------------------------------------------------


async def _seed_recallable(db, tenant_ctx, monkeypatch) -> Memory:
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _ConfiguredSettings())
    _patch_fixed_embeddings(monkeypatch, value=0.02)
    memory = await add_memory(
        db,
        tenant_ctx.tenant_id,
        customer_id=None,
        conversation_id=None,
        kind="preference",
        content="prefers blue",
        embedding=[0.02] * VECTOR_DIM,
    )
    results = await search_memory(db, tenant_ctx.tenant_id, "blue")
    assert [m.id for m, _ in results] == [memory.id]
    return memory


async def test_search_memory_excludes_invalidated(db, tenant_ctx, monkeypatch) -> None:
    memory = await _seed_recallable(db, tenant_ctx, monkeypatch)
    memory.status = "invalidated"
    memory.invalidated_at = datetime.now(UTC)
    await db.flush()
    assert await search_memory(db, tenant_ctx.tenant_id, "blue") == []


async def test_search_memory_excludes_expired(db, tenant_ctx, monkeypatch) -> None:
    """retention (§38): a memory past expires_at is dead to recall —
    add_memory must be able to set the expiry and search must honour it."""
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _ConfiguredSettings())
    _patch_fixed_embeddings(monkeypatch, value=0.02)
    now = datetime.now(UTC)
    dead = await add_memory(
        db,
        tenant_ctx.tenant_id,
        customer_id=None,
        conversation_id=None,
        kind="fact",
        content="one-hour voucher",
        embedding=[0.02] * VECTOR_DIM,
        expires_at=now - timedelta(hours=1),
    )
    alive = await add_memory(
        db,
        tenant_ctx.tenant_id,
        customer_id=None,
        conversation_id=None,
        kind="fact",
        content="allergy to peanuts",
        embedding=[0.02] * VECTOR_DIM,
        expires_at=now + timedelta(days=30),
    )
    found = {m.id for m, _ in await search_memory(db, tenant_ctx.tenant_id, "voucher allergy")}
    assert dead.id not in found
    assert alive.id in found


async def test_search_memory_still_scopes_by_tenant_and_customer(
    db, tenant_ctx, monkeypatch
) -> None:
    """The governance filters must not widen the old scope: another tenant's
    rows stay invisible (RLS + explicit filter), another customer's rows stay
    out when a customer scope is requested."""
    await _seed_recallable(db, tenant_ctx, monkeypatch)
    other = uuid.uuid4()
    results = await search_memory(db, tenant_ctx.tenant_id, "blue", customer_id=other)
    assert results == []
