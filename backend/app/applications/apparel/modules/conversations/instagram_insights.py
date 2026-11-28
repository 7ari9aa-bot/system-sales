"""A story's metrics, applied to the story we already hold.

Instagram delivers ``story_insights`` after a story expires: impressions, reach, taps forward and
back, exits, replies. The field was parsed by nothing, so every number was dropped and the merchant
had no story performance at all.

Two rules this module keeps:

* **-1 means "fewer than five".** Meta sends -1 when a count is below five rather than a small
  number, and that is not an error. The value is stored as sent; the screen decides how to say it.
* **A story we never saw is not invented, but a story Meta names is recorded.** A story lives 24
  hours and its numbers arrive after that, so the row is usually gone. The delivery itself states
  the media id, so a minimal story row is created from it (no caption, no counts, no guessed date)
  instead of throwing the metrics away.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.apparel.modules.conversations.models import SocialPost

logger = logging.getLogger(__name__)

#: Meta's "fewer than five" sentinel. Named so no caller writes `== -1` from memory.
BELOW_THRESHOLD = -1


def is_below_threshold(value: object) -> bool:
    """True when Meta refused to give the real count because it is under five."""
    return value == BELOW_THRESHOLD


class StoryInsightsService:
    @staticmethod
    async def apply(
        session: AsyncSession, tenant_id: uuid.UUID, platform: str, deliveries: list[dict]
    ) -> dict[str, int]:
        """Store each delivery's metrics on its story; report what could not be placed."""
        result = {"updated": 0, "created": 0, "ignored": 0}
        for delivery in deliveries:
            media_id = str(delivery.get("media_id") or "").strip()
            metrics = delivery.get("metrics")
            if not media_id or not isinstance(metrics, dict) or not metrics:
                result["ignored"] += 1
                continue
            post = (
                await session.execute(
                    select(SocialPost).where(
                        SocialPost.tenant_id == tenant_id,
                        SocialPost.platform == platform,
                        SocialPost.post_id == media_id,
                    )
                )
            ).scalar_one_or_none()
            if post is None:
                # A story expires after 24 hours, and its numbers arrive after that, so the row is
                # usually gone by the time the metrics land. Meta has just told us the media id, so
                # the row is created from what the delivery states: a story, with its metrics. No
                # caption, no like count, and no guessed date are invented for it.
                post = SocialPost(
                    tenant_id=tenant_id,
                    platform=platform,
                    post_id=media_id,
                    media_type="STORIES",
                    insights=dict(metrics),
                    publish_status="expired",
                )
                session.add(post)
                result["created"] += 1
                continue
            # Merge, never replace: Meta sends a partial set per delivery and an earlier metric
            # must not vanish because a later event carried fewer keys.
            merged = dict(post.insights or {})
            merged.update(metrics)
            post.insights = merged
            result["updated"] += 1

        if result["created"]:
            logger.info(
                "instagram.story_insights_created_row",
                extra={
                    "tenant_id": str(tenant_id),
                    "platform": platform,
                    "count": result["created"],
                },
            )
        return result
