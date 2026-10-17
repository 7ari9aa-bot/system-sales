"""AI governance routes — approvals (§135), handovers (§37/§150), provider policies (§43)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.ai.approvals import ApprovalService
from app.modules.ai.models import AIHandover
from app.modules.ai.policy import AIProviderPolicyService
from app.modules.ai.routers._deps import (
    ApproveCtx,
    HandoverReadCtx,
    HandoverWriteCtx,
    SettingsCtx,
    TenantCtxDep,
)
from app.modules.ai.schemas import (
    HANDOVER_OUTCOMES,
    ApprovalDecisionOut,
    ApprovalList,
    HandoverList,
    HandoverOut,
    HandoverResolveRequest,
    PolicyList,
    PolicyOut,
)

router = APIRouter(prefix="/ai", tags=["ai"])


# ---------- approvals (§135) ----------
#
# A HIGH-risk tool call parks the run in WAITING_APPROVAL and the action has
# NOT happened. These routes are how a human releases (or kills) it — without
# them the run would wait forever with no way to decide.


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(description="APPROVED | REJECTED | CANCELLED")
    reason: str | None = Field(default=None, max_length=512)


def _approval_out(a) -> dict:
    return {
        "id": str(a.id),
        "status": a.status,
        "action": a.action,
        "risk_level": a.risk_level,
        "entity_type": a.entity_type,
        "entity_id": a.entity_id,
        "conversation_id": str(a.conversation_id) if a.conversation_id else None,
        "run_id": str(a.run_id) if a.run_id else None,
        "payload": a.payload or {},
        # §135 review G-02: the digest is what makes an approval cover the
        # ARGUMENTS it approved rather than merely the action name, and
        # `approved_by_user_id` is who owns that decision. A queue that cannot
        # be audited after the fact is not a governance surface, so both ride
        # with the row.
        "payload_hash": a.payload_hash,
        "requested_by": a.requested_by,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "decided_at": a.decided_at.isoformat() if a.decided_at else None,
        "consumed_at": a.consumed_at.isoformat() if a.consumed_at else None,
        "approved_by_user_id": str(a.approved_by_user_id) if a.approved_by_user_id else None,
        "rejection_reason": a.rejection_reason,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("/approvals", response_model=ApprovalList)
async def list_approvals(
    ctx: TenantCtxDep,
    status: Annotated[str | None, Query(description="PENDING | APPROVED | ...")] = None,
):
    rows, truncated = await ApprovalService.list_for_tenant(
        ctx.session, ctx.tenant_id, status=status
    )
    return {"items": [_approval_out(a) for a in rows], "truncated": truncated}


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalDecisionOut)
async def decide_approval(
    approval_id: uuid.UUID,
    body: ApprovalDecisionRequest,
    ctx: ApproveCtx,
):
    """Approve, reject or cancel a parked HIGH-risk action.

    Approving RE-ENQUEUES the conversation so the agent re-evaluates context and
    retries: the gate then finds the granted approval and executes the action
    exactly once. A customer who replied while the approval was pending makes it
    stale, which is why the run is re-planned rather than blindly continued.
    """
    from app.core.events.writer import add_outbox_event

    approval = await ApprovalService.decide(
        ctx.session,
        ctx.tenant_id,
        approval_id,
        decision=body.decision,
        decided_by_user_id=ctx.user.id,
        rejection_reason=body.reason,
    )

    resumed = False
    if approval.status == "APPROVED" and approval.conversation_id is not None:
        await add_outbox_event(
            ctx.session,
            aggregate_type="message",
            aggregate_id=approval.id,
            event_type="message.received",
            tenant_id=ctx.tenant_id,
            payload={
                "conversation_id": str(approval.conversation_id),
                "resumed_approval_id": str(approval.id),
                # Explicitly no message. This event re-runs the CONVERSATION, and
                # the approval's own id is the aggregate — naming it a message
                # would have the worker transcribe a message that does not exist
                # and answer whichever inbound happens to share the row's shape.
                # The hook therefore re-evaluates against the newest inbound.
                "message_id": None,
            },
        )
        resumed = True

    return {**_approval_out(approval), "resumed": resumed}


# ---------- §37/§150 Handover queue & workflow ----------


def _handover_out(h: AIHandover) -> dict:
    """One shape for every handover response — three routes used to build the
    field list by hand, which is how a new column gets forgotten."""
    return HandoverOut(
        id=h.id,
        conversation_id=h.conversation_id,
        run_id=h.run_id,
        reason=h.reason,
        status=h.status,
        claimed_by_user_id=h.claimed_by_user_id,
        note=h.note,
        created_at=h.created_at.isoformat() if h.created_at else None,
        resolved_by_user_id=h.resolved_by_user_id,
        resolved_at=h.resolved_at.isoformat() if h.resolved_at else None,
        outcome=h.outcome,
        outcome_note=h.outcome_note,
    )


@router.get("/handovers", response_model=HandoverList)
async def list_handovers(
    ctx: HandoverReadCtx,
    status: Annotated[
        str | None, Query(description="Filter by pending | claimed | resolved")
    ] = None,
):
    query = select(AIHandover).where(AIHandover.tenant_id == ctx.tenant_id)
    if status:
        query = query.where(AIHandover.status == status)
    query = query.order_by(AIHandover.created_at.desc())
    rows = (await ctx.session.execute(query)).scalars().all()
    return {"items": [_handover_out(h) for h in rows], "total": len(rows)}


@router.post("/handovers/{handover_id}/claim", response_model=HandoverOut)
async def claim_handover(
    handover_id: uuid.UUID,
    ctx: HandoverWriteCtx,
):
    from sqlalchemy import text

    existing = (
        await ctx.session.execute(
            select(AIHandover).where(
                AIHandover.id == handover_id,
                AIHandover.tenant_id == ctx.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not existing:
        raise NotFoundError("handover not found")
    if existing.status != "pending":
        raise ConflictError(f"handover is already {existing.status}")

    # Atomic claim: only pending -> claimed (§29)
    stmt = (
        update(AIHandover)
        .where(
            AIHandover.id == handover_id,
            AIHandover.tenant_id == ctx.tenant_id,
            AIHandover.status == "pending",
        )
        .values(
            status="claimed",
            claimed_by_user_id=ctx.user_id,
        )
        .returning(AIHandover)
    )
    handover = (await ctx.session.execute(stmt)).scalar_one_or_none()
    if not handover:
        raise ConflictError("handover was already claimed by another user")

    await ctx.session.execute(
        text(
            "UPDATE conversations SET assignee_user_id = :uid WHERE id = :cid AND tenant_id = :tid"
        ),
        {
            "uid": str(ctx.user_id),
            "cid": str(handover.conversation_id),
            "tid": str(ctx.tenant_id),
        },
    )
    await ctx.session.flush()
    return _handover_out(handover)


@router.post("/handovers/{handover_id}/resolve", response_model=HandoverOut)
async def resolve_handover(
    handover_id: uuid.UUID,
    ctx: HandoverWriteCtx,
    body: HandoverResolveRequest | None = None,
):
    """Close a handover, recording WHO closed it, WHEN, and WITH WHAT RESULT.

    §150's outcome half: this route used to flip `status` and leave no trace
    behind, so the queue could count handovers created but never handovers
    answered. `outcome` is a closed vocabulary (a free-text-only field is a
    field nobody aggregates); `note` carries the detail a human would want
    later. Resolving a resolved row is a conflict, not a silent re-write: the
    second resolver would overwrite the first one's record of what happened.
    """
    from app.core.events.writer import add_outbox_event

    handover = (
        await ctx.session.execute(
            select(AIHandover)
            .where(
                AIHandover.id == handover_id,
                AIHandover.tenant_id == ctx.tenant_id,
            )
            # Two reviewers opening one handover both see PENDING; the row
            # lock makes the second one read the resolved state instead of
            # overwriting the first one's outcome.
            .with_for_update()
        )
    ).scalar_one_or_none()
    if handover is None:
        raise NotFoundError("handover not found")
    if handover.status == "resolved":
        raise ConflictError("handover is already resolved")

    outcome = body.outcome if body is not None else None
    if outcome is not None and outcome not in HANDOVER_OUTCOMES:
        raise ValidationError(f"outcome must be one of: {', '.join(HANDOVER_OUTCOMES)}")

    handover.status = "resolved"
    handover.resolved_by_user_id = ctx.user_id
    handover.resolved_at = datetime.now(UTC)
    handover.outcome = outcome
    handover.outcome_note = body.note if body is not None else None

    # Synchronize conversation: conversation leaves waiting_human (§30)
    from sqlalchemy import text

    await ctx.session.execute(
        text(
            "UPDATE conversations SET status = 'open' "
            "WHERE id = :cid AND tenant_id = :tid AND status = 'waiting_human'"
        ),
        {
            "cid": str(handover.conversation_id),
            "tid": str(ctx.tenant_id),
        },
    )
    # The other half of `request_human_takeover`'s three writes: the row and
    # the status moved, so the outbox says so too — that is how SLA clocks and
    # the dashboard learn a handover ENDED rather than only that it began.
    await add_outbox_event(
        ctx.session,
        aggregate_type="ai",
        aggregate_id=handover.conversation_id,
        event_type="ai.handover.resolved",
        tenant_id=ctx.tenant_id,
        payload={
            "event_type": "ai.handover.resolved",
            "handover_id": str(handover.id),
            "conversation_id": str(handover.conversation_id),
            "reason": handover.reason,
            "outcome": outcome,
            "resolved_by_user_id": str(ctx.user_id),
        },
    )
    await ctx.session.flush()
    return _handover_out(handover)


# ---------- provider policies (§43) ----------
#
# Data-egress governance: which providers/models may receive tenant data.
# Writes are gated like platform settings (settings:write).


class ProviderPolicyUpsertRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=31)
    status: str = Field(default="allowed", description="allowed | denied")
    allowed_models: list[str] = Field(default_factory=list)
    pii_redaction_required: bool = False
    data_classification: str = Field(default="internal", max_length=31)
    data_residency: str | None = Field(
        default=None, max_length=31, description="§43 region data may not leave, e.g. 'eu'"
    )
    retention_terms: str | None = Field(
        default=None, max_length=2000, description="§43 documented provider retention terms"
    )
    notes: str | None = None


def _policy_out(policy) -> dict:
    return {
        "id": str(policy.id),
        "provider": policy.provider,
        "status": policy.status,
        "allowed_models": list(policy.allowed_models or []),
        "pii_redaction_required": bool(policy.pii_redaction_required),
        "data_classification": policy.data_classification,
        "data_residency": policy.data_residency,
        "retention_terms": policy.retention_terms,
        "notes": policy.notes,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
    }


@router.get("/provider-policies", response_model=PolicyList)
async def list_provider_policies(ctx: SettingsCtx):
    policies = await AIProviderPolicyService.list_policies(ctx.session, ctx.tenant_id)
    return {"items": [_policy_out(p) for p in policies]}


@router.put("/provider-policies", response_model=PolicyOut)
async def upsert_provider_policy(body: ProviderPolicyUpsertRequest, ctx: SettingsCtx):
    policy = await AIProviderPolicyService.upsert(
        ctx.session,
        ctx.tenant_id,
        provider=body.provider,
        status=body.status,
        allowed_models=body.allowed_models,
        pii_redaction_required=body.pii_redaction_required,
        data_classification=body.data_classification,
        data_residency=body.data_residency,
        retention_terms=body.retention_terms,
        notes=body.notes,
    )
    return _policy_out(policy)
