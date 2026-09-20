"""PLATFORM routes — feature flags (§76) and the metric registry (§167).

Flags are rollout switches, not authorization. The registry is read-only: it
tells every screen what a number means so two screens cannot compute it
differently.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.errors import ValidationError
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.platform.flags import FeatureFlagService
from app.modules.platform.metrics import MetricRegistry
from app.modules.platform.models import FeatureFlag

router = APIRouter(prefix="/platform", tags=["platform"])

FEATURE_MAX_LEN = 127  # matches feature_flags.feature String(127)


class FlagUpsert(BaseModel):
    """Body for ``PUT /platform/flags/{feature}``."""

    enabled: bool = True
    workspace_id: uuid.UUID | None = None
    role_code: str | None = Field(default=None, max_length=63)
    rollout_percent: int = Field(default=100, ge=0, le=100)


def _flag_payload(flag: FeatureFlag) -> dict:
    return {
        "feature": flag.feature,
        "enabled": flag.enabled,
        "workspace_id": str(flag.workspace_id) if flag.workspace_id else None,
        "role_code": flag.role_code,
        "rollout_percent": flag.rollout_percent,
    }


@router.get("/flags")
async def list_flags(ctx: TenantCtxDep):
    """Every feature flag configured for the caller's tenant."""
    flags = await FeatureFlagService.list_flags(ctx.session, ctx.tenant_id)
    return [_flag_payload(flag) for flag in flags]


@router.put("/flags/{feature}")
async def upsert_flag(
    feature: str,
    body: FlagUpsert,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Create or replace the tenant's flag for ``feature`` (idempotent)."""
    if not feature or len(feature) > FEATURE_MAX_LEN:
        raise ValidationError(
            f"feature name must be 1-{FEATURE_MAX_LEN} characters",
            details={"feature": feature},
        )
    flag = await FeatureFlagService.set_flag(
        ctx.session,
        ctx.tenant_id,
        feature,
        enabled=body.enabled,
        workspace_id=body.workspace_id,
        role_code=body.role_code,
        rollout_percent=body.rollout_percent,
    )
    return _flag_payload(flag)


@router.get("/flags/{feature}/check")
async def check_flag(ctx: TenantCtxDep, feature: str):
    """Evaluate ``feature`` for the calling user — used to hide a UI affordance.

    A flag is NOT authorization. This endpoint only tells the client whether to
    *render* something. A disabled flag hides a button; it does not protect the
    action behind that button. The action still needs its own server-side RBAC
    check (``require_permission``) — never branch a security decision on the
    value returned here.

    The caller's user id is passed as ``stable_key`` so a per-user percentage
    rollout buckets the same user consistently across requests. Workspace-scoped
    rows evaluate to false here because the request context carries no workspace.
    """
    enabled = await FeatureFlagService.is_enabled(
        ctx.session,
        ctx.tenant_id,
        feature,
        role_code=ctx.role_code,
        stable_key=str(ctx.user.id),
    )
    return {"feature": feature, "enabled": enabled}


@router.get("/metrics")
async def list_metric_definitions(ctx: TenantCtxDep):
    """The canonical metric registry (§167) — one definition per number.

    Reads need only a tenant context. Every screen must resolve a metric through
    this registry rather than re-deriving the formula, so the same number is not
    computed differently in two places.
    """
    return MetricRegistry.definitions()
