"""The Page's own feed: what happened to OUR posts, applied to the local record.

The `feed` webhook carries more than comments. A post is edited, shared, hidden, published or
reacted to, and until now every one of those changes was parsed away: `parse_meta_comment_changes`
returns nothing for anything that is not a comment, so FIHRIST kept showing the post as it was the
day it was published. This processor is the other half — it classifies each change and applies the
ones we can hold honestly, and it LOGS the ones we cannot instead of dropping them in silence.

Only facts the event actually carries are written. A `reaction` event does not say the new total,
so no total is invented; the counter is incremented only for `add` and decremented only for
`remove`, which is what Meta tells us.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversations.models import SocialPost

logger = logging.getLogger(__name__)

#: Feed items that are the Page's own content (as opposed to a comment or a reaction).
_POST_ITEMS = frozenset({"post", "status", "photo", "video", "share", "link", "reel"})
_REACTION_ITEMS = frozenset({"reaction", "like"})


def _epoch(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (TypeError, ValueError):
        return None


class PageEventProcessor:
    """Classify Page feed changes and apply the ones FIHRIST can hold honestly."""

    @staticmethod
    def classify(changes: list[dict]) -> dict[str, int]:
        """Count the changes by kind, so the caller can log a real summary per delivery."""
        counts: dict[str, int] = {}
        for change in changes:
            value = change.get("value") or {}
            item = str(value.get("item") or "").lower()
            if change.get("field") == "mention" or change.get("field") == "mentions":
                kind = "mention"
            elif item == "comment":
                kind = "comment"
            elif item in _REACTION_ITEMS:
                kind = "reaction"
            elif item in _POST_ITEMS:
                kind = "post"
            else:
                kind = "unsupported"
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    @staticmethod
    async def apply(
        session: AsyncSession, tenant_id: uuid.UUID, platform: str, changes: list[dict]
    ) -> dict[str, int]:
        """Apply post edits and reactions; report everything, apply only what is knowable.

        A change for a post we do not hold is counted as ``unknown_post`` and logged: the Page may
        have been connected after that post was written, and inventing a row with no caption,
        media or date would put a fake post in the merchant's list.
        """
        result = {"updated": 0, "reactions": 0, "unknown_post": 0, "ignored": 0}
        for change in changes:
            value = change.get("value") or {}
            item = str(value.get("item") or "").lower()
            post_id = str(value.get("post_id") or "").strip()

            if item in _REACTION_ITEMS:
                if not post_id:
                    result["ignored"] += 1
                    continue
                post = await PageEventProcessor._find_post(session, tenant_id, platform, post_id)
                if post is None:
                    result["unknown_post"] += 1
                    continue
                verb = str(value.get("verb") or "add").lower()
                if verb == "add":
                    post.like_count = (post.like_count or 0) + 1
                elif verb == "remove":
                    post.like_count = max((post.like_count or 0) - 1, 0)
                else:
                    result["ignored"] += 1
                    continue
                result["reactions"] += 1
                continue

            if item not in _POST_ITEMS or not post_id:
                result["ignored"] += 1
                continue

            post = await PageEventProcessor._find_post(session, tenant_id, platform, post_id)
            if post is None:
                result["unknown_post"] += 1
                continue

            verb = str(value.get("verb") or "add").lower()
            if verb == "remove":
                # Meta does not tell us whether it was deleted or hidden; marking it unpublished
                # is the honest middle: it is no longer visible, and the post row stays for the
                # comments that reference it.
                post.publish_status = "removed"
                result["updated"] += 1
                continue
            message = value.get("message")
            if isinstance(message, str) and message != post.caption:
                post.caption = message
                result["updated"] += 1
                continue
            posted_at = _epoch(value.get("created_time"))
            if posted_at is not None and posted_at != post.posted_at:
                post.posted_at = posted_at
                result["updated"] += 1
                continue
            result["ignored"] += 1

        if result["unknown_post"]:
            logger.info(
                "facebook.feed_unknown_post",
                extra={"tenant_id": str(tenant_id), "platform": platform,
                       "count": result["unknown_post"]},
            )
        return result

    @staticmethod
    async def _find_post(
        session: AsyncSession, tenant_id: uuid.UUID, platform: str, post_id: str
    ) -> SocialPost | None:
        return (
            await session.execute(
                select(SocialPost).where(
                    SocialPost.tenant_id == tenant_id,
                    SocialPost.platform == platform,
                    SocialPost.post_id == post_id,
                )
            )
        ).scalar_one_or_none()
