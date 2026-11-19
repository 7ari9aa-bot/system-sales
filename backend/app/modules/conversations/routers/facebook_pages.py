"""Staff routes for the Facebook Page's own posts and comments.

Read needs the Facebook channel visible to the user; every action that speaks for the Page
needs it SENDABLE (the grant a chat reply needs). Meta is called first, our row changes after.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.modules.conversations.facebook_service import FacebookService
from app.modules.conversations.gateway.facebook_pages import facebook_pages
from app.modules.conversations.routers._deps import TenantContext, require_permission
from app.modules.conversations.routers.inbox import (
    _allowed_channels,
    _channel_config,
    _sendable_channels,
)
from app.modules.conversations.routers.social import _comment_out

router = APIRouter(tags=["facebook"])

_PROVIDER = "facebook"


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class HideRequest(BaseModel):
    hidden: bool = True


class LikeRequest(BaseModel):
    liked: bool = True


class PublishRequest(BaseModel):
    """Text, a link, or one picture (public https link); `schedule_at` schedules it."""

    message: str | None = Field(default=None, max_length=63206)
    link: str | None = Field(default=None, max_length=2000, pattern=r"^https?://")
    photo_url: str | None = Field(default=None, max_length=2000, pattern=r"^https://")
    schedule_at: datetime | None = None


class EditRequest(BaseModel):
    message: str = Field(min_length=1, max_length=63206)


def _post_out(p) -> dict:
    return {
        "id": p.post_id,
        "message": p.caption,
        "picture": p.media_url,
        "type": p.media_type,
        "permalink": p.permalink,
        "reactions": p.like_count,
        "comments": p.comments_count,
        "posted_at": p.posted_at.isoformat() if p.posted_at else None,
    }


async def _credentials(ctx: TenantContext, *, send: bool) -> dict:
    allowed = await _allowed_channels(ctx)
    if allowed is not None and _PROVIDER not in allowed:
        raise PermissionDeniedError("channel is not enabled for this user")
    if send:
        sendable = await _sendable_channels(ctx)
        if sendable is not None and _PROVIDER not in sendable:
            raise PermissionDeniedError("sending is not enabled for this user on this channel")
    config = await _channel_config(ctx, _PROVIDER)
    if not config or not config.get("api_key") or not config.get("account_id"):
        raise ConflictError("Facebook is not connected")
    return config


@router.get("/facebook/page")
async def get_page(ctx: TenantContext = Depends(require_permission("conversations:read"))):
    """The connected Page as its profile shows it (name, about, followers, cover, contact)."""
    return await facebook_pages.get_page(await _credentials(ctx, send=False))


@router.get("/facebook/posts")
async def list_posts(
    refresh: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    before: datetime | None = None,
    ctx: TenantContext = Depends(require_permission("conversations:read")),
):
    creds = await _credentials(ctx, send=False)
    if refresh:
        await FacebookService.sync_posts(ctx.session, ctx.tenant_id, creds, limit=limit)
    posts = await FacebookService.list_posts(ctx.session, ctx.tenant_id, limit=limit, before=before)
    return {"items": [_post_out(p) for p in posts]}


@router.get("/facebook/scheduled")
async def list_scheduled(ctx: TenantContext = Depends(require_permission("conversations:read"))):
    """Posts waiting for their time. They live only on Facebook, so this reads it live."""
    page = await facebook_pages.list_posts(await _credentials(ctx, send=False), scheduled=True)
    return {
        "items": [
            {
                "id": p.get("id"),
                "message": p.get("message"),
                "picture": p.get("full_picture"),
                "scheduled_for": p.get("scheduled_publish_time"),
            }
            for p in page["items"]
        ]
    }


@router.post("/facebook/posts", status_code=201)
async def publish_post(
    body: PublishRequest, ctx: TenantContext = Depends(require_permission("conversations:write"))
):
    creds = await _credentials(ctx, send=True)
    post_id = await FacebookService.publish(
        ctx.session,
        ctx.tenant_id,
        creds,
        message=body.message,
        link=body.link,
        photo_url=body.photo_url,
        schedule_at=body.schedule_at,
    )
    return {"id": post_id, "scheduled": body.schedule_at is not None}


@router.patch("/facebook/posts/{post_id}")
async def edit_post(
    post_id: str,
    body: EditRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Meta lets an app edit only a post it published itself; others are refused."""
    creds = await _credentials(ctx, send=True)
    return _post_out(
        await FacebookService.edit(ctx.session, ctx.tenant_id, creds, post_id, body.message)
    )


