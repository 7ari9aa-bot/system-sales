"""Staff routes for the store's own posts and comments (Instagram).

Read needs the Instagram channel to be visible to the user; every action that
speaks for the store (reply, hide, delete, private reply) needs it to be SENDABLE,
the same stricter grant a chat reply needs. The platform is called first and our
row changes only after it accepted, so the screen never shows something that did not happen.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.modules.conversations.gateway.instagram import instagram_adapter
from app.modules.conversations.models import SocialComment, SocialPost
from app.modules.conversations.routers._deps import (
    TenantContext,
    require_permission,
)
from app.modules.conversations.routers.inbox import (
    _allowed_channels,
    _channel_config,
    _sendable_channels,
)
from app.modules.conversations.social_service import (
    MAX_PICTURE_BYTES,
    MAX_REPLY_CHARS,
    SocialService,
)

router = APIRouter(tags=["social"])

_PROVIDER = "instagram"


class CommentReplyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_REPLY_CHARS)


class CommentHideRequest(BaseModel):
    hidden: bool = True


class PostCommentsToggleRequest(BaseModel):
    enabled: bool


class PublishPostRequest(BaseModel):
    """One picture, or 2-10 for a carousel. Each picture is a base64 JPEG."""

    pictures: list[str] = Field(min_length=1, max_length=10)
    caption: str | None = Field(default=None, max_length=2200)


def _decode_picture(value: str, number: int) -> bytes:
    # Refuse an oversized one before decoding it: base64 is ~4/3 of the real size.
    if len(value) > (MAX_PICTURE_BYTES * 4) // 3 + 8:
        raise ValidationError(f"picture {number} is larger than 8 MB")
    if value.startswith("data:"):  # a browser data URL: keep only the payload
        value = value.partition(",")[2]
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError(f"picture {number} is not valid base64") from exc


def _post_out(p: SocialPost) -> dict:
    return {
        "id": p.post_id,
        "caption": p.caption,
        "media_url": p.media_url,
        "thumbnail_url": p.thumbnail_url,
        "media_type": p.media_type,
        "permalink": p.permalink,
        "like_count": p.like_count,
        "comments_count": p.comments_count,
        "comments_enabled": p.comments_enabled,
        "posted_at": p.posted_at.isoformat() if p.posted_at else None,
        "publish_status": p.publish_status,
    }


def _comment_out(c: SocialComment) -> dict:
    return {
        "id": c.comment_id,
        "post_id": c.post_id,
        "parent_id": c.parent_comment_id,
        "username": c.username or c.author_name,
        "body": c.body,
        "like_count": c.like_count,
        "commented_at": c.commented_at.isoformat() if c.commented_at else None,
        "status": c.status,
        "is_page_reply": c.is_page_reply,
        "replied_at": c.replied_at.isoformat() if c.replied_at else None,
        "private_replied_at": c.private_replied_at.isoformat() if c.private_replied_at else None,
    }


async def _credentials(ctx: TenantContext, *, send: bool) -> dict:
    """The connected Instagram account's credentials, after the channel grants are checked."""
    allowed = await _allowed_channels(ctx)
    if allowed is not None and _PROVIDER not in allowed:
        raise PermissionDeniedError("channel is not enabled for this user")
    if send:
        sendable = await _sendable_channels(ctx)
        if sendable is not None and _PROVIDER not in sendable:
            raise PermissionDeniedError("sending is not enabled for this user on this channel")
    config = await _channel_config(ctx, _PROVIDER)
    if not config or not config.get("api_key") or not config.get("account_id"):
        raise ConflictError("Instagram is not connected")
    return config


@router.get("/social/account")
async def get_account(
    ctx: TenantContext = Depends(require_permission("conversations:read")),
):
    """The connected Instagram account as its profile page shows it (name, bio, counts)."""
    creds = await _credentials(ctx, send=False)
    return await instagram_adapter.get_account(creds)


