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

from app.core.sql import like_pattern


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

    async def delete_from_index(
        self, session: AsyncSession, tenant_id: uuid.UUID, *,
        entity_type: str, entity_id: uuid.UUID,
    ) -> int:
        """§131: remove a customer's data from the search index on deletion.

        For PostgresSearch the index is the customers/products table itself
        (soft-deleted rows are filtered by `deleted_at IS NULL`). For an
        external engine (Meilisearch/Typesense) this deletes the document
        from the engine's index. Returns the number of entries removed.
        """
        ...


class PostgresSearch:
    """The §45 adapter that ships: a contains-match over the live tables.

    Tenant-scoped twice over — the RLS GUC and an explicit `tenant_id` filter —
    and the caller's term is data, never a pattern (`like_pattern` escapes the
    `%`/`_` it types and each statement declares the escape character).

    This is NOT full-text search, whatever the name suggests: no tsvector, no
    trigram index, no relevance ranking — customers come back alphabetical and
    products in heap order. The FTS half of §45 is an open gap, not this class.
    """

    async def search(
        self, session: AsyncSession, tenant_id: uuid.UUID, query: str, *,
        entity_types: list[str] | None = None, limit: int = 20,
    ) -> list[SearchHit]:
        term = query.strip()
        if not term:
            return []
        # The pattern is a bound parameter, so it carries the caller's apostrophes
        # as text; the wildcards are ours, and ESCAPE makes theirs literal.
        pattern = like_pattern(term)
        wanted = set(entity_types or ("customer", "product"))
        hits: list[SearchHit] = []

        if "customer" in wanted:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, name, email, phone FROM customers "
                        "WHERE tenant_id = :t AND deleted_at IS NULL AND ("
                        r"name ILIKE :q ESCAPE '\' OR email ILIKE :q ESCAPE '\'"
                        r" OR phone ILIKE :q ESCAPE '\') "
                        "ORDER BY name LIMIT :limit"
                    ),
                    {"t": tenant_id, "q": pattern, "limit": limit},
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
                        r"AND p.title ILIKE :q ESCAPE '\' LIMIT :limit"
                    ),
                    {"t": tenant_id, "q": pattern, "limit": limit},
                )
            ).all()
            for r in rows:
                hits.append(
                    SearchHit(entity_type="product", entity_id=r.id, title=r.title)
                )

        return hits[:limit]

    async def delete_from_index(
        self, session: AsyncSession, tenant_id: uuid.UUID, *,
        entity_type: str, entity_id: uuid.UUID,
    ) -> int:
        """§131: for PostgresSearch the index IS the table. Soft-deleted rows
        are already filtered by `deleted_at IS NULL` in search(). This method
        is a no-op for the PG implementation — the tombstone set by the
        domain layer (step 1 of propagate_customer_deletion) already hides
        the row from search. For an external engine, this would delete the
        document from the engine's index.
        """
        return 0


def get_search() -> SearchPort:
    """Port accessor — swap for an external engine adapter later."""
    return PostgresSearch()
