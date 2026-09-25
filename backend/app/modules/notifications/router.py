"""NOTIFICATIONS HTTP routes.

Every route names its reply (see ``schemas.py`` for why an anonymous body is not
a contract), the list's ``limit``/``offset`` are bounded here and re-checked in
the service, and a mark-read miss raises ``NotFoundError`` — HTTP 404 — instead
of the 200-with-``detail`` the register filed as P3.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.modules.identity.deps import TenantCtxDep
from app.modules.notifications import schemas
from app.modules.notifications.schemas import (
    OFFSET_MAX,
    PAGE_MAX,
    MarkReadRequest,
    NotificationOut,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "",
    summary="List notifications for the current user",
    response_model=list[NotificationOut],
)
async def list_notifications(
    ctx: TenantCtxDep,
    unread_only: bool = False,
    kind: str | None = None,
    limit: Annotated[int, Query(ge=1, le=PAGE_MAX)] = 50,
    offset: Annotated[int, Query(ge=0, le=OFFSET_MAX)] = 0,
) -> list[NotificationOut]:
    from app.modules.notifications.service import NotificationService

    rows = await NotificationService.list_for_user(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        unread_only=unread_only,
        kind=kind,
        limit=limit,
        offset=offset,
    )
    return [NotificationOut.from_row(r) for r in rows]


@router.get(
    "/unread-count",
    summary="Count of unread notifications",
    response_model=schemas.UnreadCount,
)
async def unread_count(ctx: TenantCtxDep) -> schemas.UnreadCount:
    from app.modules.notifications.service import NotificationService

    count = await NotificationService.unread_count(
        ctx.session, ctx.tenant_id, ctx.user.id
    )
    return schemas.UnreadCount(count=count)


@router.get(
    "/summary",
    summary="Totals the notifications centre labels its filters with",
    response_model=schemas.NotificationSummary,
)
async def summary(ctx: TenantCtxDep) -> schemas.NotificationSummary:
    from app.modules.notifications.service import NotificationService

    totals = await NotificationService.summary(ctx.session, ctx.tenant_id, ctx.user.id)
    return schemas.NotificationSummary.model_validate(totals)


@router.get(
    "/digest",
    summary="§166: grouped unread notifications for the bell's collapsed view",
    response_model=schemas.NotificationDigest,
)
async def digest(ctx: TenantCtxDep) -> schemas.NotificationDigest:
    from app.modules.notifications.service import NotificationService

    grouped = await NotificationService.digest(ctx.session, ctx.tenant_id, ctx.user.id)
    return schemas.NotificationDigest.model_validate(grouped)


@router.patch(
    "/{notification_id}/read",
    summary="Mark one notification as read",
    response_model=NotificationOut,
)
async def mark_read(
    notification_id: uuid.UUID,
    ctx: TenantCtxDep,
) -> NotificationOut:
    from app.modules.notifications.service import NotificationService

    notif = await NotificationService.mark_read(
        ctx.session, ctx.tenant_id, ctx.user.id, notification_id
    )
    return NotificationOut.from_row(notif)


@router.post(
    "/mark-read",
    summary="Mark a set of notifications as read",
    response_model=schemas.MarkReadResult,
)
async def mark_many_read(body: MarkReadRequest, ctx: TenantCtxDep) -> schemas.MarkReadResult:
    from app.modules.notifications.service import NotificationService

    count = await NotificationService.mark_many_read(
        ctx.session, ctx.tenant_id, ctx.user.id, body.ids
    )
    return schemas.MarkReadResult(marked=count)


@router.post(
    "/mark-all-read",
    summary="Mark all notifications as read",
    response_model=schemas.MarkReadResult,
)
async def mark_all_read(ctx: TenantCtxDep) -> schemas.MarkReadResult:
    from app.modules.notifications.service import NotificationService

    count = await NotificationService.mark_all_read(
        ctx.session, ctx.tenant_id, ctx.user.id
    )
    return schemas.MarkReadResult(marked=count)
