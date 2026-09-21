"""Spec §45 — Search indexer: EventLog consumer for external search engines.

When volume demands a dedicated search engine (Meilisearch, Typesense,
OpenSearch), this indexer subscribes to the EventLog and feeds the index.
The SearchPort abstraction means the application layer never knows which
engine is running.

For now, the default PostgresSearch implementation is sufficient. This
module provides the adapter scaffolding so the switch is a config change,
not a code rewrite.
"""

from __future__ import annotations

import logging
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.search import SearchHit

logger = logging.getLogger(__name__)


class SearchIndexPort(Protocol):
    """External search engine index port (§45).

    Implementations: MeilisearchIndex, TypesenseIndex, OpenSearchIndex.
    The application layer never knows which engine — only the port.
    """

    async def upsert_document(
        self,
        tenant_id: uuid.UUID,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
        document: dict,
        permissions: dict | None = None,
    ) -> None:
        """Add or update a document in the search index."""
        ...

    async def delete_document(
        self,
        tenant_id: uuid.UUID,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
    ) -> None:
        """Remove a document from the search index (§131 deletion propagation)."""
        ...

    async def search(
        self,
        tenant_id: uuid.UUID,
        query: str,
        *,
        entity_types: list[str] | None = None,
        limit: int = 20,
        filters: dict | None = None,
    ) -> list[SearchHit]:
        """Search the external index. Results are tenant-scoped."""
        ...


class SearchIndexerService:
    """§45: consumes domain events and feeds the search index.

    Listens to the EventLog for entity mutations and upserts/deletes
    documents in the external search engine. This is async — the search
    index is eventually consistent (§137).

    If no external engine is configured (PostgresSearch is the default),
    this service is a no-op — PostgreSQL FTS handles search inline.
    """

    # Event type → index action mapping
    INDEX_EVENTS = {
        "customer.created": "upsert",
        "customer.updated": "upsert",
        "customer.merged": "upsert",
        "customer.deleted": "delete",
        "product.created": "upsert",
        "product.updated": "upsert",
        "product.deleted": "delete",
        "order.created": "upsert",
        "order.updated": "upsert",
    }

    def __init__(self, index: SearchIndexPort | None = None):
        self._index = index

    @property
    def is_active(self) -> bool:
        """True when an external search engine is configured."""
        return self._index is not None

    async def handle_event(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        payload: dict,
    ) -> None:
        """Process a domain event and update the search index.

        No-op when no external engine is configured.
        """
        if self._index is None:
            return

        action = self.INDEX_EVENTS.get(event_type)
        if action is None:
            return

        if action == "delete":
            await self._index.delete_document(
                tenant_id,
                entity_type=aggregate_type,
                entity_id=aggregate_id,
            )
        elif action == "upsert":
            document = await self._build_document(
                session, tenant_id,
                entity_type=aggregate_type,
                entity_id=aggregate_id,
                payload=payload,
            )
            if document:
                await self._index.upsert_document(
                    tenant_id,
                    entity_type=aggregate_type,
                    entity_id=aggregate_id,
                    document=document,
                    permissions={"tenant_id": str(tenant_id)},
                )

    async def _build_document(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
        payload: dict,
    ) -> dict | None:
        """Build a search document from the entity.

        Uses the payload from the event log when possible; falls back to
        a DB read if the payload is incomplete.
        """
        if entity_type == "customer":
            from sqlalchemy import select

            from app.modules.customers.models import Customer

            customer = (
                await session.execute(
                    select(Customer).where(
                        Customer.tenant_id == tenant_id,
                        Customer.id == entity_id,
                    )
                )
            ).scalar_one_or_none()
            if customer is None or customer.deleted_at is not None:
                return None
            return {
                "entity_type": "customer",
                "entity_id": str(entity_id),
                "name": customer.name,
                "email": customer.email or "",
                "phone": customer.phone or "",
                "tenant_id": str(tenant_id),
            }

        if entity_type == "product":
            from sqlalchemy import select

            from app.modules.catalog.models import Product

            product = (
                await session.execute(
                    select(Product).where(
                        Product.tenant_id == tenant_id,
                        Product.id == entity_id,
                    )
                )
            ).scalar_one_or_none()
            if product is None:
                return None
            return {
                "entity_type": "product",
                "entity_id": str(entity_id),
                "title": product.title,
                "slug": product.slug or "",
                "tenant_id": str(tenant_id),
            }

        # Generic: use payload
        return {
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "tenant_id": str(tenant_id),
            **payload,
        }
