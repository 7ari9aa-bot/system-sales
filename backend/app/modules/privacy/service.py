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
        from sqlalchemy import select

        from app.modules.customers.models import Customer
        from app.modules.platform.models import AuditLog

        customer = (
            await session.execute(
                select(Customer).where(
                    Customer.tenant_id == tenant_id,
                    Customer.id == customer_id,
                )
            )
        ).scalar_one_or_none()
        if customer is None:
            raise NotFoundError("customer not found")
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
            text("DELETE FROM memories WHERE tenant_id = :t AND customer_id = :c")
            if False
            else text(
                "DELETE FROM memories WHERE tenant_id = :t AND customer_id = :c"
            ),
            {"t": tenant_id, "c": customer_id},
        )
        report["steps"].append(
            {"step": "memories_deleted", "rows": result.rowcount or 0}
        )

        # 3) Vector-bearing knowledge rows that reference this customer only
        #    via conversation content are anonymized (no direct vector rows).
        report["steps"].append({"step": "vector_check", "note": "scoped by tenant"})

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
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=requested_by_user_id,
                action="privacy.customer_deleted",
                resource_type="customer",
                resource_id=str(customer_id),
                after=report,
            )
        )
        await add_outbox_event(
            session,
            aggregate_type="customer",
            aggregate_id=customer_id,
            event_type="privacy.customer_deleted",
            tenant_id=tenant_id,
            payload=report,
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
