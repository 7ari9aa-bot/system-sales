"""AUTHORITY routes — Capability Grants, Authority Leases, and Atomic Execution (V12 Wave B).

Routes mounted under /api/v1/authority:
- Grants: /api/v1/authority/grants
- Leases: /api/v1/authority/leases
- Execution: /api/v1/authority/execute
- Budgets: /api/v1/authority/budgets
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from app.modules.authority import schemas
from app.modules.authority.executor import AtomicExecutionService
from app.modules.authority.models import AutonomyBudget, CapabilityGrant
from app.modules.authority.service import AuthorityService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission

router = APIRouter(prefix="/authority", tags=["authority"])

WriteCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]
PageLimit = Annotated[int, Query(ge=1, le=schemas.PAGE_LIMIT_MAX)]
PageOffset = Annotated[int, Query(ge=0)]


# ---------------------------------------------------------------- Capability Grants


@router.post(
    "/grants",
    response_model=schemas.CapabilityGrantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a new CapabilityGrant",
)
async def issue_grant(
    ctx: WriteCtx,
    body: schemas.CapabilityGrantCreate,
) -> CapabilityGrant:
    return await AuthorityService.issue_grant(
        ctx.session,
        ctx.tenant_id,
        tool_name=body.tool_name,
        decision_id=body.decision_id,
        actor_id=body.actor_id or ctx.user_id,
        actor_type=body.actor_type or "system",
        scope=body.scope,
        max_budget=body.max_budget,
        currency=body.currency,
        ttl_seconds=body.ttl_seconds,
    )


@router.get(
    "/grants",
    response_model=schemas.CapabilityGrantListOut,
    summary="List CapabilityGrants for tenant",
)
async def list_grants(
    ctx: TenantCtxDep,
    tool_name: Annotated[str | None, Query()] = None,
    grant_status: Annotated[str | None, Query(alias="status")] = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
) -> schemas.CapabilityGrantListOut:
    items, total = await AuthorityService.list_grants(
        ctx.session,
        ctx.tenant_id,
        tool_name=tool_name,
        status=grant_status,
        limit=limit,
        offset=offset,
    )
    return schemas.CapabilityGrantListOut(
        items=[schemas.CapabilityGrantOut.model_validate(g, from_attributes=True) for g in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/grants/{grant_id}",
    response_model=schemas.CapabilityGrantOut,
    summary="Get a CapabilityGrant by ID",
)
async def get_grant(
    ctx: TenantCtxDep,
    grant_id: uuid.UUID,
) -> CapabilityGrant:
    return await AuthorityService.get_grant(ctx.session, ctx.tenant_id, grant_id)


@router.post(
    "/grants/{grant_id}/revoke",
    response_model=schemas.CapabilityGrantOut,
    summary="Revoke an active CapabilityGrant",
)
async def revoke_grant(
    ctx: WriteCtx,
    grant_id: uuid.UUID,
) -> CapabilityGrant:
    return await AuthorityService.revoke_grant(ctx.session, ctx.tenant_id, grant_id)


# ---------------------------------------------------------------- Authority Leases


@router.post(
    "/leases/mint",
    response_model=schemas.MintLeaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mint an ephemeral AuthorityLease bound to command_hash with TTL <= 60s",
)
async def mint_lease(
    ctx: WriteCtx,
    body: schemas.MintLeaseRequest,
) -> schemas.MintLeaseResponse:
    lease, lease_token = await AuthorityService.mint_lease(
        ctx.session,
        ctx.tenant_id,
        grant_id=body.grant_id,
        decision_id=body.decision_id,
        command_hash=body.command_hash,
        expected_versions=body.expected_versions,
        ttl_seconds=body.ttl_seconds,
        budget_amount=body.budget_amount,
        budget_id=body.budget_id,
    )
    return schemas.MintLeaseResponse(
        lease_id=lease.lease_id,
        lease_token=lease_token,
        grant_id=lease.grant_id,
        decision_id=lease.decision_id,
        command_hash=lease.command_hash,
        expected_versions=lease.expected_versions,
        state=lease.state,
        ttl_seconds=lease.ttl_seconds,
        expires_at=lease.expires_at,
        reserved_budget=lease.reserved_budget,
        created_at=lease.created_at,
    )


@router.get(
    "/leases",
    response_model=schemas.AuthorityLeaseListOut,
    summary="List AuthorityLeases for tenant",
)
async def list_leases(
    ctx: TenantCtxDep,
    state: Annotated[str | None, Query()] = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
) -> schemas.AuthorityLeaseListOut:
    items, total = await AuthorityService.list_leases(
        ctx.session, ctx.tenant_id, state=state, limit=limit, offset=offset
    )
    return schemas.AuthorityLeaseListOut(
        items=[schemas.AuthorityLeaseOut.model_validate(l, from_attributes=True) for l in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/leases/{lease_id}/revoke",
    response_model=schemas.AuthorityLeaseOut,
    summary="Revoke an active AuthorityLease",
)
async def revoke_lease(
    ctx: WriteCtx,
    lease_id: uuid.UUID,
) -> schemas.AuthorityLeaseOut:
    lease = await AuthorityService.revoke_lease(ctx.session, ctx.tenant_id, lease_id)
    return schemas.AuthorityLeaseOut.model_validate(lease, from_attributes=True)


# ---------------------------------------------------------------- Atomic Execution


@router.post(
    "/execute",
    response_model=schemas.ExecutionResultOut,
    summary="Execute command through the Canonical 15-step Atomic Execution Boundary",
)
async def execute_command(
    ctx: WriteCtx,
    body: schemas.ExecuteCommandRequest,
) -> schemas.ExecutionResultOut:
    return await AtomicExecutionService.execute_command(
        ctx.session,
        ctx.tenant_id,
        lease_token=body.lease_token,
        action=body.action,
        resource=body.resource,
        arguments=body.arguments,
        purpose=body.purpose,
        current_versions=body.current_versions,
    )


# ---------------------------------------------------------------- Autonomy Budgets


@router.post(
    "/budgets",
    response_model=schemas.AutonomyBudgetOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an AutonomyBudget",
)
async def create_budget(
    ctx: WriteCtx,
    body: schemas.AutonomyBudgetCreate,
) -> schemas.AutonomyBudgetOut:
    budget = await AuthorityService.create_budget(
        ctx.session,
        ctx.tenant_id,
        name=body.name,
        total_limit=body.total_limit,
        currency=body.currency,
        period=body.period,
        actor_id=body.actor_id,
        parent_budget_id=body.parent_budget_id,
    )
    return _budget_out(budget)


@router.get(
    "/budgets",
    response_model=list[schemas.AutonomyBudgetOut],
    summary="List AutonomyBudgets for tenant",
)
async def list_budgets(
    ctx: TenantCtxDep,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
) -> list[schemas.AutonomyBudgetOut]:
    budgets, _ = await AuthorityService.list_budgets(
        ctx.session, ctx.tenant_id, limit=limit, offset=offset
    )
    return [_budget_out(b) for b in budgets]


@router.get(
    "/budgets/{budget_id}",
    response_model=schemas.AutonomyBudgetOut,
    summary="Get an AutonomyBudget by ID",
)
async def get_budget(
    ctx: TenantCtxDep,
    budget_id: uuid.UUID,
) -> schemas.AutonomyBudgetOut:
    budget = await AuthorityService.get_budget(ctx.session, ctx.tenant_id, budget_id)
    return _budget_out(budget)


def _budget_out(b: AutonomyBudget) -> schemas.AutonomyBudgetOut:
    available = b.total_limit - b.spent_amount - b.reserved_amount
    return schemas.AutonomyBudgetOut(
        budget_id=b.budget_id,
        actor_id=b.actor_id,
        parent_budget_id=b.parent_budget_id,
        name=b.name,
        period=b.period,
        currency=b.currency,
        total_limit=b.total_limit,
        spent_amount=b.spent_amount,
        reserved_amount=b.reserved_amount,
        available_amount=available,
        reset_at=b.reset_at,
        created_at=b.created_at,
        updated_at=b.updated_at,
    )
