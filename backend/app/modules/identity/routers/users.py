"""Identity users HTTP routes."""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.core.errors import PayloadTooLargeError, StorageUnavailableError
from app.core.mfa import is_mfa_enabled
from app.core.storage import FetchedMedia, get_storage
from app.modules.identity import avatar, schemas, service
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.identity.models import Role, TenantUser, User

users_router = APIRouter(prefix="/users", tags=["users"])


async def _current_user(session, user_id) -> schemas.CurrentUser:
    """The signed-in account as every screen sees it (profile, sidebar, avatar)."""
    full = await service.UserService.get(session, user_id)
    tenants = await service.TenantService.list_for_user(session, user_id)
    return schemas.CurrentUser(
        id=full.id,
        email=full.email,
        full_name=full.full_name,
        is_platform_admin=full.is_platform_admin,
        avatar_url=avatar.read_url(full.avatar_url),
        mfa_enabled=await is_mfa_enabled(session, user_id=user_id),
        email_verified=bool(full.email_verified),
        phone=full.phone,
        job_title=full.job_title,
        tenants=[
            schemas.CurrentTenant(
                id=t.id, name=t.name, slug=t.slug, role_code=role, currency=t.currency
            )
            for t, role in tenants
        ],
    )


@users_router.get("/me", response_model=schemas.CurrentUser)
async def my_profile(ctx: TenantCtxDep):
    return await _current_user(ctx.session, ctx.user.id)


@users_router.patch("/me", response_model=schemas.CurrentUser)
async def update_my_profile(body: schemas.ProfileUpdate, ctx: TenantCtxDep):
    """Rewrite the caller's own display name, phone and job title.

    It answers with the WHOLE account rather than the changed field, so the
    screen renders what the server now holds instead of echoing the input back
    to itself. Nothing here can touch another user: the id comes from the
    verified token, never from the body.
    """
    await service.UserService.update_profile(
        ctx.session,
        ctx.user.id,
        full_name=body.full_name,
        phone=body.phone,
        job_title=body.job_title,
    )
    return await _current_user(ctx.session, ctx.user.id)


@users_router.put("/me/avatar")
async def set_my_avatar(request: Request, ctx: TenantCtxDep):
    """Store the signed-in user's own picture: raw bytes, screened, then bucketed.

    The bytes decide what the file is, so a renamed upload cannot smuggle
    another format, and the size cap is applied while streaming — a client that
    lies about `Content-Length` still cannot fill the bucket.
    """
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > avatar.MAX_AVATAR_BYTES:
            raise PayloadTooLargeError(f"an avatar must be at most {avatar.MAX_AVATAR_BYTES} bytes")
    data = bytes(chunks)
    avatar.screen(content_type, data)

    storage = get_storage()
    if not storage.configured:
        raise StorageUnavailableError()
    stored = await storage.store(
        FetchedMedia(
            data=data,
            content_type=content_type,
            checksum=hashlib.sha256(data).hexdigest(),
        ),
        prefix=f"avatars/{ctx.user.id}",
        original_url="",
    )
    if not stored.durable or not stored.storage_key:
        raise StorageUnavailableError()
    await service.UserService.set_avatar_url(ctx.session, ctx.user.id, f"s3://{stored.storage_key}")
    return {"avatar_url": avatar.read_url(f"s3://{stored.storage_key}", storage=storage)}


@users_router.delete("/me/avatar")
async def clear_my_avatar(ctx: TenantCtxDep):
    """Forget the picture. The object itself goes with the media retention sweep."""
    await service.UserService.clear_avatar_url(ctx.session, ctx.user.id)
    return {"avatar_url": None}


def _closure_state(state: dict) -> schemas.AccountClosureState:
    request = state["request"]
    return schemas.AccountClosureState(
        request=schemas.AccountClosureRequestOut.model_validate(request) if request else None,
        blockers=[schemas.AccountClosureBlocker(**blocker) for blocker in state["blockers"]],
        memberships=state["memberships"],
    )


@users_router.get("/me/closure-request", response_model=schemas.AccountClosureState)
async def my_closure_request(ctx: TenantCtxDep):
    """What the "close my account" card draws: the open request, or why none can open.

    ``blockers`` names every shop this person administers alone. The card shows
    them instead of letting the person submit a request that must be refused.
    """
    state = await service.AccountClosureService.state(ctx.session, ctx.user.id)
    return _closure_state(state)


@users_router.post(
    "/me/closure-request", response_model=schemas.AccountClosureState, status_code=201
)
async def open_my_closure_request(body: schemas.AccountClosureRequestIn, ctx: TenantCtxDep):
    """Ask to close the account (or erase the personal data too). A request, not a deletion."""
    await service.AccountClosureService.open(
        ctx.session, ctx.user.id, mode=body.mode, reason=body.reason
    )
    state = await service.AccountClosureService.state(ctx.session, ctx.user.id)
    return _closure_state(state)


@users_router.delete("/me/closure-request", status_code=204)
async def cancel_my_closure_request(ctx: TenantCtxDep):
    """Withdraw the open request before the platform decides on it."""
    await service.AccountClosureService.cancel(ctx.session, ctx.user.id)


# The roster carries every teammate's email and role, so reading it is a settings read: the owner
# and manager have it, a cashier does not (the cashier's shift screen already copes with that).
SettingsReadCtx = Annotated[TenantContext, Depends(require_permission("settings:read"))]


@users_router.get("")
async def list_tenant_members(ctx: SettingsReadCtx):
    """The tenant's members — the POS profile-grant picker's source.

    Read-only and tenant-scoped: only the members of the caller's own
    tenant, with the role each membership carries.
    """
    rows = (
        await ctx.session.execute(
            select(User.id, User.email, User.full_name, Role.code)
            .select_from(TenantUser)
            .join(User, User.id == TenantUser.user_id)
            .join(Role, Role.id == TenantUser.role_id)
            .where(TenantUser.tenant_id == ctx.tenant_id)
            .order_by(User.full_name.asc())
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "email": row.email,
            "full_name": row.full_name,
            "role_code": row.code,
        }
        for row in rows
    ]
