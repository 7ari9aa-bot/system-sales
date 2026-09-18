"""AI approval workflow (spec §135) — durable human-in-the-loop.

HIGH-risk tool calls create an ApprovalRequest and suspend the run in
WAITING_APPROVAL. Approve → resume; reject/expire → stop. A new customer
message makes pending approvals stale (re-evaluate context, never
auto-continue).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.modules.ai.models import ApprovalRequest

APPROVAL_TTL_MINUTES = 60


class ApprovalService:
    @staticmethod
    async def request(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        run_id: uuid.UUID | None,
        conversation_id: uuid.UUID | None,
        entity_type: str,
        entity_id: str,
        action: str,
        risk_level: str = "HIGH",
        payload: dict | None = None,
        ttl_minutes: int = APPROVAL_TTL_MINUTES,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            tenant_id=tenant_id,
            run_id=run_id,
            conversation_id=conversation_id,
            requested_by="ai",
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            risk_level=risk_level,
            payload=payload or {},
            status="PENDING",
            expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
        )
        session.add(request)
        await session.flush()
        return request

    @staticmethod
    async def decide(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        approval_id: uuid.UUID,
        *,
        decision: str,  # APPROVED | REJECTED | CANCELLED
        decided_by_user_id: uuid.UUID,
        rejection_reason: str | None = None,
    ) -> ApprovalRequest:
        if decision not in ("APPROVED", "REJECTED", "CANCELLED"):
            raise ValidationError(f"invalid decision: {decision}")
        request = (
            await session.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.tenant_id == tenant_id,
                    ApprovalRequest.id == approval_id,
                )
            )
        ).scalar_one_or_none()
        if request is None:
            raise NotFoundError("approval request not found")
        if request.status != "PENDING":
            raise ValidationError(f"approval already {request.status}")
        if (
            request.expires_at is not None
            and request.expires_at < datetime.now(UTC)
        ):
            request.status = "EXPIRED"
            raise ValidationError("approval request expired")

        request.status = decision
        request.approved_by_user_id = decided_by_user_id
        request.decided_at = datetime.now(UTC)
        request.rejection_reason = rejection_reason
        await session.flush()
        return request

    @staticmethod
    async def expire_stale(session: AsyncSession, tenant_id: uuid.UUID) -> int:
        """Maintenance worker: expire PENDING approvals past their TTL."""
        from sqlalchemy import update

        result = await session.execute(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.status == "PENDING",
                ApprovalRequest.expires_at < datetime.now(UTC),
            )
            .values(status="EXPIRED")
        )
        return result.rowcount or 0

    @staticmethod
    async def is_stale_for_conversation(
        session: AsyncSession, conversation_id: uuid.UUID, *, since: datetime
    ) -> bool:
        """True when a new customer message arrived after the approval was
        created — the approval must be re-evaluated, not auto-continued."""
        from app.modules.conversations.models import Message

        newer = (
            await session.execute(
                select(Message.id)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.direction == "inbound",
                    Message.created_at > since,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return newer is not None
