"""Effect Ledger API router (V12 Wave C)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.modules.effects import schemas
from app.modules.effects.models import EffectLedger
from app.modules.effects.service import EffectService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission

router = APIRouter(prefix="/effects", tags=["effects"])

WriteCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]

PageLimit = Annotated[int, Query(ge=1, le=schemas.PAGE_LIMIT_MAX)]
PageOffset = Annotated[int, Query(ge=0)]


def _effect_dict(effect: EffectLedger) -> dict:
    return {
        "effect_id": effect.effect_id,
        "tenant_id": effect.tenant_id,
        "idempotency_key": effect.idempotency_key,
        "operation": effect.operation,
        "workflow_id": effect.workflow_id,
        "task_id": effect.task_id,
        "decision_id": effect.decision_id,
        "lease_id": effect.lease_id,
        "status": effect.status,
        "provider": effect.provider,
        "provider_reference": effect.provider_reference,
        "arguments": effect.arguments or {},
        "result": effect.result,
        "error_details": effect.error_details,
        "attempts": effect.attempts,
        "last_attempt_at": effect.last_attempt_at,
        "resolved_at": effect.resolved_at,
        "created_at": effect.created_at,
        "updated_at": effect.updated_at,
    }


@router.post("", response_model=schemas.EffectOut, status_code=201)
async def record_effect_intent(ctx: WriteCtx, body: schemas.EffectIntentCreate):
    """Record an effect intent or retrieve existing by deterministic idempotency key."""
    effect = await EffectService.record_intent(
        ctx.session,
        ctx.tenant_id,
        operation=body.operation,
        arguments=body.arguments,
        workflow_id=body.workflow_id,
        task_id=body.task_id,
        decision_id=body.decision_id,
        lease_id=body.lease_id,
        provider=body.provider,
    )
    return _effect_dict(effect)


@router.get("/{effect_id}", response_model=schemas.EffectOut)
async def get_effect(effect_id: uuid.UUID, ctx: TenantCtxDep):
    """Retrieve an effect by ID."""
    effect = await EffectService.get(ctx.session, ctx.tenant_id, effect_id)
    return _effect_dict(effect)


@router.get("", response_model=schemas.EffectListOut)
async def list_effects(
    ctx: TenantCtxDep,
    status: Annotated[str | None, Query(max_length=32)] = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """List effects for the tenant with optional status filter."""
    conditions = [EffectLedger.tenant_id == ctx.tenant_id]
    if status:
        conditions.append(EffectLedger.status == status)

    total = (
        await ctx.session.execute(select(func.count(EffectLedger.effect_id)).where(*conditions))
    ).scalar_one()

    rows = (
        (
            await ctx.session.execute(
                select(EffectLedger)
                .where(*conditions)
                .order_by(EffectLedger.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )

    return {
        "items": [_effect_dict(row) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.post("/{effect_id}/reconcile", response_model=schemas.EffectOut)
async def reconcile_effect(
    effect_id: uuid.UUID,
    body: schemas.EffectResolve,
    ctx: WriteCtx,
):
    """Reconcile an AMBIGUOUS effect to COMPLETED or FAILED."""
    effect = await EffectService.reconcile_effect(
        ctx.session,
        ctx.tenant_id,
        effect_id,
        resolution_status=body.status,
        provider_reference=body.provider_reference,
        result=body.result,
        error_details=body.error_details,
    )
    return _effect_dict(effect)
