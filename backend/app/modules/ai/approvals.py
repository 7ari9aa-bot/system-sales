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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.modules.ai.models import ApprovalRequest

APPROVAL_TTL_MINUTES = 60

#: How many rows one read of the queue returns. Bounded because the decided
#: histories (APPROVED / REJECTED) grow forever; reported as `truncated` so a
#: bounded page never reads as a complete one.
APPROVALS_PAGE_SIZE = 100


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


def _pending_duplicate_stmt(
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    action: str,
    fingerprint: str,
):
    """THE dedupe statement — spelled once for both the pre-check and the
    post-violation re-read, so the two can never drift and the index in
    migration e6f7a8b9c0d1 expresses exactly this predicate.

    Idempotent by key: (tenant, conversation, action, payload_hash) restricted
    to the PENDING state. `conversation_id == None` renders IS NULL, which is
    why the index buckets NULL through coalesce — see that migration's
    docstring and tests/test_approval_pending_dedupe_index.py.
    """
    return (
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
        command_hash: str | None = None,
        evidence_set_hash: str | None = None,
        dependency_snapshot_hash: str | None = None,
    ) -> ApprovalRequest:
        payload = dict(payload or {})
        # V12 Wave D: cryptographically bind approval to command and evidence hashes
        if command_hash or evidence_set_hash or dependency_snapshot_hash:
            payload["_v12_lineage"] = {
                k: v
                for k, v in {
                    "command_hash": command_hash,
                    "evidence_set_hash": evidence_set_hash,
                    "dependency_snapshot_hash": dependency_snapshot_hash,
                }.items()
                if v is not None
            }
        fingerprint = payload_fingerprint(payload)

        # Idempotent: re-running the gate must not pile up duplicate PENDING
        # requests for the same conversation + action + arguments. This matters
        # because a STALE approval is discarded and re-requested, and a resumed
        # run re-enters the gate.
        stmt = _pending_duplicate_stmt(tenant_id, conversation_id, action, fingerprint)
        existing = (await session.execute(stmt)).scalar_one_or_none()
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
        # The SELECT above is a check-then-act: two simultaneous gate entries
        # can both see no PENDING row. The database closes the race —
        # uq_approvals_pending_dedupe (unique partial index on exactly this
        # key, WHERE status = 'PENDING') lets one INSERT through and refuses
        # the other. The savepoint keeps that refusal recoverable: without it
        # the 23505 would abort the CALLER's transaction (the whole agent run),
        # and the re-read below could not run at all.
        try:
            async with session.begin_nested():
                session.add(request)
                await session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "pgcode", None) != "23505":
                raise  # an FK or other integrity fault is not this race
            winner = (await session.execute(stmt)).scalar_one_or_none()
            if winner is None:
                raise  # not explainable by the dedupe key — fail closed
            return winner
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
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.tenant_id == tenant_id,
                    ApprovalRequest.id == approval_id,
                )
                # The lock is what makes the two checks below a decision rather
                # than a guess. Under READ COMMITTED a second `decide` blocks
                # here, and when the winner commits it re-reads the NEW row
                # version — so it sees `status != PENDING` and refuses, instead
                # of both reviewers getting a 200 and the parked run being
                # released twice.
                .with_for_update()
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
                # `consume` below is a separate write, so without this lock two
                # resumed runs of one conversation both read the same unconsumed
                # grant and BOTH ran the handler — the approval authorizing two
                # executions of a HIGH-risk action. Locked, the loser blocks, and
                # on the winner's commit Postgres re-checks the predicate against
                # the new row version: `consumed_at IS NULL` no longer holds, so
                # it reads None and parks a fresh request instead of double-firing.
                .with_for_update()
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
        limit: int = APPROVALS_PAGE_SIZE,
    ) -> tuple[list[ApprovalRequest], bool]:
        """One page of a tenant's approvals, and whether the queue was longer.

        The second value is the point: a reviewer who is handed exactly 100
        pending rows cannot tell 100 from 1000 by looking at them, and §135's
        promise is that this queue is the whole set of decisions owed. So the
        page is fetched one row deep and cut, which says "there is more" without
        a COUNT over the whole table.
        """
        stmt = select(ApprovalRequest).where(ApprovalRequest.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(ApprovalRequest.status == status)
        rows = (
            await session.execute(
                stmt.order_by(ApprovalRequest.created_at.desc()).limit(limit + 1)
            )
        ).scalars().all()
        return list(rows[:limit]), len(rows) > limit

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
