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

    count = await NotificationService.unread_count(ctx.session, ctx.tenant_id, ctx.user.id)
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

    count = await NotificationService.mark_all_read(ctx.session, ctx.tenant_id, ctx.user.id)
    return schemas.MarkReadResult(marked=count)


# --------------------------------------------------------------------------
# The person's own notification settings.
#
# They live on a /users/me prefix because that is who owns them: no workspace-admin
# permission is needed to decide whether YOU want email, and a route under
# /notifications would read as workspace configuration. The workspace's own rules
# (section 16 of the settings map) are a different surface and a different
# permission.
# --------------------------------------------------------------------------

me_router = APIRouter(prefix="/users/me", tags=["notifications"])


def _hhmm(value) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


@me_router.get(
    "/notification-preferences",
    summary="Read the caller's own notification channels and quiet hours",
    response_model=schemas.NotificationPreferencesOut,
)
async def my_notification_preferences(ctx: TenantCtxDep) -> schemas.NotificationPreferencesOut:
    """What this person's notifications actually do, and why.

    Reading creates the row when it is missing, because "no row" and "email is on"
    are the same state: a screen that shows neither cannot be reasoned about.
    """
    from app.modules.notifications.digest import NotificationAggregator
    from app.modules.notifications.service import (
        NotificationPreferencesService,
        person_local_time,
        person_timezone,
    )

    pref = await NotificationPreferencesService.get_or_create(
        ctx.session, ctx.tenant_id, ctx.user.id
    )
    zone = await person_timezone(ctx.session, ctx.tenant_id, ctx.user.id)
    local_now = await person_local_time(ctx.session, ctx.tenant_id, ctx.user.id)
    quiet_on = pref.quiet_start is not None and pref.quiet_end is not None

    from app.core.settings_read import resolve_settings

    workspace = await resolve_settings(
        ctx.session,
        ctx.tenant_id,
        ["notifications.email_enabled", "notifications.push_enabled"],
    )

    return schemas.NotificationPreferencesOut(
        channels=[
            schemas.ChannelPreference(
                channel="in_app",
                label_key="notif.channel.inApp",
                enabled=True,
                available=True,
                locked=True,
            ),
            schemas.ChannelPreference(
                channel="email",
                label_key="notif.channel.email",
                enabled=pref.email_enabled,
                available=True,
            ),
            schemas.ChannelPreference(
                channel="push",
                label_key="notif.channel.push",
                enabled=pref.push_enabled,
                available=True,
            ),
        ],
        quiet_hours=schemas.QuietHours(
            start=_hhmm(pref.quiet_start),
            end=_hhmm(pref.quiet_end),
            active_now=quiet_on
            and NotificationAggregator._in_quiet_hours(pref, now_time=local_now),
        ),
        timezone=zone,
        workspace={
            "email": bool(workspace["notifications.email_enabled"]),
            "push": bool(workspace["notifications.push_enabled"]),
        },
    )


@me_router.put(
    "/notification-preferences",
    summary="Change the caller's own notification channels or quiet hours",
    response_model=schemas.NotificationPreferencesOut,
)
async def update_my_notification_preferences(
    body: schemas.NotificationPreferencesUpdate, ctx: TenantCtxDep
) -> schemas.NotificationPreferencesOut:
    """Save one switch or the window, then answer with the whole state.

    The response is the same shape the GET returns, so the screen renders what the
    server now holds instead of echoing the request back to itself.
    """
    from app.modules.notifications.service import NotificationPreferencesService

    await NotificationPreferencesService.update(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        email_enabled=body.email_enabled,
        push_enabled=body.push_enabled,
        quiet_start=body.quiet_start,
        quiet_end=body.quiet_end,
    )
    return await my_notification_preferences(ctx)
