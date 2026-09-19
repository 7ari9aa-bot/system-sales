"""NOTIFICATIONS HTTP routes."""
from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.modules.identity.deps import TenantCtxDep

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str | None
    body: str
    action_url: str | None
    payload: dict
    read_at: str | None
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_iso(cls, obj) -> "NotificationOut":
        return cls(
            id=obj.id,
            kind=obj.kind,
            title=obj.title,
            body=obj.body,
            action_url=obj.action_url,
            payload=obj.payload or {},
            read_at=obj.read_at.isoformat() if obj.read_at else None,
            created_at=obj.created_at.isoformat(),
        )


class MarkReadRequest(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


@router.get("", summary="List notifications for the current user")
async def list_notifications(
    ctx: TenantCtxDep,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[NotificationOut]:
    from app.modules.notifications.service import NotificationService

    rows = await NotificationService.list_for_user(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )
    return [NotificationOut.from_orm_iso(r) for r in rows]


@router.get("/unread-count", summary="Count of unread notifications")
async def unread_count(ctx: TenantCtxDep) -> dict[str, int]:
    from app.modules.notifications.service import NotificationService

    count = await NotificationService.unread_count(
        ctx.session, ctx.tenant_id, ctx.user.id
    )
    return {"count": count}


@router.patch("/{notification_id}/read", summary="Mark one notification as read")
async def mark_read(
    notification_id: uuid.UUID,
    ctx: TenantCtxDep,
) -> NotificationOut | dict:
    from app.modules.notifications.service import NotificationService

    notif = await NotificationService.mark_read(
        ctx.session, ctx.tenant_id, ctx.user.id, notification_id
    )
    if notif is None:
        return {"detail": "not found"}
    return NotificationOut.from_orm_iso(notif)


@router.post("/mark-all-read", summary="Mark all notifications as read")
async def mark_all_read(ctx: TenantCtxDep) -> dict[str, int]:
    from app.modules.notifications.service import NotificationService

    count = await NotificationService.mark_all_read(
        ctx.session, ctx.tenant_id, ctx.user.id
    )
    return {"marked": count}
