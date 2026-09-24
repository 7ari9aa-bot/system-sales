"""PRIVACY services — deletion propagation (§172) + data subject requests.

Deletion chain (EVERY step, never a bare DELETE):
    Application Service → policy check → domain deletion (tombstone)
    → derived data (memories, vectors, transcripts) → audit → events.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.events.writer import add_outbox_event
from app.modules.privacy.models import DataSubjectRequest


class DeletionService:
    @staticmethod
    async def propagate_customer_deletion(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        requested_by_user_id: uuid.UUID | None = None,
        reason: str = "data_subject_request",
    ) -> dict:
        """Full deletion propagation for one customer (spec §172 order).

        Returns a report of what was deleted where — auditable proof.
        """

        from app.core.audit import write_audit_row
        from app.modules.customers.service import CustomerService

        customer = await CustomerService.get_for_erasure(session, tenant_id, customer_id)
        if customer.deleted_at is not None:
            raise ValidationError("customer already deleted")

        report: dict = {"customer_id": str(customer_id), "steps": []}

        # 1) Domain deletion — tombstone (§143), keeps referential history
        customer.deleted_at = datetime.now(UTC)
        customer.deleted_by = requested_by_user_id
        customer.deletion_reason = reason
        customer.is_blocked = True
        report["steps"].append({"step": "domain_tombstone", "done": True})

        # 2) Derived data: AI memories (hard delete — §131 minimal retention)
        result = await session.execute(
            text("DELETE FROM memories WHERE tenant_id = :t AND customer_id = :c"),
            {"t": tenant_id, "c": customer_id},
        )
        report["steps"].append(
            {"step": "memories_deleted", "rows": result.rowcount or 0}
        )

        # §131: delete knowledge chunks that carry this customer's conversation
        # content from the vector store. These are the embeddings used for
        # retrieval — they must be purged, not just the memories table.
        # knowledge_chunks may not exist yet (fail open). A failed DELETE
        # would ABORT the whole transaction — the except block cannot un-poison
        # it — so probe with to_regclass first, which never raises.
        chunks_exist = (
            await session.execute(
                text("SELECT to_regclass('public.knowledge_chunks') IS NOT NULL")
            )
        ).scalar()
        if chunks_exist:
            result = await session.execute(
                text(
                    "DELETE FROM knowledge_chunks kc "
                    "USING conversations c "
                    "WHERE kc.conversation_id = c.id "
                    "AND c.tenant_id = :t AND c.customer_id = :c"
                ),
                {"t": tenant_id, "c": customer_id},
            )
            report["steps"].append(
                {"step": "vector_chunks_deleted", "rows": result.rowcount or 0}
            )
        else:
            report["steps"].append(
                {"step": "vector_chunks_deleted", "rows": 0, "note": "table not found"}
            )

        # §131: remove from search index. For PostgresSearch this is a no-op
        # (the tombstone in step 1 already hides the row). For an external
        # search engine, this deletes the customer document from the index.
        try:
            from app.core.search import get_search

            search = get_search()
            removed = await search.delete_from_index(
                session, tenant_id, entity_type="customer", entity_id=customer_id
            )
            report["steps"].append(
                {"step": "search_index_purged", "rows": removed}
            )
        except Exception:
            report["steps"].append(
                {
                    "step": "search_index_purged",
                    "note": "failed",
                    "error": "search port unavailable",
                }
            )

        # §131: anonymize message transcripts — don't hard-delete (referential
        # integrity for orders/conversations), but strip PII from body text.
        result = await session.execute(
            text(
                "UPDATE messages SET body = '[REDACTED]', media_url = NULL "
                "WHERE tenant_id = :t AND conversation_id IN ("
                "  SELECT id FROM conversations WHERE customer_id = :c"
                ")"
            ),
            {"t": tenant_id, "c": customer_id},
        )
        report["steps"].append(
            {"step": "transcripts_anonymized", "rows": result.rowcount or 0}
        )

        # §131: emit an event so n8n and other integrations can purge their
        # own copies of this customer's data (CRM sync, marketing tools, etc.)
        await add_outbox_event(
            session,
            aggregate_type="customer",
            aggregate_id=customer_id,
            event_type="privacy.customer_purge_required",
            tenant_id=tenant_id,
            payload={
                "customer_id": str(customer_id),
                "reason": reason,
                "requested_by": str(requested_by_user_id) if requested_by_user_id else None,
            },
            # §153: the customer row's real version (VersionMixin), not a literal.
            aggregate_version=customer.version,
        )

        # 4) Close pending data subject requests for this customer
        result = await session.execute(
            text(
                "UPDATE data_subject_requests SET status = 'completed', "
                "completed_at = now() WHERE tenant_id = :t AND customer_id = :c "
                "AND status IN ('pending', 'in_progress')"
            ),
            {"t": tenant_id, "c": customer_id},
        )
        report["steps"].append({"step": "dsr_closed", "rows": result.rowcount or 0})

        # 5) Audit + event
        await write_audit_row(
            session,
            tenant_id,
            requested_by_user_id,
            action="privacy.customer_deleted",
            resource_type="customer",
            resource_id=str(customer_id),
            after=report,
        )
        await add_outbox_event(
            session,
            aggregate_type="customer",
            aggregate_id=customer_id,
            event_type="privacy.customer_deleted",
            tenant_id=tenant_id,
            payload=report,
            # §153: same customer aggregate — the row's real version (the
            # tombstone path does not bump it), never a fabricated literal.
            aggregate_version=customer.version,
        )
        await session.flush()
        return report


class DataRequestService:
    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        customer_id: uuid.UUID,
        request_type: str,
        requested_by_user_id: uuid.UUID | None = None,
    ) -> DataSubjectRequest:
        if request_type not in ("access", "export", "delete", "rectify"):
            raise ValidationError(f"invalid request type: {request_type}")
        request = DataSubjectRequest(
            tenant_id=tenant_id,
            customer_id=customer_id,
            request_type=request_type,
            requested_by_user_id=requested_by_user_id,
            status="pending",
        )
        session.add(request)
        await session.flush()
        return request
