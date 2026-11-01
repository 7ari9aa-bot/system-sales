"""Tenant channel status for the inbox and settings surfaces."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.identity.deps import TenantCtxDep
from app.modules.platform.services.channel_access import channel_status

router = APIRouter(prefix="/channels", tags=["channels"])


@router.get("/status")
async def list_channel_status(ctx: TenantCtxDep) -> list[dict]:
    """Connection truth + THIS user's access, with no credential material.

    Membership-gated on purpose: staff need to know which channels are locked
    in the inbox, but ``GET /integrations`` is settings-scoped and exposes
    webhook URLs/keys they must not see.
    """
    return await channel_status(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        ctx.role_code,
    )
