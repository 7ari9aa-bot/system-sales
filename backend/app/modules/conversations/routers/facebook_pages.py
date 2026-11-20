"""Staff routes for the Facebook Page's own posts and comments.

Read needs the Facebook channel visible to the user; every action that speaks for the Page
needs it SENDABLE (the grant a chat reply needs). Meta is called first, our row changes after.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.modules.conversations.facebook_service import MAX_PICTURE_BYTES, FacebookService
from app.modules.conversations.gateway import facebook_video
from app.modules.conversations.gateway.facebook_pages import facebook_pages, page_token_and_id
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
    """Text, a link, or one picture; `schedule_at` schedules it.

    The picture is either a file (`picture`, base64, up to 4 MB: what the screen sends) or a public
    https link someone else hosts (`photo_url`). Never both, and a picture never rides with a link.
    """

    message: str | None = Field(default=None, max_length=63206)
    link: str | None = Field(default=None, max_length=2000, pattern=r"^https?://")
    photo_url: str | None = Field(default=None, max_length=2000, pattern=r"^https://")
    picture: str | None = Field(default=None, max_length=(MAX_PICTURE_BYTES * 4) // 3 + 200)
    schedule_at: datetime | None = None


def _decode_picture(value: str) -> bytes:
    if value.startswith("data:"):  # a browser data URL: keep only the payload
        value = value.partition(",")[2]
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("the picture is not valid base64") from exc


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
    token, page_id = page_token_and_id(config or {})
    if not token or not page_id:
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
    if body.picture and body.photo_url:
        raise ValidationError("send a picture file or a picture link, not both")
    if body.picture and body.link:
        raise ValidationError("a post carries a picture or a link, not both")
    creds = await _credentials(ctx, send=True)
    if body.picture:
        post_id = await FacebookService.publish_picture(
            ctx.session,
            ctx.tenant_id,
            creds,
            picture=_decode_picture(body.picture),
            message=body.message,
            schedule_at=body.schedule_at,
        )
    else:
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


async def _read_body(request: Request, limit: int, what: str) -> bytes:
    """The raw file the screen sent, refused as soon as it passes `limit`."""
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > limit:
            raise ValidationError(
                f"the {what} is too large", details={"reason": "too_large", "max_bytes": limit}
            )
    return bytes(chunks)


def _header_text(request: Request, name: str) -> str | None:
    """A text the screen sent in a header, percent-encoded so Arabic survives."""
    from urllib.parse import unquote

    raw = request.headers.get(name)
    return unquote(raw).strip() or None if raw else None


@router.post("/facebook/reels", status_code=201)
async def publish_reel(
    request: Request, ctx: TenantContext = Depends(require_permission("conversations:write"))
):
    """Publish a Reel. The raw mp4 is the body; text, title and time travel in headers.

    `X-Description`, `X-Title` (percent-encoded), `X-Schedule-At` (ISO time, 10 minutes to 29
    days away) and `X-AI-Generated: true` are all optional.
    """
    creds = await _credentials(ctx, send=True)
    video = await _read_body(request, facebook_video.MAX_VIDEO_BYTES, "video")
    schedule_at = None
    if raw := request.headers.get("x-schedule-at"):
        try:
            schedule_at = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValidationError("the schedule time is not a valid date") from exc
    video_id = await FacebookService.publish_reel(
        ctx.session,
        ctx.tenant_id,
        creds,
        video=video,
        description=_header_text(request, "x-description"),
        title=_header_text(request, "x-title"),
        schedule_at=schedule_at,
        is_ai_generated=request.headers.get("x-ai-generated", "").lower() == "true",
    )
    return {"id": video_id, "scheduled": schedule_at is not None}


@router.post("/facebook/stories", status_code=201)
async def publish_story(
    request: Request, ctx: TenantContext = Depends(require_permission("conversations:write"))
):
    """Publish a Story: the raw file is the body, and its Content-Type says video or picture."""
    creds = await _credentials(ctx, send=True)
    kind = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if kind == "video/mp4":
        video = await _read_body(request, facebook_video.MAX_VIDEO_BYTES, "video")
        story_id = await FacebookService.publish_story(
            ctx.session, ctx.tenant_id, creds, video=video
        )
    elif kind.startswith("image/"):
        photo = await _read_body(request, facebook_video.MAX_STORY_PHOTO_BYTES, "picture")
        story_id = await FacebookService.publish_story(
            ctx.session, ctx.tenant_id, creds, photo=photo
        )
    else:
        raise ValidationError("a Story is an mp4 video or a picture")
    return {"id": story_id}


@router.get("/facebook/reels")
async def list_reels(
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    after: str | None = None,
    ctx: TenantContext = Depends(require_permission("conversations:read")),
):
    page = await facebook_pages.list_reels(
        await _credentials(ctx, send=False), limit=limit, after=after
    )
    return {
        "items": [
            {
                "id": r.get("id"),
                "description": r.get("description"),
                "title": r.get("title"),
                "picture": r.get("picture"),
                "permalink": r.get("permalink_url"),
                "length": r.get("length"),
                "updated_at": r.get("updated_time"),
            }
            for r in page["items"]
        ],
        "next": page["next"],
    }


@router.get("/facebook/stories")
async def list_stories(ctx: TenantContext = Depends(require_permission("conversations:read"))):
    stories = await facebook_pages.list_stories(await _credentials(ctx, send=False))
    return {
        "items": [
            {
                "id": s.get("post_id"),
                "status": s.get("status"),
                "type": s.get("media_type"),
                "url": s.get("url"),
                "created_at": s.get("creation_time"),
            }
            for s in stories
        ]
    }


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
