"""DECISIONS routes — the Decision Plane over /api/v1/decisions (V12).

Reads use plain ``TenantCtxDep`` (the Decision surface exists so every actor
can SEE what was minted and why — ADR-060's human-inclusive authority);
every write, including the state-machine transitions, is gated on
``settings:write`` — the house convention for governance surfaces, since no
new permission code may be invented without a role ever being granted it
(an invented code is an unreachable door).

There is no DELETE and no generic PATCH: decisions are immutable history in
their content. The only writes are propose, record-dependency, and the
state-machine transitions — each answered with the decision's NEW state, so
an attempt to approve an expired decision returns the EXPIRED decision rather
than a silent success (see DecisionService._apply_transition for why the
expiry flip is a committed write and not a raised error).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.modules.decisions import schemas
from app.modules.decisions.models import Decision, DecisionDependency
from app.modules.decisions.service import DecisionService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission

router = APIRouter(prefix="/decisions", tags=["decisions"])

WriteCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]

# Query params are declared `Annotated[type, Query(...)] = <value>`, never
# `name: type = Query(...)` — the parameter-declaration rule gated by
# tests/test_route_parameter_declarations.py.
PageLimit = Annotated[int, Query(ge=1, le=schemas.PAGE_LIMIT_MAX)]
PageOffset = Annotated[int, Query(ge=0)]

_STATUS_PATTERN = (
    "^(PROPOSED|VERIFIED|PENDING_APPROVAL|APPROVED|STALE|DENIED|EXPIRED|REVOKED|EXECUTED)$"
)


class DecisionPropose(BaseModel):
    """Body for ``POST /decisions`` — mints a PROPOSED decision."""

    action: str = Field(min_length=1, max_length=255)
    risk_level: str = Field(pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    normalized_arguments: dict[str, Any] = Field(default_factory=dict)
    actor_id: uuid.UUID | None = None
    actor_type: str | None = Field(default=None, max_length=31)
    agent_id: uuid.UUID | None = None
    agent_version_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    intent: str | None = Field(default=None, max_length=255)
    policy_version: int | None = Field(default=None, ge=1)
    evidence_set_id: uuid.UUID | None = None
    evidence_set_hash: str | None = Field(default=None, max_length=64)
    dependency_snapshot_hash: str | None = Field(default=None, max_length=64)
    resource_versions: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = Field(default=None, max_length=255)
    trace_id: str | None = Field(default=None, max_length=255)
    conversation_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    # Explicit windows win; otherwise HIGH/CRITICAL get the 60s TTL.
    expires_at: datetime | None = None


class DependencyRecord(BaseModel):
    """Body for ``POST /decisions/{decision_id}/dependencies``."""

    resource_type: str = Field(min_length=1, max_length=127)
    resource_id: uuid.UUID
    resource_version: int = Field(ge=0)
    # Either a value or a precomputed digest. Over the wire the value travels
    # as its CANONICAL STRING (the same canonical_json the digest is taken
    # from) — the money-strings contract forbids a polymorphic `value` field
    # because a number loses cents; a caller with a rich object hashes it
    # client-side and sends value_digest instead.
    value: str | None = None
    value_digest: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default=None, max_length=255)
    source_version: str | None = Field(default=None, max_length=255)
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    freshness_sla_seconds: int | None = Field(default=None, ge=0)
    classification: str = Field(min_length=1, max_length=63)
    content_hash: str = Field(min_length=1, max_length=64)


def _decision_dict(decision: Decision) -> dict:
    return {
        "decision_id": decision.decision_id,
        "actor_id": decision.actor_id,
        "actor_type": decision.actor_type,
        "agent_id": decision.agent_id,
        "agent_version_id": decision.agent_version_id,
        "run_id": decision.run_id,
        "intent": decision.intent,
        "action": decision.action,
        "normalized_arguments": decision.normalized_arguments or {},
        "policy_version": decision.policy_version,
        "risk_level": decision.risk_level,
        "approval_state": decision.approval_state,
        "evidence_set_id": decision.evidence_set_id,
        "evidence_set_hash": decision.evidence_set_hash,
        "dependency_snapshot_hash": decision.dependency_snapshot_hash,
        "resource_versions": decision.resource_versions or {},
        "created_at": decision.created_at,
        "expires_at": decision.expires_at,
        "decision_status": decision.decision_status,
        "request_id": decision.request_id,
        "trace_id": decision.trace_id,
        "conversation_id": decision.conversation_id,
        "customer_id": decision.customer_id,
        "content_hash": decision.content_hash,
        "command_hash": decision.command_hash,
    }


def _dependency_dict(dependency: DecisionDependency) -> dict:
    return {
        "dependency_id": dependency.dependency_id,
        "decision_id": dependency.decision_id,
        "resource_type": dependency.resource_type,
        "resource_id": dependency.resource_id,
        "resource_version": dependency.resource_version,
        "value_digest": dependency.value_digest,
        "source": dependency.source,
        "source_version": dependency.source_version,
        "observed_at": dependency.observed_at,
        "valid_from": dependency.valid_from,
        "valid_until": dependency.valid_until,
        "freshness_sla_seconds": dependency.freshness_sla_seconds,
        "classification": dependency.classification,
        "content_hash": dependency.content_hash,
        "created_at": dependency.created_at,
    }


@router.post("", response_model=schemas.DecisionOut, status_code=201)
async def propose_decision(ctx: WriteCtx, body: DecisionPropose):
    """Mint a PROPOSED decision; content_hash is computed over the canonical
    (action + normalized_arguments) JSON, never taken from the caller."""
    decision = await DecisionService.propose(
        ctx.session,
        ctx.tenant_id,
        action=body.action,
        risk_level=body.risk_level,
        normalized_arguments=body.normalized_arguments,
        actor_id=body.actor_id,
        actor_type=body.actor_type,
        agent_id=body.agent_id,
        agent_version_id=body.agent_version_id,
        run_id=body.run_id,
        intent=body.intent,
        policy_version=body.policy_version,
        evidence_set_id=body.evidence_set_id,
        evidence_set_hash=body.evidence_set_hash,
        dependency_snapshot_hash=body.dependency_snapshot_hash,
        resource_versions=body.resource_versions,
        request_id=body.request_id,
        trace_id=body.trace_id,
        conversation_id=body.conversation_id,
        customer_id=body.customer_id,
        expires_at=body.expires_at,
    )
    return _decision_dict(decision)


@router.get("", response_model=schemas.DecisionListOut)
async def list_decisions(
    ctx: TenantCtxDep,
    decision_status: Annotated[str | None, Query(pattern=_STATUS_PATTERN)] = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """This tenant's decisions, newest first, paged, optionally by status."""
    conditions = [Decision.tenant_id == ctx.tenant_id]
    if decision_status is not None:
        conditions.append(Decision.decision_status == decision_status)
    total = (
        await ctx.session.execute(select(func.count(Decision.decision_id)).where(*conditions))
    ).scalar_one()
    rows = (
        await ctx.session.execute(
            select(Decision)
            .where(*conditions)
            # created_at shares one now() across a transaction; decision_id is
            # the tie-break that makes the ORDER a total order (house rule).
            .order_by(Decision.created_at.desc(), Decision.decision_id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return {
        "items": [_decision_dict(row) for row in rows.scalars().all()],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{decision_id}", response_model=schemas.DecisionOut)
async def get_decision(ctx: TenantCtxDep, decision_id: uuid.UUID):
    """One decision — another tenant's id is a 404 (the id is not a permission)."""
    decision = await DecisionService.get(ctx.session, ctx.tenant_id, decision_id)
    return _decision_dict(decision)


@router.post("/{decision_id}/verify", response_model=schemas.DecisionOut)
async def verify_decision(decision_id: uuid.UUID, ctx: WriteCtx):
    """PROPOSED -> VERIFIED."""
    decision = await DecisionService.verify(ctx.session, ctx.tenant_id, decision_id)
    return _decision_dict(decision)


@router.post("/{decision_id}/require-approval", response_model=schemas.DecisionOut)
async def require_approval(decision_id: uuid.UUID, ctx: WriteCtx):
    """VERIFIED -> PENDING_APPROVAL: opens the §135 durable approval."""
    decision = await DecisionService.require_approval(ctx.session, ctx.tenant_id, decision_id)
    return _decision_dict(decision)


@router.post("/{decision_id}/approve", response_model=schemas.DecisionOut)
async def approve_decision(decision_id: uuid.UUID, ctx: WriteCtx):
    """-> APPROVED, bound to the row's pinned hashes (§135).

    A decision past its TTL comes back EXPIRED, never APPROVED — the body,
    not the status code, carries the refusal.
    """
    decision = await DecisionService.approve(ctx.session, ctx.tenant_id, decision_id)
    return _decision_dict(decision)


@router.post("/{decision_id}/deny", response_model=schemas.DecisionOut)
async def deny_decision(decision_id: uuid.UUID, ctx: WriteCtx):
    """-> DENIED (terminal): decided once; a denied decision is never revived."""
    decision = await DecisionService.deny(ctx.session, ctx.tenant_id, decision_id)
    return _decision_dict(decision)


@router.post("/{decision_id}/stale", response_model=schemas.DecisionOut)
async def mark_stale(decision_id: uuid.UUID, ctx: WriteCtx):
    """-> STALE: a dependency moved; re-propose, never revive."""
    decision = await DecisionService.mark_stale(ctx.session, ctx.tenant_id, decision_id)
    return _decision_dict(decision)


@router.post("/{decision_id}/execute", response_model=schemas.DecisionOut)
async def execute_decision(decision_id: uuid.UUID, ctx: WriteCtx):
    """APPROVED -> EXECUTED (terminal).

    A decision past its TTL comes back EXPIRED — execution after expiry is
    exactly the stale-authorization the TTL exists to prevent.
    """
    decision = await DecisionService.mark_executed(ctx.session, ctx.tenant_id, decision_id)
    return _decision_dict(decision)


@router.post("/{decision_id}/dependencies", response_model=schemas.DependencyOut, status_code=201)
async def record_dependency(
    decision_id: uuid.UUID, body: DependencyRecord, ctx: WriteCtx
):
    """Pin one resource version into the decision's dependency snapshot; the
    decision's dependency_snapshot_hash is re-derived and stored."""
    dependency = await DecisionService.record_dependency(
        ctx.session,
        ctx.tenant_id,
        decision_id,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        resource_version=body.resource_version,
        value=body.value,
        value_digest=body.value_digest,
        source=body.source,
        source_version=body.source_version,
        observed_at=body.observed_at,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        freshness_sla_seconds=body.freshness_sla_seconds,
        classification=body.classification,
        content_hash=body.content_hash,
    )
    return _dependency_dict(dependency)


@router.get("/{decision_id}/dependencies", response_model=schemas.DependencyListOut)
async def list_dependencies(
    ctx: TenantCtxDep,
    decision_id: uuid.UUID,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """The decision's dependency snapshot rows, in dependency-id order, paged.

    The parent is proven to be this tenant's BEFORE the child table is read —
    the 404-first ordering the §115 matrix requires of every parent/child pair.
    """
    await DecisionService.get(ctx.session, ctx.tenant_id, decision_id)
    conditions = [
        DecisionDependency.tenant_id == ctx.tenant_id,
        DecisionDependency.decision_id == decision_id,
    ]
    total = (
        await ctx.session.execute(
            select(func.count(DecisionDependency.dependency_id)).where(*conditions)
        )
    ).scalar_one()
    rows = (
        await ctx.session.execute(
            select(DecisionDependency)
            .where(*conditions)
            .order_by(DecisionDependency.dependency_id)
            .limit(limit)
            .offset(offset)
        )
    )
    return {
        "items": [_dependency_dict(row) for row in rows.scalars().all()],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }
