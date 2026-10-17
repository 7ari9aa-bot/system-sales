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

from app.modules.conversations.gateway.base import InboundComment
from app.modules.conversations.models import SocialComment


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
            return await SocialCommentService._mark_removed(
                session, tenant_id, platform, comment.platform_comment_id, commented_at
            )
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
        return (await session.execute(stmt)).scalar_one()

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