@router.delete("/facebook/posts/{post_id}", status_code=204)
async def delete_post(
    post_id: str, ctx: TenantContext = Depends(require_permission("conversations:write"))
):
    creds = await _credentials(ctx, send=True)
    await FacebookService.remove_post(ctx.session, ctx.tenant_id, creds, post_id)


@router.get("/facebook/posts/{post_id}/comments")
async def list_post_comments(
    post_id: str,
    refresh: bool = False,
    ctx: TenantContext = Depends(require_permission("conversations:read")),
):
    creds = await _credentials(ctx, send=False)
    if refresh:
        await FacebookService.sync_comments(ctx.session, ctx.tenant_id, creds, post_id)
    rows = await FacebookService.list_comments(ctx.session, ctx.tenant_id, post_id)
    return {"items": [_comment_out(c) for c in rows]}


@router.post("/facebook/objects/{object_id}/comments", status_code=201)
async def comment_or_reply(
    object_id: str,
    body: TextRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """A comment on a post, or a reply when `object_id` is a comment."""
    creds = await _credentials(ctx, send=True)
    row = await FacebookService.reply(
        ctx.session, ctx.tenant_id, creds, object_id, body.text, user_id=ctx.user.id
    )
    return _comment_out(row)


@router.post("/facebook/objects/{object_id}/like")
async def like_object(
    object_id: str,
    body: LikeRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """The Page likes (or un-likes) a post or comment as itself."""
    creds = await _credentials(ctx, send=True)
    await facebook_pages.like(creds, object_id, body.liked)
    return {"id": object_id, "liked": body.liked}


@router.post("/facebook/comments/{comment_id}/hide")
async def hide_comment(
    comment_id: str,
    body: HideRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    creds = await _credentials(ctx, send=True)
    row = await FacebookService.set_hidden(
        ctx.session, ctx.tenant_id, creds, comment_id, body.hidden, user_id=ctx.user.id
    )
    return _comment_out(row)


@router.delete("/facebook/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: str, ctx: TenantContext = Depends(require_permission("conversations:write"))
):
    creds = await _credentials(ctx, send=True)
    await FacebookService.remove_comment(
        ctx.session, ctx.tenant_id, creds, comment_id, user_id=ctx.user.id
    )


@router.post("/facebook/comments/{comment_id}/private-reply", status_code=201)
async def private_reply(
    comment_id: str,
    body: TextRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """One private Messenger message to the commenter, within 7 days of the comment."""
    creds = await _credentials(ctx, send=True)
    mid = await FacebookService.private_reply(
        ctx.session, ctx.tenant_id, creds, comment_id, body.text, user_id=ctx.user.id
    )
    return {"message_id": mid}


@router.get("/facebook/insights")
async def page_insights(
    since: int | None = None,
    until: int | None = None,
    ctx: TenantContext = Depends(require_permission("conversations:read")),
):
    creds = await _credentials(ctx, send=False)
    return {"metrics": await facebook_pages.get_page_insights(creds, since=since, until=until)}


@router.get("/facebook/posts/{post_id}/insights")
async def post_insights(
    post_id: str, ctx: TenantContext = Depends(require_permission("conversations:read"))
):
    creds = await _credentials(ctx, send=False)
    if await FacebookService.get_post(ctx.session, ctx.tenant_id, post_id) is None:
        raise NotFoundError("post not found")
    return {"post_id": post_id, "metrics": await facebook_pages.get_post_insights(creds, post_id)}


__all__ = ["router", "ValidationError"]
