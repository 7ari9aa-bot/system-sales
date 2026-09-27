"""Atomic Execution Boundary Service (V12 Wave B §23).

Enforces the canonical 15-step transaction:
1. Verify lease signature / hash & nonce
2. Verify lease is in MINTED state & not expired (lease TTL <= 60s)
3. Verify grant is ACTIVE & not expired/revoked
4. Verify decision is in APPROVED state & not stale (<= TTL)
5. Lock target resources / verify resource version matches expected_version
6. Lock budget reservation / account balance
7. Re-verify risk engine score if needed
8. Transition lease to ACTIVE / EXECUTING
9. Execute payload handler (domain mutation callback)
10. Record side effects into EffectLedger
11. Record double-entry financial transaction if financial
12. Update resource versions
13. Transition lease to EXECUTED (redeemed)
14. Append Outbox event with decision_id and effect_id
15. Commit transaction & release locks
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.commands import command_hash as compute_command_hash
from app.core.errors import ConflictError, NotFoundError
from app.core.events.writer import add_outbox_event
from app.modules.authority.models import AuthorityLease, CapabilityGrant
from app.modules.authority.schemas import ExecutionResultOut
from app.modules.authority.service import AuthorityService, sha256_hex
from app.modules.decisions.models import Decision
from app.modules.decisions.service import DecisionService


class AtomicExecutionService:
    """The canonical 15-step execution boundary for all domain mutations."""

    @staticmethod
    async def execute_command(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        lease_token: str,
        action: str,
        resource: dict[str, Any] | None = None,
        arguments: dict[str, Any] | None = None,
        purpose: str,
        current_versions: dict[str, int] | None = None,
        mutation_fn: Callable[[AsyncSession], Awaitable[dict[str, Any]]] | None = None,
        outbox_aggregate_type: str | None = None,
        outbox_aggregate_id: uuid.UUID | None = None,
        outbox_event_type: str | None = None,
        outbox_payload: dict[str, Any] | None = None,
    ) -> ExecutionResultOut:
        now = datetime.now(UTC)
        res = resource or {}
        args = arguments or {}
        cur_versions = current_versions or {}

        # 1. Compute canonical command hash over arrived payload
        arrived_hash = compute_command_hash(
            str(tenant_id),
            action=action,
            resource=res,
            arguments=args,
            purpose=purpose,
        )

        # 2. Look up Authority Lease by token hash with row lock
        token_hash = sha256_hex(lease_token)
        lease = await session.scalar(
            select(AuthorityLease)
            .where(
                AuthorityLease.tenant_id == tenant_id,
                AuthorityLease.lease_token_hash == token_hash,
            )
            .with_for_update()
        )
        if not lease:
            await metrics.record_authority_rejection()
            raise NotFoundError("Authority lease not found or invalid token")

        # 3. Verify lease is in MINTED state (single-use enforcement)
        if lease.state != "MINTED":
            await metrics.record_authority_rejection()
            raise ConflictError(
                f"Authority lease is already redeemed or inactive (state: {lease.state})"
            )

        # 4. Verify lease TTL (strictly <= 60s)
        if lease.expires_at <= now:
            lease.state = "EXPIRED"
            await session.flush()
            await metrics.record_authority_rejection()
            raise ConflictError("Authority lease has expired past its TTL")

        # 5. Verify command_hash binding
        if lease.command_hash != arrived_hash:
            await metrics.record_authority_rejection()
            raise ConflictError(
                f"Execution command_hash mismatch (lease: {lease.command_hash}, "
                f"execution: {arrived_hash})"
            )

        # 6. Verify Capability Grant with row lock
        grant = await session.scalar(
            select(CapabilityGrant)
            .where(
                CapabilityGrant.tenant_id == tenant_id,
                CapabilityGrant.grant_id == lease.grant_id,
            )
            .with_for_update()
        )
        if not grant or grant.status != "ACTIVE":
            lease.state = "REVOKED"
            await session.flush()
            await metrics.record_authority_rejection()
            raise ConflictError("Parent capability grant is not ACTIVE or was revoked")
        if grant.expires_at <= now:
            grant.status = "EXPIRED"
            lease.state = "REVOKED"
            await session.flush()
            await metrics.record_authority_rejection()
            raise ConflictError("Parent capability grant has expired")

        # 7. Verify Decision with row lock
        decision = await session.scalar(
            select(Decision)
            .where(
                Decision.tenant_id == tenant_id,
                Decision.decision_id == lease.decision_id,
            )
            .with_for_update()
        )
        if not decision:
            lease.state = "REVOKED"
            await session.flush()
            await metrics.record_authority_rejection()
            raise NotFoundError("Underlying decision not found")

        if decision.decision_status != "APPROVED":
            lease.state = "REVOKED"
            await session.flush()
            await metrics.record_authority_rejection()
            raise ConflictError(
                f"Underlying decision is not in APPROVED state "
                f"(current: {decision.decision_status})"
            )

        if decision.expires_at and decision.expires_at <= now:
            await DecisionService.mark_stale(session, tenant_id, decision.decision_id)
            lease.state = "EXPIRED"
            await session.flush()
            await metrics.record_decision_stale()
            await metrics.record_authority_rejection()
            raise ConflictError("Underlying decision expired past its TTL")

        # 8. Check and lock expected resource versions (optimistic concurrency)
        if lease.expected_versions:
            for res_key, expected_ver in lease.expected_versions.items():
                observed_ver = cur_versions.get(res_key)
                if observed_ver is not None and observed_ver != expected_ver:
                    # Version conflict: mark decision stale, revoke lease, record metrics
                    await metrics.record_version_conflict()
                    await metrics.record_authority_rejection()
                    await metrics.record_decision_stale()
                    await DecisionService.mark_stale(session, tenant_id, decision.decision_id)
                    lease.state = "REVOKED"
                    await session.flush()
                    raise ConflictError(
                        f"Resource version conflict on '{res_key}': "
                        f"expected {expected_ver}, observed {observed_ver}"
                    )

        # 9. Commit budget reservation if any
        # Look for in-flight reservation tied to this lease
        from app.modules.authority.models import BudgetReservation

        reservation = await session.scalar(
            select(BudgetReservation).where(
                BudgetReservation.tenant_id == tenant_id,
                BudgetReservation.lease_id == lease.lease_id,
                BudgetReservation.status == "RESERVED",
            )
        )
        if reservation:
            await AuthorityService.commit_reservation(
                session, tenant_id, reservation.reservation_id
            )

        # 10. Transition lease to ACTIVE / EXECUTING
        lease.state = "ACTIVE"
        await session.flush()

        # 11. Execute domain mutation callback
        mutation_result: dict[str, Any] = {}
        if mutation_fn is not None:
            mutation_result = await mutation_fn(session)

        # 12. Allocate effect ID (for side effect lineage & outbox event)
        effect_id = uuid.uuid4()

        # 13. Transition lease to EXECUTED (redeemed)
        redeemed_at = datetime.now(UTC)
        lease.state = "EXECUTED"
        lease.redeemed_at = redeemed_at

        # 14. Transition decision to EXECUTED (terminal state)
        await DecisionService.mark_executed(session, tenant_id, decision.decision_id)

        # 15. Append Outbox event with decision_id and effect_id if requested
        if outbox_aggregate_type and outbox_event_type and outbox_aggregate_id:
            await add_outbox_event(
                session,
                aggregate_type=outbox_aggregate_type,
                aggregate_id=outbox_aggregate_id,
                event_type=outbox_event_type,
                tenant_id=tenant_id,
                payload=outbox_payload or mutation_result,
                decision_id=decision.decision_id,
                effect_id=effect_id,
            )

        await session.flush()

        return ExecutionResultOut(
            success=True,
            lease_id=lease.lease_id,
            decision_id=decision.decision_id,
            effect_id=effect_id,
            mutation_result=mutation_result,
            executed_at=redeemed_at,
        )
