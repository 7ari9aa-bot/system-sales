"""Platform admin plane (§160) and break-glass emergency access (§147).

A platform admin is NOT a tenant user. This plane exists for the operator
who runs the deployment itself: list all tenants, see tenant health, and
take provisioning actions (suspend, provision, etc.). It is gated by a
platform-admin role that is separate from any tenant's RBAC.

The §160 design rule: the admin plane must never expose tenant data
(customers, messages, orders) — only tenant metadata and health. A
platform admin can see THAT a tenant exists and WHETHER it is healthy,
not WHAT is inside it.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.modules.platform import schemas
from app.modules.platform.models import OutboxEvent
from app.modules.platform.routers._deps import (
    PageLimit,
    PageOffset,
    TenantCtxDep,
    _require_platform_admin,
)

router = APIRouter(prefix="/platform", tags=["platform"])


@router.get("/admin/tenants", response_model=schemas.TenantListOut)
async def admin_list_tenants(
    ctx: TenantCtxDep,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """§160: list all tenants on the deployment (metadata only, no tenant data).

    The one cross-tenant list on this plane, and until now the one unbounded
    read of it: a deployment's whole tenant count was the size of the dump an
    operator's accidental ``GET`` pulled. Paged with the module's shared ceiling.

    Ordered ``(created_at, id)`` DESC, not ``created_at`` DESC. Tenants
    provisioned together share one ``now()`` — the seed and any bulk provisioning
    run produce stretches of identical timestamps — and an un-tied ORDER BY lets
    PostgreSQL break those ties differently on each read, so across pages one
    tenant is listed twice while another is never listed at all. ``id`` (the
    primary key) is the tie-break that makes the sort a total order.
    """
    _require_platform_admin(ctx)
    from app.modules.identity.models import Tenant

    total = (await ctx.session.execute(select(func.count(Tenant.id)))).scalar_one()
    rows = (
        await ctx.session.execute(
            select(
                Tenant.id,
                Tenant.name,
                Tenant.lifecycle_state,
                Tenant.is_active,
                Tenant.created_at,
            )
            .order_by(Tenant.created_at.desc(), Tenant.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return {
        "items": [
            {
                "id": str(row.id),
                "name": row.name,
                "lifecycle_state": row.lifecycle_state,
                "is_active": row.is_active,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/admin/tenants/{tenant_id}", response_model=schemas.TenantDetailOut)
async def admin_get_tenant(ctx: TenantCtxDep, tenant_id: uuid.UUID):
    """§160: one tenant's metadata + health (no customer/message data)."""
    _require_platform_admin(ctx)
    from app.modules.identity.models import Tenant

    tenant = (
        await ctx.session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("tenant not found")

    # Count outbox backlog for this tenant (not the contents — just the depth).
    # `outbox_events` is a system table with no tenant column: §19 put tenancy
    # inside the envelope, so the filter reads meta->>'tenant_id' — the same key
    # the relay refuses to publish without. A comparison on OutboxEvent.tenant_id
    # does not even reach SQL; the attribute does not exist. `ix_outbox_status_created`
    # carries the status half of this predicate; nothing indexes the envelope.
    outbox_pending = (
        await ctx.session.execute(
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.meta["tenant_id"].as_string() == str(tenant_id),
                OutboxEvent.status == "pending",
            )
        )
    ).scalar_one()

    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "lifecycle_state": tenant.lifecycle_state,
        "is_active": tenant.is_active,
        "status_reason": tenant.status_reason,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "health": {
            "outbox_pending": int(outbox_pending or 0),
        },
    }


@router.patch("/admin/tenants/{tenant_id}/status", response_model=schemas.TenantStatusOut)
async def admin_update_tenant_status(
    ctx: TenantCtxDep,
    tenant_id: uuid.UUID,
    status: str,
    reason: str | None = None,
    x_break_glass_token: Annotated[str | None, Header()] = None,
):
    """§160/§48: move a tenant's lifecycle state (suspend, reactivate, ...).

    §147: this is a cross-tenant privileged action, so platform-admin rights
    alone are NOT enough — the caller must present a one-shot break-glass
    capability scoped to this tenant and ``tenant_status_change``.

    The mutation runs through TenantLifecycleService.transition — the single
    writer that validates the state machine, keeps ``is_active`` consistent
    and writes the before/after audit + security trail (§66/§67). Request
    validation happens BEFORE the capability is consumed: a bad request must
    not destroy the one-shot token.
    """
    _require_platform_admin(ctx)
    from app.modules.identity.models import Tenant
    from app.modules.identity.service import STATE_POLICIES, TenantLifecycleService

    if status not in STATE_POLICIES:
        raise ValidationError(
            "unknown tenant lifecycle state",
            details={"status": status, "allowed": sorted(STATE_POLICIES)},
        )
    tenant = (
        await ctx.session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("tenant not found")

    from app.core.break_glass import validate_capability

    elevated = await validate_capability(
        x_break_glass_token or "",
        tenant_id=tenant_id,
        user_id=ctx.user.id,
        action="tenant_status_change",
    )
    if not elevated:
        raise PermissionDeniedError(
            "tenant status changes require a break-glass capability scoped to "
            "this tenant (POST /platform/admin/break-glass with "
            "action=tenant_status_change)"
        )
    tenant = await TenantLifecycleService.transition(
        ctx.session,
        tenant_id,
        status,
        reason=reason,
        actor_user_id=ctx.user.id,
    )
    return {
        "id": str(tenant.id),
        "lifecycle_state": tenant.lifecycle_state,
        "is_active": tenant.is_active,
    }


class BreakGlassRequest(BaseModel):
    """Body for POST /platform/admin/break-glass."""

    tenant_id: uuid.UUID
    action: str = Field(min_length=1, max_length=255)
    resource_type: str = Field(min_length=1, max_length=63)
    resource_id: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=10, max_length=2000)


@router.post("/admin/break-glass", response_model=schemas.BreakGlassOut)
async def admin_break_glass(
    ctx: TenantCtxDep,
    body: BreakGlassRequest,
    request: Request,
):
    """§147: emergency access — records a security event + issues a capability token.

    The token is one-shot and expires in 15 minutes. The event is NEVER silent:
    even the platform admin's own break-glass is recorded.
    """
    _require_platform_admin(ctx)
    from app.core.break_glass import break_glass

    token = await break_glass(
        ctx.session,
        tenant_id=body.tenant_id,
        user_id=ctx.user.id,
        action=body.action,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        reason=body.reason,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return {"capability_token": token, "expires_in_minutes": 15}


class BreakGlassValidateRequest(BaseModel):
    """Body for POST /platform/admin/break-glass/validate."""

    capability_token: str
    tenant_id: uuid.UUID
    action: str


@router.post("/admin/break-glass/validate", response_model=schemas.BreakGlassValidateOut)
async def admin_validate_break_glass(
    ctx: TenantCtxDep,
    body: BreakGlassValidateRequest,
):
    """§147: pre-flight check whether a capability token is valid.

    Read-only on purpose: a *check* must not burn the one-shot token — the
    capability is consumed by the protected action itself (GETDEL there).
    """
    _require_platform_admin(ctx)
    from app.core.break_glass import peek_capability

    valid = await peek_capability(
        body.capability_token,
        tenant_id=body.tenant_id,
        user_id=ctx.user.id,
        action=body.action,
    )
    return {"valid": valid}
