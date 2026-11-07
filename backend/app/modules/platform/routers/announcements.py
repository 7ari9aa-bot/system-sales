"""Tenant-facing announcements read path — the banner's only data source.

Writes live in the owner console (platform-authority surface). This router is
read + dismiss for any authenticated tenant user: a banner everyone can see
needs no permission code, and the dismissal is strictly per CALLING user — the
service never accepts a user_id from the request.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.modules.platform.routers._deps import TenantCtxDep
from app.modules.platform.services.announcements import active_for_user, dismiss

router = APIRouter(prefix="/platform/announcements", tags=["announcements"])


class AnnouncementOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    cta_label: str | None = None
    cta_url: str | None = None
    dismissible: bool
    starts_at: str
    ends_at: str | None = None


class AnnouncementActiveOut(BaseModel):
    announcement: AnnouncementOut | None = None


class AnnouncementDismissOut(BaseModel):
    dismissed: bool


@router.get("/active", response_model=AnnouncementActiveOut)
async def get_active_announcement(ctx: TenantCtxDep) -> AnnouncementActiveOut:
    """The live banner for this tenant and user, or an honest null."""
    row = await active_for_user(ctx.session, ctx.tenant_id, ctx.user.id)
    if row is None:
        return AnnouncementActiveOut(announcement=None)
    return AnnouncementActiveOut(
        announcement=AnnouncementOut(
            id=row.id,
            kind=row.kind,
            title=row.title,
            body=row.body,
            cta_label=row.cta_label,
            cta_url=row.cta_url,
            dismissible=row.dismissible,
            starts_at=row.starts_at.isoformat(),
            ends_at=row.ends_at.isoformat() if row.ends_at else None,
        )
    )


@router.post("/{announcement_id}/dismiss", response_model=AnnouncementDismissOut)
async def dismiss_announcement(
    ctx: TenantCtxDep, announcement_id: uuid.UUID
) -> AnnouncementDismissOut:
    """Tombstone the banner for THIS user only; idempotent."""
    dismissed = await dismiss(ctx.session, announcement_id, ctx.user.id, tenant_id=ctx.tenant_id)
    return AnnouncementDismissOut(dismissed=dismissed)