@router.get("/social/posts")
async def list_posts(
    refresh: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    before: datetime | None = None,
    ctx: TenantContext = Depends(require_permission("conversations:read")),
):
    """The store's posts, newest first. `refresh=true` pulls the latest from Instagram first."""
    if refresh:
        creds = await _credentials(ctx, send=False)
        await SocialService.sync_posts(ctx.session, ctx.tenant_id, creds, limit=limit)
    else:
        await _credentials(ctx, send=False)
    posts = await SocialService.list_posts(ctx.session, ctx.tenant_id, limit=limit, before=before)
    return {"items": [_post_out(p) for p in posts]}


@router.get("/social/posts/{post_id}/comments")
async def list_post_comments(
    post_id: str,
    refresh: bool = False,
    ctx: TenantContext = Depends(require_permission("conversations:read")),
):
    """A post's comments, oldest first, replies carrying their parent id."""
    creds = await _credentials(ctx, send=False)
    if refresh:
        await SocialService.sync_comments(ctx.session, ctx.tenant_id, creds, post_id)
    comments = await SocialService.list_comments(ctx.session, ctx.tenant_id, post_id)
    return {"items": [_comment_out(c) for c in comments]}


@router.get("/social/posts/{post_id}/insights")
async def post_insights(
    post_id: str,
    ctx: TenantContext = Depends(require_permission("conversations:read")),
):
    """How one post performed (reach, views, likes, ...). A number not produced yet is null."""
    creds = await _credentials(ctx, send=False)
    post = await SocialService.get_post(ctx.session, ctx.tenant_id, post_id)
    if post is None:
        raise NotFoundError("post not found")
    metrics = await instagram_adapter.get_media_insights(creds, post.post_id, post.media_type)
    return {"post_id": post.post_id, "metrics": metrics}


@router.post("/social/comments/{comment_id}/reply", status_code=201)
async def reply_to_comment(
    comment_id: str,
    body: CommentReplyRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    creds = await _credentials(ctx, send=True)
    reply = await SocialService.reply_publicly(
        ctx.session, ctx.tenant_id, creds, comment_id, body.text, user_id=ctx.user.id
    )
    return _comment_out(reply)


@router.post("/social/comments/{comment_id}/hide")
async def hide_comment(
    comment_id: str,
    body: CommentHideRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    creds = await _credentials(ctx, send=True)
    row = await SocialService.set_hidden(
        ctx.session, ctx.tenant_id, creds, comment_id, body.hidden, user_id=ctx.user.id
    )
    return _comment_out(row)


@router.delete("/social/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: str,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    creds = await _credentials(ctx, send=True)
    await SocialService.delete(ctx.session, ctx.tenant_id, creds, comment_id, user_id=ctx.user.id)


@router.post("/social/comments/{comment_id}/private-reply", status_code=201)
async def private_reply(
    comment_id: str,
    body: CommentReplyRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """One private message to the commenter, within 7 days of the comment."""
    creds = await _credentials(ctx, send=True)
    message_id = await SocialService.send_private_reply(
        ctx.session, ctx.tenant_id, creds, comment_id, body.text, user_id=ctx.user.id
    )
    return {"message_id": message_id}


@router.post("/social/posts/{post_id}/comments-enabled")
async def toggle_post_comments(
    post_id: str,
    body: PostCommentsToggleRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    creds = await _credentials(ctx, send=True)
    await SocialService.set_comments_enabled(
        ctx.session, ctx.tenant_id, creds, post_id, body.enabled
    )
    return {"post_id": post_id, "comments_enabled": body.enabled}


@router.post("/social/posts", status_code=201)
async def publish_post(
    body: PublishPostRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Publish a photo (1 picture) or a carousel (2-10) to the store's Instagram.

    Instagram accepts JPEG only and allows 100 API posts per account per 24 hours.
    The post is recorded here only after Instagram accepted it.
    """
    creds = await _credentials(ctx, send=True)
    pictures = [_decode_picture(v, i) for i, v in enumerate(body.pictures, start=1)]
    media_id = await SocialService.publish_post(
        ctx.session, ctx.tenant_id, creds, pictures, body.caption
    )
    return {"post_id": media_id}
