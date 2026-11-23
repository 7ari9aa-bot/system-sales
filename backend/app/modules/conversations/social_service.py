"""The store's own posts and comments: sync, reply, moderate, answer in private.

The merchant works from the inbox instead of the Instagram app. Every action
calls the platform FIRST and writes our row only once the platform accepted it,
so the inbox never claims a reply, a hide or a delete that did not happen.

The rules that come from the platform, not from us:
  * a private reply is ONE message per comment, within 7 days of the comment;
  * a deleted comment is gone for good;
  * a commenter is an id and a username only (no photo, no follower data).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.storage import FetchedMedia, get_storage
from app.modules.conversations.gateway.instagram import instagram_adapter
from app.modules.conversations.models import SocialComment, SocialPost

PRIVATE_REPLY_WINDOW = timedelta(days=7)
MAX_REPLY_CHARS = 2200  # Instagram's comment length limit
PLATFORM = "instagram"
logger = logging.getLogger(__name__)
MAX_PICTURE_BYTES = 8 * 1024 * 1024  # Instagram's own limit for a picture
PICTURE_LINK_SECONDS = 15 * 60  # Instagram fetches each picture once, right away
_JPEG_START = b"\xff\xd8\xff"
#: A Reel is a video file Instagram has to accept. MP4/MOV both carry an `ftyp` box right after
#: the 4-byte size, which is the only thing we can check without decoding the video.
MAX_VIDEO_BYTES = 100 * 1024 * 1024
_FTYP_AT = 4


def _parse_time(value: Any) -> datetime:
    """Graph timestamps look like 2026-11-17T10:00:00+0000 (no colon in the offset)."""
    if isinstance(value, str) and value:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                return datetime.strptime(value, fmt).astimezone(UTC)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _clean_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise ValidationError("the reply is empty")
    if len(text) > MAX_REPLY_CHARS:
        raise ValidationError(f"the reply is longer than {MAX_REPLY_CHARS} characters")
    return text


class SocialService:
    # ---------- publishing ----------

    @staticmethod
    def check_pictures(pictures: list[bytes]) -> None:
        """Refuse what Instagram would refuse, before a single byte is stored.

        Instagram publishes JPEG only. The type is read from the file's own first
        bytes, never from the name or the header the browser sent.
        """
        if not pictures:
            raise ValidationError("add at least one picture")
        if len(pictures) > instagram_adapter.CAROUSEL_MAX:
            raise ValidationError(f"a post holds at most {instagram_adapter.CAROUSEL_MAX} pictures")
        for i, data in enumerate(pictures, start=1):
            if not data.startswith(_JPEG_START):
                raise ValidationError(f"picture {i} is not a JPEG; Instagram accepts JPEG only")
            if len(data) > MAX_PICTURE_BYTES:
                raise ValidationError(f"picture {i} is larger than 8 MB")

    @staticmethod
    async def publish_post(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        credentials: dict,
        pictures: list[bytes],
        caption: str | None,
    ) -> str:
        """Publish a photo or a carousel, then pull it into our list. Returns the media id.

        The pictures wait in private storage only long enough for Instagram to fetch
        them (a short-lived link), and are removed afterwards whatever happens.
        """
        SocialService.check_pictures(pictures)
        caption = (caption or "").strip() or None
        if caption and len(caption) > 2200:
            raise ValidationError("a caption is at most 2,200 characters")
        storage = get_storage()
        if not storage.configured:
            raise ConflictError("file storage is not set up, so a post cannot be published yet")
        keys: list[str] = []
        try:
            links: list[str] = []
            for data in pictures:
                stored = await storage.store(
                    FetchedMedia(data=data, content_type="image/jpeg", checksum=""),
                    prefix=f"social-outbox/{tenant_id}",
                )
                if not stored.storage_key:
                    raise ConflictError("a picture could not be stored for publishing")
                keys.append(stored.storage_key)
                links.append(
                    storage.signed_url(stored.storage_key, expires_in=PICTURE_LINK_SECONDS)
                )
            media_id = await instagram_adapter.publish_post(credentials, links, caption)
        except ValueError as exc:  # the adapter's own early refusals
            raise ValidationError(str(exc)) from exc
        finally:
            if keys:
                try:
                    await storage.delete_objects(keys)
                except Exception:  # noqa: BLE001 - a leftover temp file must not hide the result
                    logger.warning("social.publish.cleanup_failed", extra={"count": len(keys)})
        # Show it right away; if the refresh hiccups the post is still live on Instagram.
        try:
            await SocialService.sync_posts(session, tenant_id, credentials, limit=5)
        except Exception:  # noqa: BLE001
            logger.warning("social.publish.sync_failed")
        return media_id

    @staticmethod
    def check_video(video: bytes) -> None:
        """Refuse a file Instagram would refuse, before storing a byte of it."""
        if not video:
            raise ValidationError("add a video")
        if len(video) > MAX_VIDEO_BYTES:
            raise ValidationError("the video is larger than 100 MB")
        if video[_FTYP_AT : _FTYP_AT + 4] != b"ftyp":
            raise ValidationError("the video is not an MP4/MOV file; Instagram accepts those only")

    @staticmethod
    async def _publish_media(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        credentials: dict,
        data: bytes,
        content_type: str,
        call,
    ) -> str:
        """Store one file just long enough for Instagram to fetch it, then publish.

        The link is short-lived and the object is removed whatever happens: a leftover temp file
        must never outlive the request.
        """
        storage = get_storage()
        if not storage.configured:
            raise ConflictError("file storage is not set up, so a post cannot be published yet")
        stored = await storage.store(
            FetchedMedia(data=data, content_type=content_type, checksum=""),
            prefix=f"social-outbox/{tenant_id}",
        )
        if not stored.storage_key:
            raise ConflictError("the file could not be stored for publishing")
        try:
            link = storage.signed_url(stored.storage_key, expires_in=PICTURE_LINK_SECONDS)
            media_id = await call(link)
        except ValueError as exc:  # the adapter's own early refusals
            raise ValidationError(str(exc)) from exc
        finally:
            try:
                await storage.delete_objects([stored.storage_key])
            except Exception:  # noqa: BLE001 - a leftover temp file must not hide the result
                logger.warning("social.publish.cleanup_failed", extra={"count": 1})
        try:
            await SocialService.sync_posts(session, tenant_id, credentials, limit=5)
        except Exception:  # noqa: BLE001
            logger.warning("social.publish.sync_failed")
        return media_id

    @staticmethod
    async def publish_reel(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        credentials: dict,
        video: bytes,
        caption: str | None,
        *,
        share_to_feed: bool = True,
        cover: bytes | None = None,
    ) -> str:
        """Publish a Reel. Returns the media id Instagram assigned."""
        SocialService.check_video(video)
        caption = (caption or "").strip() or None
        if caption and len(caption) > 2200:
            raise ValidationError("a caption is at most 2,200 characters")
        cover_url: str | None = None
        storage = get_storage()
        if cover is not None:
            SocialService.check_pictures([cover])
            if not storage.configured:
                raise ConflictError("file storage is not set up, so a post cannot be published yet")
            stored = await storage.store(
                FetchedMedia(data=cover, content_type="image/jpeg", checksum=""),
                prefix=f"social-outbox/{tenant_id}",
            )
            if not stored.storage_key:
                raise ConflictError("the cover could not be stored for publishing")
            cover_url = storage.signed_url(stored.storage_key, expires_in=PICTURE_LINK_SECONDS)
            try:
                return await SocialService._publish_media(
                    session,
                    tenant_id,
                    credentials,
                    video,
                    "video/mp4",
                    lambda link: instagram_adapter.publish_reel(
                        credentials, link, caption, share_to_feed=share_to_feed, cover_url=cover_url
                    ),
                )
            finally:
                try:
                    await storage.delete_objects([stored.storage_key])
                except Exception:  # noqa: BLE001
                    logger.warning("social.publish.cleanup_failed", extra={"count": 1})
        return await SocialService._publish_media(
            session,
            tenant_id,
            credentials,
            video,
            "video/mp4",
            lambda link: instagram_adapter.publish_reel(
                credentials, link, caption, share_to_feed=share_to_feed
            ),
        )

    @staticmethod
    async def publish_story(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        credentials: dict,
        media: bytes,
        *,
        is_video: bool,
    ) -> str:
        """Publish one story (picture or video). A story carries no caption on Instagram."""
        if is_video:
            SocialService.check_video(media)
            content_type = "video/mp4"
        else:
            SocialService.check_pictures([media])
            content_type = "image/jpeg"
        return await SocialService._publish_media(
            session,
            tenant_id,
            credentials,
            media,
            content_type,
            lambda link: instagram_adapter.publish_story(credentials, link, is_video=is_video),
        )

    @staticmethod
    async def list_stories(credentials: dict) -> list[dict]:
        """The stories running right now, with whatever numbers Meta has already delivered.

        The stored metrics come from the story_insights webhook; a story that is still live has
        none yet, and Meta answers -1 for a count under five. Both are passed through untouched so
        the screen can tell "not yet" from "fewer than five" from a real number.
        """
        items = await instagram_adapter.list_stories(credentials)
        return [
            {
                "id": str(item.get("id") or ""),
                "media_type": item.get("media_type"),
                "media_url": item.get("media_url"),
                "thumbnail_url": item.get("thumbnail_url"),
                "permalink": item.get("permalink"),
                "posted_at": item.get("timestamp"),
            }
            for item in items
            if item.get("id")
        ]

    # ---------- reading ----------

    @staticmethod
    async def list_posts(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        limit: int = 25,
        before: datetime | None = None,
    ) -> list[SocialPost]:
        stmt = select(SocialPost).where(
            SocialPost.tenant_id == tenant_id, SocialPost.platform == PLATFORM
        )
        if before is not None:
            stmt = stmt.where(SocialPost.posted_at < before)
        rows = await session.execute(stmt.order_by(SocialPost.posted_at.desc()).limit(limit))
        return list(rows.scalars().all())

    @staticmethod
    async def list_comments(
        session: AsyncSession, tenant_id: uuid.UUID, post_id: str, *, include_hidden: bool = True
    ) -> list[SocialComment]:
        """Oldest first, so a thread reads top to bottom. Removed comments are never shown."""
        statuses = ("visible", "hidden") if include_hidden else ("visible",)
        rows = await session.execute(
            select(SocialComment)
            .where(
                SocialComment.tenant_id == tenant_id,
                SocialComment.platform == PLATFORM,
                SocialComment.post_id == post_id,
                SocialComment.status.in_(statuses),
            )
            .order_by(SocialComment.commented_at.asc())
        )
        return list(rows.scalars().all())

    @staticmethod
    async def get_post(
        session: AsyncSession, tenant_id: uuid.UUID, post_id: str
    ) -> SocialPost | None:
        """One of this shop's posts by its Instagram media id (never another shop's)."""
        return (
            await session.execute(
                select(SocialPost).where(
                    SocialPost.tenant_id == tenant_id,
                    SocialPost.platform == PLATFORM,
                    SocialPost.post_id == post_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get_comment(
        session: AsyncSession, tenant_id: uuid.UUID, comment_id: str
    ) -> SocialComment:
        row = (
            await session.execute(
                select(SocialComment).where(
                    SocialComment.tenant_id == tenant_id,
                    SocialComment.platform == PLATFORM,
                    SocialComment.comment_id == comment_id,
                )
            )
        ).scalar_one_or_none()
        if row is None or row.status == "removed":
            raise NotFoundError("comment not found")
        return row

    # ---------- syncing from the platform ----------

    @staticmethod
    async def sync_posts(
        session: AsyncSession, tenant_id: uuid.UUID, credentials: dict, *, limit: int = 25
    ) -> int:
        """Pull the latest posts and keep ours in step. Returns how many were upserted."""
        page = await instagram_adapter.list_media(credentials, limit=limit)
        now = datetime.now(UTC)
        n = 0
        for m in page["items"]:
            pid = str(m.get("id") or "")
            if not pid:
                continue
            mtype = str(
                m.get("media_product_type") == "REELS" and "REELS" or m.get("media_type") or ""
            )
            values = dict(
                tenant_id=tenant_id,
                platform=PLATFORM,
                post_id=pid,
                caption=m.get("caption"),
                media_url=m.get("media_url"),
                thumbnail_url=m.get("thumbnail_url"),
                media_type=mtype or None,
                permalink=m.get("permalink"),
                like_count=int(m.get("like_count") or 0),
                comments_count=int(m.get("comments_count") or 0),
                posted_at=_parse_time(m.get("timestamp")),
                synced_at=now,
            )
            update_cols = {
                k: values[k]
                for k in (
                    "caption",
                    "media_url",
                    "thumbnail_url",
                    "media_type",
                    "permalink",
                    "like_count",
                    "comments_count",
                    "synced_at",
                )
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
    async def sync_comments(
        session: AsyncSession, tenant_id: uuid.UUID, credentials: dict, post_id: str
    ) -> int:
        """Pull a post's comments and replies. Never changes a status we set ourselves."""
        page = await instagram_adapter.list_comments(credentials, post_id)
        n = 0

        async def _upsert(c: dict, parent: str | None) -> None:
            nonlocal n
            cid = str(c.get("id") or "")
            if not cid:
                return
            author = (c.get("from") or {}).get("id")
            name = c.get("username") or (c.get("from") or {}).get("username")
            await session.execute(
                pg_insert(SocialComment)
                .values(
                    tenant_id=tenant_id,
                    platform=PLATFORM,
                    comment_id=cid,
                    post_id=post_id,
                    parent_comment_id=parent or c.get("parent_id"),
                    author_ref=str(author) if author else None,
                    author_name=name,
                    username=name,
                    body=c.get("text"),
                    like_count=int(c.get("like_count") or 0),
                    commented_at=_parse_time(c.get("timestamp")),
                    status="hidden" if c.get("hidden") else "visible",
                )
                .on_conflict_do_update(
                    index_elements=["tenant_id", "platform", "comment_id"],
                    # status is deliberately NOT here: a sync must not undo a moderation
                    # decision, and a webhook "remove" must not be resurrected by a stale page.
                    set_={"body": c.get("text"), "like_count": int(c.get("like_count") or 0)},
                )
            )
            n += 1

        for top in page["items"]:
            await _upsert(top, None)
            for reply in (top.get("replies") or {}).get("data") or []:
                await _upsert(reply, str(top["id"]))
        return n

    # ---------- acting on a comment ----------

    @staticmethod
    async def reply_publicly(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        credentials: dict,
        comment_id: str,
        text: str,
        *,
        user_id: uuid.UUID | None = None,
    ) -> SocialComment:
        text = _clean_text(text)
        target = await SocialService.get_comment(session, tenant_id, comment_id)
        if target.status == "hidden":
            raise ConflictError("this comment is hidden; unhide it before replying")
        # Replies attach to the top-level comment: Instagram threads are one level deep.
        thread_root = target.parent_comment_id or target.comment_id
        new_id = await instagram_adapter.reply_to_comment(credentials, thread_root, text)
        if not new_id:
            raise ConflictError("the platform accepted the reply but returned no id")
        now = datetime.now(UTC)
        reply = SocialComment(
            tenant_id=tenant_id,
            platform=PLATFORM,
            comment_id=new_id,
            post_id=target.post_id,
            parent_comment_id=thread_root,
            author_name="page",
            body=text,
            commented_at=now,
            status="visible",
            is_page_reply=True,
            moderated_by=user_id,
        )
        session.add(reply)
        await session.execute(
            update(SocialComment)
            .where(
                SocialComment.tenant_id == tenant_id,
                SocialComment.platform == PLATFORM,
                SocialComment.comment_id.in_([target.comment_id, thread_root]),
            )
            .values(replied_at=now)
        )
        await session.flush()
        return reply

    @staticmethod
    async def set_hidden(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        credentials: dict,
        comment_id: str,
        hidden: bool,
        *,
        user_id: uuid.UUID | None = None,
    ) -> SocialComment:
        row = await SocialService.get_comment(session, tenant_id, comment_id)
        await instagram_adapter.set_comment_hidden(credentials, comment_id, hidden)
        row.status = "hidden" if hidden else "visible"
        row.hidden_at = datetime.now(UTC) if hidden else None
        row.moderated_by = user_id
        await session.flush()
        return row

    @staticmethod
    async def delete(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        credentials: dict,
        comment_id: str,
        *,
        user_id: uuid.UUID | None = None,
    ) -> None:
        row = await SocialService.get_comment(session, tenant_id, comment_id)
        await instagram_adapter.delete_comment(credentials, comment_id)
        row.status = "removed"
        row.moderated_by = user_id
        await session.flush()

    @staticmethod
    async def send_private_reply(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        credentials: dict,
        comment_id: str,
        text: str,
        *,
        user_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> str:
        """DM the commenter. Returns the provider message id (their chat starts here)."""
        text = _clean_text(text)
        row = await SocialService.get_comment(session, tenant_id, comment_id)
        if row.is_page_reply:
            raise ValidationError("cannot send a private reply to our own reply")
        if row.private_replied_at is not None:
            raise ConflictError("this comment already got its one private reply")
        current = now or datetime.now(UTC)
        if current - row.commented_at > PRIVATE_REPLY_WINDOW:
            raise ConflictError("a private reply must be sent within 7 days of the comment")
        message_id = await instagram_adapter.send_private_reply(credentials, comment_id, text)
        row.private_replied_at = current
        row.moderated_by = user_id
        await session.flush()
        return message_id

    @staticmethod
    async def set_comments_enabled(
        session: AsyncSession, tenant_id: uuid.UUID, credentials: dict, post_id: str, enabled: bool
    ) -> None:
        post = (
            await session.execute(
                select(SocialPost).where(
                    SocialPost.tenant_id == tenant_id,
                    SocialPost.platform == PLATFORM,
                    SocialPost.post_id == post_id,
                )
            )
        ).scalar_one_or_none()
        if post is None:
            raise NotFoundError("post not found")
        await instagram_adapter.set_comments_enabled(credentials, post_id, enabled)
        post.comments_enabled = enabled
        await session.flush()
