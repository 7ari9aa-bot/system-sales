"""AI approval workflow (spec §135) — durable human-in-the-loop.

HIGH-risk tool calls create an ApprovalRequest and suspend the run in
WAITING_APPROVAL. Approve → resume; reject/expire → stop. A new customer
message makes pending approvals stale (re-evaluate context, never
auto-continue).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.modules.ai.models import ApprovalRequest

APPROVAL_TTL_MINUTES = 60


def payload_fingerprint(payload: dict | None) -> str:
    """Stable SHA-256 over a payload, for binding an approval to its arguments.

    Canonicalised (sorted keys, no whitespace, `default=str` for the UUIDs and
    datetimes a tool argument can contain) so the same logical arguments always
    produce the same digest. Review G-02: without this, a resume matched an
    approval on the action NAME alone and would execute whatever arguments the
    run computed the second time around.
    """
    canonical = json.dumps(
        payload or {}, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


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
        payload = payload or {}
        fingerprint = payload_fingerprint(payload)

        # Idempotent: re-running the gate must not pile up duplicate PENDING
        # requests for the same conversation + action + arguments. This matters
        # because a STALE approval is discarded and re-requested, and a resumed
        # run re-enters the gate.
        existing = (
            await session.execute(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.tenant_id == tenant_id,
                    ApprovalRequest.conversation_id == conversation_id,
                    ApprovalRequest.action == action,
                    ApprovalRequest.status == "PENDING",
                    ApprovalRequest.payload_hash == fingerprint,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        request = ApprovalRequest(
            tenant_id=tenant_id,
            run_id=run_id,
            conversation_id=conversation_id,
            requested_by="ai",
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            risk_level=risk_level,
            payload=payload,
            payload_hash=fingerprint,
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
    async def find_granted(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        conversation_id: uuid.UUID | None,
        action: str,
        payload: dict | None = None,
    ) -> ApprovalRequest | None:
        """The unconsumed APPROVED approval that authorizes `action` with THESE
        arguments, if any.

        This is what makes a RESUME work: the run re-runs the gate, finds the
        approval a human already granted, executes once, and consumes it. An
        approval that was already consumed is invisible here — that is what
        stops one approval from authorizing a loop of actions.

        `payload` is REQUIRED to match the stored `payload_hash` (review G-02).
        Matching on the action name alone meant a human could approve
        `create_order(quantity=1)` and the resumed run would execute whatever
        arguments it computed this time — a different action than the one
        approved. Rows with a NULL hash never match, because SQL `= NULL` is
        never true: approvals created before the hash existed fail closed and
        need a fresh decision.
        """
        if conversation_id is None:
            return None
        if payload is None:
            # Callers must state what they are about to execute. Without it
            # there is nothing to bind the approval to, so refuse to match.
            return None
        return (
            await session.execute(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.tenant_id == tenant_id,
                    ApprovalRequest.conversation_id == conversation_id,
                    ApprovalRequest.action == action,
                    ApprovalRequest.status == "APPROVED",
                    ApprovalRequest.consumed_at.is_(None),
                    ApprovalRequest.payload_hash == payload_fingerprint(payload),
                )
                .order_by(ApprovalRequest.decided_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    @staticmethod
    async def consume(
        session: AsyncSession, request: ApprovalRequest
    ) -> ApprovalRequest:
        """Mark the approval as used — the action it authorized has run."""
        request.consumed_at = datetime.now(UTC)
        await session.flush()
        return request

    @staticmethod
    async def list_for_tenant(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ApprovalRequest]:
        stmt = select(ApprovalRequest).where(ApprovalRequest.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(ApprovalRequest.status == status)
        rows = (
            await session.execute(
                stmt.order_by(ApprovalRequest.created_at.desc()).limit(limit)
            )
        ).scalars().all()
        return list(rows)

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
