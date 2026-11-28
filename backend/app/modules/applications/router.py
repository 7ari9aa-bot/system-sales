"""What this workspace has, and what each product is waiting on.

The sidebar cannot decide for itself whether a screen exists: only the server
knows what was paid for and what setup finished. This route is the one place the
interface asks, so "you did not buy this" and "you have not finished setting this
up" arrive as different reasons instead of a missing menu item.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.modules.applications.access import describe
from app.modules.applications.repository import entitled, installed
from app.modules.identity.deps import TenantCtxDep

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("")
async def list_applications(ctx: TenantCtxDep) -> dict[str, Any]:
    """Every application, with this workspace's verdict on it."""
    workspace_id = getattr(ctx, "workspace_id", None)
    states = await installed(ctx.session, workspace_id=workspace_id) if workspace_id else {}
    facts = {
        "entitled_applications": await entitled(
            ctx.session, tenant_id=ctx.tenant_id, workspace_id=workspace_id
        ),
        "installation_states": states,
    }
    return {
        "workspace_id": str(workspace_id) if workspace_id else None,
        "applications": [dict(row) for row in describe(facts)],
    }
