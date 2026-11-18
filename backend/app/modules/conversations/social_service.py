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

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.conversations.gateway.instagram import instagram_adapter
from app.modules.conversations.models import SocialComment, SocialPost

PRIVATE_REPLY_WINDOW = timedelta(days=7)
MAX_REPLY_CHARS = 2200  # Instagram's comment length limit
PLATFORM = "instagram"


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
