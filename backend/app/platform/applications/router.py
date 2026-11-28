"""What this workspace has, and what each product is waiting on.

The sidebar cannot decide for itself whether a screen exists: only the server
knows what was paid for and what setup finished. This route is the one place the
interface asks, so "you did not buy this" and "you have not finished setting this
up" arrive as different reasons instead of a missing menu item.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.platform.applications.access import describe
from app.platform.applications.install import install_entitled
from app.platform.applications.repository import entitled, installed
from app.platform.identity.deps import TenantCtxDep

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


@router.post("/install")
async def install_applications(ctx: TenantCtxDep) -> dict[str, Any]:
    """Record what this workspace is licensed for, so the gate has something to read.

    A workspace that finished setup before the installations table existed has no
    rows, and the gate has to let it through as "not configured yet". This closes
    that window for the workspace making the request - and only for it: the id
    comes from the resolved context, never from the request body, so nobody can
    install a product into somebody else's business. It installs only what the
    live subscription already covers, so it cannot grant anything unpaid.
    """
    workspace_id = getattr(ctx, "workspace_id", None)
    if not workspace_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="choose a workspace before installing applications",
        )
    installed_keys = await install_entitled(
        ctx.session, tenant_id=ctx.tenant_id, workspace_id=workspace_id
    )
    return {
        "workspace_id": str(workspace_id),
        "installed": installed_keys,
    }
