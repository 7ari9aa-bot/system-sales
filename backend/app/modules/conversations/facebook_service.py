"""The Facebook Page's own posts and comments: pulled from Meta, changed through Meta.

Same tables as Instagram (`social_posts`, `social_comments`, platform="facebook"), so no
migration. The platform is called FIRST and our row changes only after it accepted, so the
screen never shows something that did not happen. A sync never overwrites a moderation
status we set ourselves.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.conversations.gateway.facebook_pages import facebook_pages
from app.modules.conversations.models import SocialComment, SocialPost

PLATFORM = "facebook"


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
        page = await facebook_pages.list_comments(credentials, post_id)
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

        for top in page["items"]:
            await _upsert(top, None)
            for reply in (top.get("comments") or {}).get("data") or []:
                await _upsert(reply, str(top["id"]))
        return n

    # ---- acting for the Page ----
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
    async def reply(
        session, tenant_id, credentials: dict, object_id: str, text: str, *, user_id=None
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
        try:
            new_id = await facebook_pages.comment(credentials, root, text)
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
