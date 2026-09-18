"""CUSTOMERS routes — list/search; plus PLATFORM routes for the settings screen
(invitations list, integrations)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.pagination import decode_cursor, page_slice
from app.modules.customers.service import CustomerService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.identity.models import Invitation, Role
from app.modules.platform.models import Integration

router = APIRouter(tags=["customers"])
platform_router = APIRouter(tags=["platform"])


@router.get("/customers")
async def list_customers(
    ctx: TenantCtxDep,
    search: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    before_created_at, before_id = decode_cursor(cursor) if cursor else (None, None)
    rows = await CustomerService.list_customers(
        ctx.session,
        ctx.tenant_id,
        search=search,
        limit=limit + 1,
        before_created_at=before_created_at,
        before_id=before_id,
    )
    page, next_cursor = page_slice(rows, limit)
    return {
        "items": [
            {
                "id": str(c.id),
                "name": c.name,
                "phone": c.phone,
                "email": c.email,
                "lifetime_value": str(c.lifetime_value),
                "is_blocked": c.is_blocked,
            }
            for c in page
        ],
        "next_cursor": next_cursor,
    }


class IntegrationBody(BaseModel):
    provider: str = Field(max_length=63)
    kind: str = "channel"
    config: dict = {}
    credentials: dict = {}
    status: str = "connected"


@platform_router.get("/invitations")
async def list_invitations(
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    rows = (
        await ctx.session.execute(
            select(Invitation, Role.code)
            .outerjoin(Role, Role.id == Invitation.role_id)
            .where(Invitation.tenant_id == ctx.tenant_id)
            .order_by(Invitation.created_at.desc())
            .limit(50)
        )
    ).all()
    return [
        {
            "id": str(invitation.id),
            "email": invitation.email,
            "role_code": role_code,
            "status": invitation.status,
        }
        for invitation, role_code in rows
    ]


@platform_router.get("/integrations")
async def list_integrations(ctx: TenantCtxDep):
    rows = (
        (
            await ctx.session.execute(
                select(Integration).where(Integration.tenant_id == ctx.tenant_id).limit(100)
            )
        )
        .scalars()
        .all()
    )
    return [
        {"id": str(i.id), "provider": i.provider, "kind": i.kind, "status": i.status} for i in rows
    ]


@platform_router.post("/integrations", status_code=201)
async def upsert_integration(
    body: IntegrationBody,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Register/refresh a channel integration (WhatsApp/Telegram/webchat keys)."""
    existing = (
        await ctx.session.execute(
            select(Integration).where(
                Integration.tenant_id == ctx.tenant_id,
                Integration.provider == body.provider,
                Integration.kind == body.kind,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.config = body.config
        existing.credentials = body.credentials
        existing.status = body.status
        return {"id": str(existing.id), "status": existing.status}
    integration = Integration(
        tenant_id=ctx.tenant_id,
        provider=body.provider,
        kind=body.kind,
        config=body.config,
        credentials=body.credentials,
        status=body.status,
    )
    ctx.session.add(integration)
    await ctx.session.flush()
    return {"id": str(integration.id), "status": integration.status}
