"""The Facebook Page's own posts and comments: pulled from Meta, changed through Meta.

Same tables as Instagram (`social_posts`, `social_comments`, platform="facebook"), so no
migration. The platform is called FIRST and our row changes only after it accepted, so the
screen never shows something that did not happen. A sync never overwrites a moderation
status we set ourselves.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.storage import FetchedMedia, get_storage
from app.modules.conversations.gateway import facebook_video
from app.modules.conversations.gateway.facebook_pages import facebook_pages
from app.modules.conversations.models import SocialComment, SocialPost

PLATFORM = "facebook"

_logger = logging.getLogger(__name__)

#: Facebook's own ceiling for a picture sent to a Page (Pages API: photos).
MAX_PICTURE_BYTES = 4 * 1024 * 1024
#: Facebook fetches the picture once, right away; the link only has to outlive that.
PICTURE_LINK_SECONDS = 15 * 60
#: Facebook fetches a video once it has been told where it is; it needs longer than for a picture
#: (the file is bigger), but the link still only has to outlive the fetch and the processing.
VIDEO_LINK_SECONDS = 30 * 60
# The kind is read from the file's first bytes, never from its name or the header the browser sent.
_PICTURE_KINDS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


def picture_kind(data: bytes) -> str | None:
    """The type of these bytes when Facebook takes them (JPEG, PNG, GIF, BMP, WEBP), else None."""
    for magic, kind in _PICTURE_KINDS:
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _time(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return datetime.now(UTC)


def _count(node: Any) -> int:
    return int(((node or {}).get("summary") or {}).get("total_count") or 0)


def _media_type(post: dict) -> str:
    atts = (post.get("attachments") or {}).get("data") or []
    kind = str((atts[0] if atts else {}).get("media_type") or post.get("status_type") or "")
    return kind.upper() or "STATUS"


#: Pages of 50 comments read for one post in one refresh. A cursor that never ends stops here.
MAX_COMMENT_PAGES = 20

#: Meta takes a handful of tags in one comment, not a crowd.
MAX_MENTIONS = 5


class FacebookService:
    @staticmethod
    async def sync_posts(
        session: AsyncSession, tenant_id: uuid.UUID, credentials: dict, *, limit: int = 25
    ) -> int:
        page = await facebook_pages.list_posts(credentials, limit=limit)
        now = datetime.now(UTC)
        n = 0
        for p in page["items"]:
            pid = str(p.get("id") or "")
            if not pid:
                continue
            values = dict(
                tenant_id=tenant_id,
                platform=PLATFORM,
                post_id=pid,
                caption=p.get("message"),
                media_url=p.get("full_picture"),
                thumbnail_url=p.get("full_picture"),
                media_type=_media_type(p),
                permalink=p.get("permalink_url"),
                like_count=_count(p.get("reactions")),
                comments_count=_count(p.get("comments")),
                posted_at=_time(p.get("created_time")),
                synced_at=now,
            )
            keep = ("caption", "media_url", "thumbnail_url", "media_type", "permalink")
            update_cols = {
                k: values[k] for k in (*keep, "like_count", "comments_count", "synced_at")
            }
            await session.execute(
                pg_insert(SocialPost)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["tenant_id", "platform", "post_id"], set_=update_cols
                )
            )
            n += 1
        return n

    @staticmethod
    async def list_posts(session, tenant_id, *, limit=25, before=None) -> list[SocialPost]:
        q = select(SocialPost).where(
            SocialPost.tenant_id == tenant_id, SocialPost.platform == PLATFORM
        )
        if before is not None:
            q = q.where(SocialPost.posted_at < before)
        rows = await session.execute(q.order_by(SocialPost.posted_at.desc()).limit(limit))
        return list(rows.scalars())

    @staticmethod
    async def get_post(session, tenant_id, post_id: str) -> SocialPost | None:
        row = await session.execute(
            select(SocialPost).where(
                SocialPost.tenant_id == tenant_id,
                SocialPost.platform == PLATFORM,
                SocialPost.post_id == post_id,
            )
        )
        return row.scalar_one_or_none()

    @staticmethod
    async def list_comments(session, tenant_id, post_id: str) -> list[SocialComment]:
        rows = await session.execute(
            select(SocialComment)
            .where(
                SocialComment.tenant_id == tenant_id,
                SocialComment.platform == PLATFORM,
                SocialComment.post_id == post_id,
                SocialComment.status != "removed",
            )
            .order_by(SocialComment.commented_at)
        )
        return list(rows.scalars())

    @staticmethod
    async def get_comment(session, tenant_id, comment_id: str) -> SocialComment:
        row = await session.execute(
            select(SocialComment).where(
                SocialComment.tenant_id == tenant_id,
                SocialComment.platform == PLATFORM,
                SocialComment.comment_id == comment_id,
            )
        )
        found = row.scalar_one_or_none()
        if found is None:
            raise NotFoundError("comment not found")
        return found

    @staticmethod
    async def sync_comments(session, tenant_id, credentials: dict, post_id: str) -> int:
        """Store every comment on the post, following Meta's pages to the end (up to a cap)."""
        n = 0

        async def _upsert(c: dict, parent: str | None) -> None:
            nonlocal n
            cid = str(c.get("id") or "")
            if not cid:
                return
            who = c.get("from") or {}
            await session.execute(
                pg_insert(SocialComment)
                .values(
                    tenant_id=tenant_id,
                    platform=PLATFORM,
                    comment_id=cid,
                    post_id=post_id,
                    parent_comment_id=parent or (c.get("parent") or {}).get("id"),
                    author_ref=str(who["id"]) if who.get("id") else None,
                    author_name=who.get("name"),
                    username=who.get("name"),
                    body=c.get("message"),
                    permalink=c.get("permalink_url"),
                    like_count=int(c.get("like_count") or 0),
                    commented_at=_time(c.get("created_time")),
                    status="hidden" if c.get("is_hidden") else "visible",
                )
                .on_conflict_do_update(
                    index_elements=["tenant_id", "platform", "comment_id"],
                    # status is NOT updated: a sync must not undo a moderation decision.
                    set_={"body": c.get("message"), "like_count": int(c.get("like_count") or 0)},
                )
            )
            n += 1

        async def _pages(object_id: str):
            """Meta's pages for one post or comment, until it says there is no next one."""
            after = None
            for _ in range(MAX_COMMENT_PAGES):
                page = await facebook_pages.list_comments(credentials, object_id, after=after)
                yield page["items"]
                after = page.get("next")
                if not after:
                    return

        async for items in _pages(post_id):
            for top in items:
                await _upsert(top, None)
                inline = top.get("comments") or {}
                for reply in inline.get("data") or []:
                    await _upsert(reply, str(top["id"]))
                # The inline list holds a comment's first replies only; Meta marks a longer one.
                if (inline.get("paging") or {}).get("next"):
                    async for more in _pages(str(top["id"])):
                        for reply in more:
                            await _upsert(reply, str(top["id"]))
        return n

    # ---- acting for the Page ----
    @staticmethod
    def check_picture(data: bytes) -> str:
        """Refuse what Facebook would refuse, before a single byte is stored. Returns the type."""
        if not data:
            raise ValidationError("the picture is empty")
        if len(data) > MAX_PICTURE_BYTES:
            raise ValidationError("the picture is larger than 4 MB")
        kind = picture_kind(data)
        if kind is None:
            raise ValidationError("Facebook accepts JPEG, PNG, GIF, BMP or WEBP pictures")
        return kind

    @staticmethod
    async def publish_picture(
        session, tenant_id, credentials: dict, *, picture: bytes, **kw
    ) -> str:
        """Publish a post whose picture is a file we hold, not a link someone else hosts.

        The picture waits in private storage only long enough for Facebook to fetch it (a short
        signed link), and is removed afterwards whatever happens.
        """
        kind = FacebookService.check_picture(picture)
        storage = get_storage()
        if not storage.configured:
            raise ConflictError("file storage is not set up, so a picture cannot be posted yet")
        stored = await storage.store(
            FetchedMedia(data=picture, content_type=kind, checksum=""),
            prefix=f"social-outbox/{tenant_id}",
        )
        if not stored.storage_key:
            raise ConflictError("the picture could not be stored for publishing")
        try:
            link = storage.signed_url(stored.storage_key, expires_in=PICTURE_LINK_SECONDS)
            return await FacebookService.publish(
                session, tenant_id, credentials, photo_url=link, **kw
            )
        finally:
            try:
                await storage.delete_objects([stored.storage_key])
            except Exception:  # noqa: BLE001 - a leftover temp file must not hide the result
                _logger.warning("facebook.publish.cleanup_failed")

    # ---- Reels and Stories ----
    @staticmethod
    async def _with_stored_file(tenant_id, data: bytes, content_type: str, fn) -> Any:
        """Hold a file in private storage just long enough for Facebook to fetch it.

        `fn` gets a short signed link. The file is removed afterwards, whatever happens.
        """
        storage = get_storage()
        if not storage.configured:
            raise ConflictError("file storage is not set up, so this cannot be posted yet")
        stored = await storage.store(
            FetchedMedia(data=data, content_type=content_type, checksum=""),
            prefix=f"social-outbox/{tenant_id}",
        )
        if not stored.storage_key:
            raise ConflictError("the file could not be stored for publishing")
        try:
            link = storage.signed_url(stored.storage_key, expires_in=VIDEO_LINK_SECONDS)
            return await fn(link)
        finally:
            try:
                await storage.delete_objects([stored.storage_key])
            except Exception:  # noqa: BLE001 - a leftover temp file must not hide the result
                _logger.warning("facebook.publish.cleanup_failed")

    @staticmethod
    async def _reel_budget(tenant_id: uuid.UUID, page_id: str) -> None:
        """Meta allows 30 Reels per Page in any 24 hours; refuse the 31st with the time to wait.

        Redis down must not stop a post: Meta enforces the same limit and says so itself.
        """
        from app.core.ratelimit import RateLimiter
        from app.core.redis import get_redis_or_none

        client = get_redis_or_none()
        if client is None:
            return
        try:
            result = await RateLimiter(
                client,
                limit=facebook_video.REELS_PER_DAY,
                window_seconds=24 * 3600,
                prefix="fb-reels",
            ).allow(f"{tenant_id}:{page_id}")
        except Exception:  # noqa: BLE001
            _logger.warning("facebook.reel_budget.unavailable")
            return
        if not result.allowed:
            hours = max(1, round(result.retry_after_seconds / 3600))
            raise ConflictError(
                f"Facebook allows {facebook_video.REELS_PER_DAY} Reels a day for a Page; "
                f"try again in about {hours} hour{'s' if hours != 1 else ''}"
            )

    @staticmethod
    async def publish_reel(session, tenant_id, credentials: dict, *, video: bytes, **kw) -> str:
        try:
            facebook_video.check_reel(video)
        except facebook_video.FacebookVideoError as exc:
            raise ValidationError(str(exc), details={"reason": exc.code}) from exc
        await FacebookService._reel_budget(tenant_id, str(credentials.get("account_id")))

        async def _go(link: str) -> str:
            try:
                return await facebook_pages.publish_reel(credentials, video_url=link, **kw)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

        return await FacebookService._with_stored_file(tenant_id, video, "video/mp4", _go)

    @staticmethod
    async def publish_story(
        session,
        tenant_id,
        credentials: dict,
        *,
        video: bytes | None = None,
        photo: bytes | None = None,
    ) -> str:
        if (video is None) == (photo is None):
            raise ValidationError("a Story is one video or one picture")
        try:
            if video is not None:
                facebook_video.check_video_story(video)
            else:
                photo_type = facebook_video.check_story_photo(photo)
        except facebook_video.FacebookVideoError as exc:
            raise ValidationError(str(exc), details={"reason": exc.code}) from exc
        if video is not None:
            return await FacebookService._with_stored_file(
                tenant_id,
                video,
                "video/mp4",
                lambda link: facebook_pages.publish_video_story(credentials, video_url=link),
            )
        return await FacebookService._with_stored_file(
            tenant_id,
            photo,
            photo_type,
            lambda link: facebook_pages.publish_photo_story(credentials, photo_url=link),
        )

    @staticmethod
    async def publish(session, tenant_id, credentials: dict, **kw) -> str:
        try:
            post_id = await facebook_pages.publish_post(credentials, **kw)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        try:
            await FacebookService.sync_posts(session, tenant_id, credentials, limit=5)
        except Exception:  # noqa: BLE001 - it is live on Facebook even if the refresh failed
            pass
        return post_id

    @staticmethod
    async def edit(session, tenant_id, credentials: dict, post_id: str, message: str) -> SocialPost:
        post = await FacebookService.get_post(session, tenant_id, post_id)
        if post is None:
            raise NotFoundError("post not found")
        try:
            await facebook_pages.update_post(credentials, post_id, message)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        post.caption = message.strip()
        await session.flush()
        return post

    @staticmethod
    async def remove_post(session, tenant_id, credentials: dict, post_id: str) -> None:
        post = await FacebookService.get_post(session, tenant_id, post_id)
        if post is None:
            raise NotFoundError("post not found")
        await facebook_pages.delete_post(credentials, post_id)
        await session.delete(post)
        await session.flush()

    @staticmethod
    def resolve_mentions(thread, wanted: list[str] | None) -> list[str]:
        """The ids to tag, kept only if each wrote on this thread as someone other than the Page.

        Meta lets a Page mention a person only when that person commented on, or created, the post
        (Pages API: Comments and @mentions). Tagging anyone else is refused by Meta, so it is
        refused here first, with a reason the owner can read.
        """
        if not wanted:
            return []
        ids = list(dict.fromkeys(str(w).strip() for w in wanted))
        if len(ids) > MAX_MENTIONS:
            raise ValidationError(f"you can tag at most {MAX_MENTIONS} people in one reply")
        allowed = {c.author_ref for c in thread if c.author_ref and not c.is_page_reply}
        stray = [i for i in ids if i not in allowed]
        if stray:
            raise ValidationError("you can only tag people who commented on this post")
        return ids

    @staticmethod
    async def reply(
        session,
        tenant_id,
        credentials: dict,
        object_id: str,
        text: str,
        *,
        user_id=None,
        mention: list[str] | None = None,
    ):
        """Comment on a post, or reply to a comment (Facebook threads are one level deep)."""
        post = await FacebookService.get_post(session, tenant_id, object_id)
        target = None
        if post is None:
            target = await FacebookService.get_comment(session, tenant_id, object_id)
            if target.status == "hidden":
                raise ConflictError("this comment is hidden; unhide it before replying")
            post_id, root = target.post_id, target.parent_comment_id or target.comment_id
        else:
            post_id, root = post.post_id, post.post_id
        tags: list[str] = []
        if mention:
            thread = (
                (
                    await session.execute(
                        select(SocialComment).where(
                            SocialComment.tenant_id == tenant_id,
                            SocialComment.platform == PLATFORM,
                            SocialComment.post_id == post_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            tags = FacebookService.resolve_mentions(thread, mention)
        try:
            new_id = await facebook_pages.comment(credentials, root, text, mention=tags or None)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        now = datetime.now(UTC)
        row = SocialComment(
            tenant_id=tenant_id,
            platform=PLATFORM,
            comment_id=new_id,
            post_id=post_id,
            parent_comment_id=root if target is not None else None,
            author_name="page",
            body=text.strip(),
            commented_at=now,
            status="visible",
            is_page_reply=True,
            moderated_by=user_id,
        )
        session.add(row)
        if target is not None:
            await session.execute(
                update(SocialComment)
                .where(
                    SocialComment.tenant_id == tenant_id,
                    SocialComment.platform == PLATFORM,
                    SocialComment.comment_id.in_([target.comment_id, root]),
                )
                .values(replied_at=now)
            )
        await session.flush()
        return row

    @staticmethod
    async def set_hidden(
        session, tenant_id, credentials: dict, comment_id: str, hidden: bool, *, user_id=None
    ):
        row = await FacebookService.get_comment(session, tenant_id, comment_id)
        await facebook_pages.set_comment_hidden(credentials, comment_id, hidden)
        row.status = "hidden" if hidden else "visible"
        row.hidden_at = datetime.now(UTC) if hidden else None
        row.moderated_by = user_id
        await session.flush()
        return row

    @staticmethod
    async def remove_comment(
        session, tenant_id, credentials: dict, comment_id: str, *, user_id=None
    ) -> None:
        row = await FacebookService.get_comment(session, tenant_id, comment_id)
        await facebook_pages.delete_comment(credentials, comment_id)
        row.status = "removed"
        row.moderated_by = user_id
        await session.flush()

    @staticmethod
    async def private_reply(
        session, tenant_id, credentials: dict, comment_id: str, text: str, *, user_id=None
    ) -> str:
        row = await FacebookService.get_comment(session, tenant_id, comment_id)
        try:
            message_id = await facebook_pages.private_reply(credentials, comment_id, text)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        row.private_replied_at = datetime.now(UTC)
        row.moderated_by = user_id
        await session.flush()
        return message_id
