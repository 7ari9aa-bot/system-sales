"""Public social comments — durable ingest (facebook/instagram).

Comments arrive on the SAME signed webhook envelope as messages, but they are
interaction data, not conversation turns: they never page anyone, never open a
conversation, and never trigger an AI reply. The ingest is idempotent by
(tenant, platform, comment_id) — a redelivered "add" updates the mutable
fields instead of duplicating, and the platform's own verbs are the only
writers of a comment's visibility (merchant moderation comes later, through
a surface that does not exist yet).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.writer import add_outbox_event
from app.applications.apparel.modules.conversations.gateway.base import InboundComment
from app.applications.apparel.modules.conversations.models import SocialComment


def comment_changed_payload(
    *,
    platform: str,
    post_id: str | None,
    comment_id: str,
    parent_comment_id: str | None,
    verb: str,
) -> dict | None:
    """What an open screen needs to refetch, and nothing more.

    Ids only: the comment text stays in the database and reaches the screen through the
    ordinary authenticated read, so a stream frame is never a second copy of customer text.
    No post means no screen to wake (a screen refetches by post), so nothing is announced.
    """
    if not post_id:
        return None
    return {
        "platform": platform,
        "post_id": post_id,
        "comment_id": comment_id,
        "parent_comment_id": parent_comment_id,
        "verb": verb,
    }


async def announce_comment_changed(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    row_id: uuid.UUID,
    *,
    platform: str,
    post_id: str | None,
    comment_id: str,
    parent_comment_id: str | None,
    verb: str,
) -> bool:
    """Stage the announcement in the caller's transaction (it commits with the comment)."""
    payload = comment_changed_payload(
        platform=platform,
        post_id=post_id,
        comment_id=comment_id,
        parent_comment_id=parent_comment_id,
        verb=verb,
    )
    if payload is None:
        return False
    await add_outbox_event(
        session,
        aggregate_type="social_comment",
        aggregate_id=row_id,
        event_type="social_comment.changed",
        tenant_id=tenant_id,
        payload=payload,
        producer="social_comments",
    )
    return True


class SocialCommentService:
    @staticmethod
    async def ingest(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        platform: str,
        comment: InboundComment,
    ) -> uuid.UUID:
        """Persist one comment idempotently; returns the row id.

        An ``add``/``edited`` redelivery updates body, like count and author
        but NEVER touches status: once the merchant hides a comment, a lazy
        provider replay must not un-hide it. A ``remove`` marks the row
        removed — and, when it lands before the row exists (out-of-order
        delivery), writes the tombstone itself so the dedupe key stays
        honest either way.
        """
        commented_at = comment.commented_at or datetime.now(UTC)
        if comment.verb == "remove":
            removed_id = await SocialCommentService._mark_removed(
                session, tenant_id, platform, comment.platform_comment_id, commented_at
            )
            await announce_comment_changed(
                session,
                tenant_id,
                removed_id,
                platform=platform,
                post_id=comment.post_id or await SocialCommentService._post_of(session, removed_id),
                comment_id=comment.platform_comment_id,
                parent_comment_id=comment.parent_comment_id,
                verb="remove",
            )
            return removed_id
        stmt = (
            pg_insert(SocialComment)
            .values(
                tenant_id=tenant_id,
                platform=platform,
                comment_id=comment.platform_comment_id,
                post_id=comment.post_id,
                parent_comment_id=comment.parent_comment_id,
                author_ref=comment.author_ref,
                author_name=comment.author_name,
                body=comment.body,
                permalink=comment.permalink,
                like_count=comment.like_count,
                commented_at=commented_at,
                status="visible",
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "platform", "comment_id"],
                set_={
                    "body": comment.body,
                    "like_count": comment.like_count,
                    "author_name": comment.author_name,
                    "permalink": comment.permalink,
                },
            )
            .returning(SocialComment.id)
        )
        row_id = (await session.execute(stmt)).scalar_one()
        await announce_comment_changed(
            session,
            tenant_id,
            row_id,
            platform=platform,
            post_id=comment.post_id,
            comment_id=comment.platform_comment_id,
            parent_comment_id=comment.parent_comment_id,
            verb=comment.verb,
        )
        return row_id

    @staticmethod
    async def _post_of(session: AsyncSession, row_id: uuid.UUID) -> str | None:
        """The post a stored comment belongs to (a remove event often omits it)."""
        return (
            await session.execute(select(SocialComment.post_id).where(SocialComment.id == row_id))
        ).scalar_one_or_none()

    @staticmethod
    async def _mark_removed(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        platform: str,
        comment_id: str,
        commented_at: datetime,
    ) -> uuid.UUID:
        existing = (
            await session.execute(
                select(SocialComment.id).where(
                    SocialComment.tenant_id == tenant_id,
                    SocialComment.platform == platform,
                    SocialComment.comment_id == comment_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            await session.execute(
                update(SocialComment)
                .where(
                    SocialComment.tenant_id == tenant_id,
                    SocialComment.platform == platform,
                    SocialComment.comment_id == comment_id,
                    SocialComment.status != "removed",
                )
                .values(status="removed")
            )
            return existing
        # A remove for a comment we never saw: write the tombstone, or the
        # dedupe key lies and a later redelivered add resurrects a deleted
        # comment as fresh.
        row = SocialComment(
            tenant_id=tenant_id,
            platform=platform,
            comment_id=comment_id,
            body=None,
            commented_at=commented_at,
            status="removed",
        )
        session.add(row)
        await session.flush()
        return row.id
