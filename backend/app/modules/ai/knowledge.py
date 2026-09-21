"""Knowledge base + customer memories with pgvector embeddings.

Ingest stores the row first (status pending), then tries to embed it through
the gateway's ``embedding`` alias. When no embedding model is configured the
item simply stays pending with no vector — ingestion must not fail because AI
is not wired up. Search embeds the query and ranks by cosine distance.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import KnowledgeItem, Memory
from app.modules.conversations import models as _conversations_models  # noqa: F401
from app.modules.customers import models as _customers_models  # noqa: F401

# Registering the conversations/customers tables in the shared metadata makes
# Memory's FKs (customers.id, conversations.id) resolvable in processes that
# only use the AI module.


async def _embed(
    session: AsyncSession, tenant_id: uuid.UUID, texts: list[str]
) -> list[list[float]]:
    gateway = AIGateway()
    return await gateway.embed(session, tenant_id, texts=texts)


async def ingest_knowledge(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    title: str,
    content: str,
    source_type: str = "text",
    source_ref: str | None = None,
) -> KnowledgeItem:
    """Store a knowledge item; embed+index when an embedding model exists."""
    item = KnowledgeItem(
        tenant_id=tenant_id,
        title=title,
        source_type=source_type,
        source_ref=source_ref,
        content=content,
        status="pending",
    )
    session.add(item)
    await session.flush()

    try:
        vectors = await _embed(session, tenant_id, [content])
    except ValidationError:
        # No embedding model configured for this tenant — keep it pending.
        return item
    item.embedding = vectors[0]
    item.status = "indexed"
    await session.flush()
    return item


async def search_knowledge(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    query: str,
    *,
    limit: int = 5,
    visibility: str | None = "customer_facing",
) -> list[tuple[KnowledgeItem, float]]:
    """Semantic search over the tenant's indexed knowledge items.

    §157: retrieval is tenant- AND visibility-scoped — the AI customer
    context only sees customer_facing items by default; staff surfaces
    pass visibility=None for everything.
    """
    vectors = await _embed(session, tenant_id, [query])
    distance = KnowledgeItem.embedding.cosine_distance(vectors[0])
    stmt = (
        select(KnowledgeItem, distance)
        .where(
            KnowledgeItem.tenant_id == tenant_id,
            KnowledgeItem.embedding.is_not(None),
            KnowledgeItem.status == "indexed",
        )
        .order_by(distance)
        .limit(limit)
    )
    if visibility is not None:
        stmt = stmt.where(KnowledgeItem.visibility == visibility)
    rows = (await session.execute(stmt)).all()
    return [(row[0], float(row[1])) for row in rows]


async def add_memory(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    customer_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None,
    kind: str,
    content: str,
    embedding: list[float] | None = None,
    source: str = "customer_stated",
    confidence: float = 0.5,
    verified_at: datetime | None = None,
) -> Memory:
    """Persist a customer/conversation memory with governed provenance (§158).

    ``source`` distinguishes customer-stated facts from AI-inferred summaries:
     - customer_stated: the customer explicitly said this
     - agent_inferred: the AI deduced/summarized this from the conversation
     - system_verified: a system process confirmed this (e.g., order delivered)
     - staff_entered: a human staff member recorded this

    ``confidence`` (0.0–1.0) reflects how trustworthy the memory is.
    ``verified_at`` is set when the memory is confirmed by a system event.
    """
    memory = Memory(
        tenant_id=tenant_id,
        customer_id=customer_id,
        conversation_id=conversation_id,
        kind=kind,
        content=content,
        embedding=embedding,
        source=source,
        confidence=confidence,
        verified_at=verified_at,
    )
    session.add(memory)
    await session.flush()
    return memory


async def search_memory(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    query: str,
    *,
    customer_id: uuid.UUID | None = None,
    limit: int = 5,
) -> list[tuple[Memory, float]]:
    """Semantic search over memories, optionally scoped to one customer."""
    vectors = await _embed(session, tenant_id, [query])
    distance = Memory.embedding.cosine_distance(vectors[0])
    stmt = (
        select(Memory, distance)
        .where(
            Memory.tenant_id == tenant_id,
            Memory.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(limit)
    )
    if customer_id is not None:
        stmt = stmt.where(Memory.customer_id == customer_id)
    rows = (await session.execute(stmt)).all()
    return [(row[0], float(row[1])) for row in rows]
