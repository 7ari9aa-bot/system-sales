"""Identity users HTTP routes."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.core.errors import PayloadTooLargeError, StorageUnavailableError
from app.core.storage import FetchedMedia, get_storage
from app.modules.identity import avatar, schemas, service
from app.modules.identity.deps import TenantCtxDep
from app.modules.identity.models import Role, TenantUser, User

users_router = APIRouter(prefix="/users", tags=["users"])


@users_router.get("/me", response_model=schemas.CurrentUser)
async def my_profile(ctx: TenantCtxDep):
    full = await service.UserService.get(ctx.session, ctx.user.id)
    tenants = await service.TenantService.list_for_user(ctx.session, ctx.user.id)
    return schemas.CurrentUser(
        id=full.id,
        email=full.email,
        full_name=full.full_name,
        is_platform_admin=full.is_platform_admin,
        avatar_url=avatar.read_url(full.avatar_url),
        tenants=[
            schemas.CurrentTenant(id=t.id, name=t.name, slug=t.slug, role_code=role)
            for t, role in tenants
        ],
    )


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


@users_router.get("")
async def list_tenant_members(ctx: TenantCtxDep):
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
