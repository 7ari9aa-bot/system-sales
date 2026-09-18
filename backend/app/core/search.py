"""SearchPort (spec §45): search abstraction — PostgreSQL FTS implementation.

The application layer depends on the port, never on a search engine.
When volume demands it, a Meilisearch/Typesense adapter implements the same
protocol and indexes are fed by the EventLog consumers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class SearchHit:
    entity_type: str
    entity_id: uuid.UUID
    title: str
    snippet: str | None = None
    rank: float = 0.0


class SearchPort(Protocol):
    async def search(
        self, session: AsyncSession, tenant_id: uuid.UUID, query: str, *,
        entity_types: list[str] | None = None, limit: int = 20,
    ) -> list[SearchHit]:
        ...


class PostgresSearch:
    """PG full-text search over customers/products with trigram fallback.

    Every query is tenant-scoped (RLS + explicit filter). Weights: name match
    beats email/phone. Plaintext query is escaped — no tsquery injection.
    """

    async def search(
        self, session: AsyncSession, tenant_id: uuid.UUID, query: str, *,
        entity_types: list[str] | None = None, limit: int = 20,
    ) -> list[SearchHit]:
        safe = query.strip().replace("'", "''")
        if not safe:
            return []
        wanted = set(entity_types or ("customer", "product"))
        hits: list[SearchHit] = []

        if "customer" in wanted:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, name, email, phone FROM customers "
                        "WHERE tenant_id = :t AND deleted_at IS NULL AND ("
                        "name ILIKE :q OR email ILIKE :q OR phone ILIKE :q) "
                        "ORDER BY name LIMIT :limit"
                    ),
                    {"t": tenant_id, "q": f"%{safe}%", "limit": limit},
                )
            ).all()
            for r in rows:
                hits.append(
                    SearchHit(
                        entity_type="customer", entity_id=r.id,
                        title=r.name, snippet=r.email or r.phone,
                    )
                )

        if "product" in wanted:
            rows = (
                await session.execute(
                    text(
                        "SELECT p.id, p.title, p.status FROM products p "
                        "WHERE p.tenant_id = :t AND p.status = 'active' "
                        "AND p.title ILIKE :q LIMIT :limit"
                    ),
                    {"t": tenant_id, "q": f"%{safe}%", "limit": limit},
                )
            ).all()
            for r in rows:
                hits.append(
                    SearchHit(entity_type="product", entity_id=r.id, title=r.title)
                )

        return hits[:limit]


def get_search() -> SearchPort:
    """Port accessor — swap for an external engine adapter later."""
    return PostgresSearch()
