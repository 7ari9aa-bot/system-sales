"""PRIVACY services — deletion propagation (§172) + data subject requests.

Deletion chain (EVERY step, never a bare DELETE):
    Application Service → policy check → domain deletion (tombstone)
    → derived data (memories, vectors, transcripts) → audit → events.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
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

        from app.modules.customers.service import CustomerService
        from app.modules.platform.service import AuditService

        customer = await CustomerService.get(session, tenant_id, customer_id)
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
            aggregate_version=1,
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
        await AuditService.write(
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
            aggregate_version=3,
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


class TenantRestoreService:
    """§164 — Tenant-scoped restore.

    When a tenant is suspended (§160) and later reactivated, or when a
    destructive operation (mass deletion, migration rollback) happened
    and needs to be reversed, this service restores the tenant's data
    from a backup snapshot.

    The restore is TENANT-SCOPED: it never touches another tenant's
    rows. This is enforced by RLS (the session is bound to the tenant
    before any restore SQL runs) and by the explicit tenant_id filter
    in every statement.

    The restore is logged as a security event (break-glass style) so
    there is always an audit trail that a restore happened, who did it,
    and why.
    """

    @staticmethod
    async def restore_from_snapshot(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        snapshot_ref: str,
        requested_by_user_id: uuid.UUID | None = None,
        reason: str,
    ) -> dict:
        """§164: restore tenant data from a named snapshot.

        This is the entry point for the restore operation. The actual
        data restore (pg_restore, S3 copy, etc.) is performed by the
        infrastructure layer; this service:
        1. Verifies the tenant exists and is suspended (you don't restore
           a live tenant).
        2. Records the restore request in the audit log.
        3. Returns a restore plan (what tables, what snapshot, what window).
        4. The caller (a worker) performs the actual restore and calls
           `mark_restored()` when done.
        """
        from app.modules.identity.models import Tenant
        from app.modules.platform.service import AuditService

        if not reason or len(reason.strip()) < 10:
            raise ValidationError(
                "restore requires a reason of at least 10 characters"
            )

        tenant = (
            await session.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
        ).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("tenant not found")
        if tenant.status != "suspended":
            raise ValidationError(
                f"tenant must be suspended to restore (current: {tenant.status})",
                details={"status": tenant.status},
            )

        # Record the restore request as a security event
        await AuditService.write(
            session,
            tenant_id,
            requested_by_user_id,
            action="tenant.restore_requested",
            resource_type="tenant",
            resource_id=str(tenant_id),
            before={"status": tenant.status},
            after={
                "snapshot_ref": snapshot_ref,
                "reason": reason,
                "requested_by": str(requested_by_user_id) if requested_by_user_id else None,
            },
        )
        await session.flush()

        return {
            "tenant_id": str(tenant_id),
            "snapshot_ref": snapshot_ref,
            "reason": reason,
            "status": "restore_planned",
            "tables": [
                "customers",
                "conversations",
                "messages",
                "orders",
                "order_payments",
                "refunds",
                "memories",
                "attachments",
            ],
        }

    @staticmethod
    async def mark_restored(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        requested_by_user_id: uuid.UUID | None = None,
    ) -> dict:
        """§164: mark the tenant as restored (reactivate after restore).

        Called by the worker after the data restore completes. Flips the
        tenant status from 'suspended' back to 'active' and logs the event.
        """
        from app.modules.identity.models import Tenant
        from app.modules.platform.service import AuditService

        tenant = (
            await session.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
        ).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("tenant not found")

        previous_status = tenant.status
        tenant.status = "active"

        await AuditService.write(
            session,
            tenant_id,
            requested_by_user_id,
            action="tenant.restored",
            resource_type="tenant",
            resource_id=str(tenant_id),
            before={"status": previous_status},
            after={"status": "active"},
        )
        await session.flush()
        return {
            "tenant_id": str(tenant_id),
            "status": "active",
            "previous_status": previous_status,
        }
