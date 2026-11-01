"""Owner console — cross-tenant health, channel matrix and visitor telemetry.

This is the deployment operator's plane (``users.is_platform_admin``), not a
tenant role. Reads are aggregate/status metadata; the channel matrix exposes
member names/roles because the owner explicitly manages per-user access.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.core.db import bind_tenant
from app.core.redis import get_redis
from app.modules.identity.models import Role, Tenant, TenantUser, User
from app.modules.platform.channel_specs.registry import list_connection_specs
from app.modules.platform.models import (
    ChannelUserAccess,
    Integration,
    OutboxEvent,
    VisitorEvent,
    WebhookEvent,
)
from app.modules.platform.routers._deps import TenantCtxDep, _require_platform_admin
from app.modules.platform.services.channel_access import channel_status, set_access

router = APIRouter(prefix="/owner", tags=["owner"])


class OwnerOverviewOut(BaseModel):
    status: str
    generated_at: datetime
    counts: dict[str, int]
    subsystems: list[dict[str, Any]]
    channels: list[dict[str, Any]]
    recent_visitors: list[dict[str, Any]]


class OwnerTenantRowOut(BaseModel):
    id: uuid.UUID
    name: str
    lifecycle_state: str
    is_active: bool
    users: int
    channels_connected: int
    channels_total: int


class OwnerTenantListOut(BaseModel):
    items: list[OwnerTenantRowOut]
    total: int


class OwnerChannelMatrixOut(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    providers: list[dict[str, Any]]
    members: list[dict[str, Any]]
    access: list[dict[str, Any]]


class OwnerVisitorListOut(BaseModel):
    items: list[dict[str, Any]]
    total: int
    unique_visitors: int
    top_paths: list[dict[str, Any]]


class ChannelAccessUpdate(BaseModel):
    enabled: bool = True
    can_send: bool = True


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def _tenant_integrations(session, tenant_id: uuid.UUID) -> list[Integration]:
    await bind_tenant(session, tenant_id)
    return (
        (
            await session.execute(
                select(Integration).where(
                    Integration.tenant_id == tenant_id,
                    Integration.kind == "channel",
                )
            )
        )
        .scalars()
        .all()
    )


async def _counts(session) -> dict[str, int]:
    tenant_total = (await session.execute(select(func.count(Tenant.id)))).scalar_one()
    active_tenants = (
        await session.execute(select(func.count(Tenant.id)).where(Tenant.is_active.is_(True)))
    ).scalar_one()
    users = (await session.execute(select(func.count(User.id)))).scalar_one()
    platform_admins = (
        await session.execute(select(func.count(User.id)).where(User.is_platform_admin.is_(True)))
    ).scalar_one()
    pending_outbox = (
        await session.execute(
            select(func.count(OutboxEvent.id)).where(OutboxEvent.status == "pending")
        )
    ).scalar_one()
    since = datetime.now(UTC) - timedelta(hours=24)
    visitors_24h = (
        await session.execute(
            select(func.count(func.distinct(VisitorEvent.visitor_id))).where(
                VisitorEvent.created_at >= since
            )
        )
    ).scalar_one()
    events_24h = (
        await session.execute(
            select(func.count(VisitorEvent.id)).where(VisitorEvent.created_at >= since)
        )
    ).scalar_one()
    failed_webhooks = (
        await session.execute(
            select(func.count(WebhookEvent.id)).where(
                WebhookEvent.processing_status.in_(("failed", "dead")),
                WebhookEvent.received_at >= since,
            )
        )
    ).scalar_one()
    return {
        "tenants": int(tenant_total or 0),
        "active_tenants": int(active_tenants or 0),
        "users": int(users or 0),
        "platform_admins": int(platform_admins or 0),
        "pending_outbox": int(pending_outbox or 0),
        "visitors_24h": int(visitors_24h or 0),
        "visitor_events_24h": int(events_24h or 0),
        "failed_webhooks_24h": int(failed_webhooks or 0),
    }


async def _subsystems(session, tenants: list[Tenant]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        await session.execute(text("SELECT 1"))
        rows.append({"name": "database", "status": "healthy"})
    except Exception as exc:  # noqa: BLE001
        rows.append({"name": "database", "status": "down", "detail": type(exc).__name__})

    try:
        await get_redis().ping()
        rows.append({"name": "redis", "status": "healthy"})
    except Exception as exc:  # noqa: BLE001
        rows.append({"name": "redis", "status": "down", "detail": type(exc).__name__})

    oldest = (
        await session.execute(
            select(func.min(OutboxEvent.created_at)).where(OutboxEvent.status == "pending")
        )
    ).scalar_one_or_none()
    if oldest is None:
        rows.append({"name": "outbox", "status": "healthy", "detail": "no pending events"})
    else:
        lag = max(int((datetime.now(UTC) - oldest).total_seconds()), 0)
        status = "down" if lag >= 600 else "degraded" if lag >= 60 else "healthy"
        rows.append(
            {"name": "outbox", "status": status, "detail": f"oldest pending event is {lag}s old"}
        )

    try:
        client = get_redis()
        depth = 0
        for stream in (
            "message.events.dlq",
            "notification.events.dlq",
            "webhook.events.dlq",
            "platform.events.dlq",
        ):
            depth += int(await client.xlen(stream) or 0)
        status = "down" if depth >= 50 else "degraded" if depth >= 1 else "healthy"
        rows.append({"name": "dlq", "status": status, "detail": f"{depth} dead-lettered events"})
    except Exception as exc:  # noqa: BLE001
        rows.append({"name": "dlq", "status": "degraded", "detail": type(exc).__name__})

    integration_total = 0
    connected_total = 0
    for tenant in tenants:
        integrations = await _tenant_integrations(session, tenant.id)
        integration_total += len(integrations)
        connected_total += sum(1 for row in integrations if row.status in ("active", "connected"))
    rows.append(
        {
            "name": "integrations",
            "status": "healthy",
            "detail": f"{connected_total}/{integration_total} channels connected",
        }
    )
    return rows


async def _channel_summary(session, tenants: list[Tenant]) -> list[dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {
        spec.name: {
            "provider": spec.name,
            "display_name": spec.display_name,
            "connected_tenants": 0,
            "total_tenants": len(tenants),
            "attention": 0,
        }
        for spec in list_connection_specs()
    }
    for tenant in tenants:
        for row in await _tenant_integrations(session, tenant.id):
            bucket = summary.get(row.provider)
            if bucket is None:
                continue
            if row.status in ("active", "connected"):
                bucket["connected_tenants"] += 1
            elif row.status in ("reauth_required", "restricted", "error"):
                bucket["attention"] += 1
    return list(summary.values())


@router.get("/overview", response_model=OwnerOverviewOut)
async def owner_overview(ctx: TenantCtxDep) -> OwnerOverviewOut:
    _require_platform_admin(ctx)
    tenants = (
        (await ctx.session.execute(select(Tenant).order_by(Tenant.created_at.desc())))
        .scalars()
        .all()
    )
    counts = await _counts(ctx.session)
    subsystems = await _subsystems(ctx.session, list(tenants))
    channels = await _channel_summary(ctx.session, list(tenants))
    recent = (
        (
            await ctx.session.execute(
                select(VisitorEvent).order_by(VisitorEvent.created_at.desc()).limit(8)
            )
        )
        .scalars()
        .all()
    )
    worst = (
        "down"
        if any(row["status"] == "down" for row in subsystems)
        else ("degraded" if any(row["status"] == "degraded" for row in subsystems) else "healthy")
    )
    return OwnerOverviewOut(
        status=worst,
        generated_at=datetime.now(UTC),
        counts=counts,
        subsystems=subsystems,
        channels=channels,
        recent_visitors=[
            {
                "id": str(row.id),
                "event_type": row.event_type,
                "path": row.path,
                "visitor_id": row.visitor_id,
                "created_at": _iso(row.created_at),
                "duration_ms": row.duration_ms,
                "status_code": row.status_code,
            }
            for row in recent
        ],
    )


@router.get("/tenants", response_model=OwnerTenantListOut)
async def owner_tenants(
    ctx: TenantCtxDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OwnerTenantListOut:
    _require_platform_admin(ctx)
    total = (await ctx.session.execute(select(func.count(Tenant.id)))).scalar_one()
    tenants = (
        (
            await ctx.session.execute(
                select(Tenant)
                .order_by(Tenant.created_at.desc(), Tenant.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    since = datetime.now(UTC) - timedelta(hours=24)
    items: list[OwnerTenantRowOut] = []
    for tenant in tenants:
        users = (
            await ctx.session.execute(
                select(func.count(TenantUser.user_id)).where(TenantUser.tenant_id == tenant.id)
            )
        ).scalar_one()
        integrations = await _tenant_integrations(ctx.session, tenant.id)
        visitors = (
            await ctx.session.execute(
                select(func.count(func.distinct(VisitorEvent.visitor_id))).where(
                    VisitorEvent.created_at >= since
                )
            )
        ).scalar_one()
        items.append(
            OwnerTenantRowOut(
                id=tenant.id,
                name=tenant.name,
                lifecycle_state=tenant.lifecycle_state,
                is_active=tenant.is_active,
                users=int(users or 0),
                channels_connected=sum(
                    1 for row in integrations if row.status in ("active", "connected")
                ),
                channels_total=len(integrations),
                visitors_24h=int(visitors or 0),
            )
        )
    return OwnerTenantListOut(items=items, total=int(total or 0))


@router.get("/tenants/{tenant_id}/channels", response_model=OwnerChannelMatrixOut)
async def owner_channel_matrix(ctx: TenantCtxDep, tenant_id: uuid.UUID) -> OwnerChannelMatrixOut:
    _require_platform_admin(ctx)
    tenant = (
        await ctx.session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("tenant not found")

    await bind_tenant(ctx.session, tenant_id)
    providers = await channel_status(ctx.session, tenant_id, ctx.user.id, "owner")
    members = (
        await ctx.session.execute(
            select(User.id, User.email, User.full_name, Role.code)
            .select_from(TenantUser)
            .join(User, User.id == TenantUser.user_id)
            .join(Role, Role.id == TenantUser.role_id)
            .where(TenantUser.tenant_id == tenant_id)
            .order_by(User.full_name.asc())
        )
    ).all()
    access_rows = (
        (
            await ctx.session.execute(
                select(ChannelUserAccess).where(ChannelUserAccess.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    access = [
        {
            "user_id": str(row.user_id),
            "provider": row.provider,
            "enabled": row.is_enabled,
            "can_send": row.can_send,
        }
        for row in access_rows
    ]
    return OwnerChannelMatrixOut(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        providers=providers,
        members=[
            {
                "id": str(row.id),
                "email": row.email,
                "full_name": row.full_name,
                "role_code": row.code,
            }
            for row in members
        ],
        access=access,
    )


@router.put("/tenants/{tenant_id}/channels/{provider}/users/{user_id}")
async def owner_set_channel_access(
    ctx: TenantCtxDep,
    tenant_id: uuid.UUID,
    provider: str,
    user_id: uuid.UUID,
    body: ChannelAccessUpdate,
) -> dict[str, Any]:
    _require_platform_admin(ctx)
    await bind_tenant(ctx.session, tenant_id)
    row = await set_access(
        ctx.session,
        tenant_id,
        user_id,
        provider,
        enabled=body.enabled,
        can_send=body.can_send,
        actor_user_id=ctx.user.id,
    )
    await ctx.session.commit()
    return {
        "user_id": str(row.user_id),
        "provider": row.provider,
        "enabled": row.is_enabled,
        "can_send": row.can_send,
    }


@router.get("/visitors", response_model=OwnerVisitorListOut)
async def owner_visitors(
    ctx: TenantCtxDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> OwnerVisitorListOut:
    _require_platform_admin(ctx)
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = (
        (
            await ctx.session.execute(
                select(VisitorEvent)
                .where(VisitorEvent.created_at >= since)
                .order_by(VisitorEvent.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    total = (
        await ctx.session.execute(
            select(func.count(VisitorEvent.id)).where(VisitorEvent.created_at >= since)
        )
    ).scalar_one()
    unique = (
        await ctx.session.execute(
            select(func.count(func.distinct(VisitorEvent.visitor_id))).where(
                VisitorEvent.created_at >= since
            )
        )
    ).scalar_one()
    top = (
        await ctx.session.execute(
            select(VisitorEvent.path, func.count(VisitorEvent.id).label("n"))
            .where(VisitorEvent.created_at >= since)
            .group_by(VisitorEvent.path)
            .order_by(func.count(VisitorEvent.id).desc())
            .limit(8)
        )
    ).all()
    return OwnerVisitorListOut(
        items=[
            {
                "id": str(row.id),
                "visitor_id": row.visitor_id,
                "session_id": row.session_id,
                "event_type": row.event_type,
                "path": row.path,
                "url": row.url,
                "referrer": row.referrer,
                "element": row.element,
                "status_code": row.status_code,
                "duration_ms": row.duration_ms,
                "metadata": row.metadata_json,
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ],
        total=int(total or 0),
        unique_visitors=int(unique or 0),
        top_paths=[{"path": path, "count": int(count)} for path, count in top],
    )
