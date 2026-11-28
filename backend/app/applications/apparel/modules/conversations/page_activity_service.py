"""What happened on the store's Page, recorded on the server instead of in one browser.

The Facebook notifications screen used to be rebuilt from the post list on every load, and its
read mark lived in `localStorage`. That had three consequences the review named: a new post, an
edited post, a deleted post, a reaction or a video produced no notification at all; a mention was
invisible until someone opened the post; and one staff member reading a notification left it
unread on every other device.

This module is the durable half of the fix. The webhook writes a row per event (idempotently —
Meta retries deliveries for up to seven days), and the screen reads rows and marks them read for
the whole tenant. Nothing here calls Meta: an event Meta already told us about needs no second
question, and an object we do not hold is still a real notification ("a post was published") even
though we cannot render its caption.

Deliberately NOT a Message and NOT a SocialComment: activity is a feed of events for staff, it
pages nobody and triggers no AI turn.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.apparel.modules.conversations.models import PageActivity

#: The kinds this module writes, and the Arabic line each one shows. Kept as data so the screen
#: and the tests agree on one vocabulary instead of matching strings in three places.
KINDS = (
    "mention",
    "post",
    "post_edit",
    "post_delete",
    "reaction",
    "share",
    "video",
    "comment",
    "live_comment",
    "policy",
)

#: Meta's `item` values, mapped to what the notification says happened.
_POST_ITEMS = frozenset({"post", "status", "photo", "video", "share", "link", "reel"})
_REACTION_ITEMS = frozenset({"reaction", "like"})

_SUMMARY = {
    "mention": "أشار إليك أحدهم",
    "post": "منشور جديد على الصفحة",
    "post_edit": "تم تعديل منشور",
    "post_delete": "تم حذف منشور",
    "reaction": "تفاعل جديد على منشور",
    "share": "تمت مشاركة منشور",
    "video": "فيديو جديد على الصفحة",
    "comment": "تعليق جديد",
    "live_comment": "تعليق مباشر جديد",
    "policy": "ميتا حذّرت أو أوقفت مراسلة الصفحة",
}


def summary_for(kind: str) -> str:
    """The one line a notification of this kind shows."""
    return _SUMMARY.get(kind, "حدث جديد على الصفحة")


def _epoch(value: object) -> datetime | None:
    """Meta sends seconds since the epoch, sometimes as a string."""
    try:
        seconds = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return datetime.fromtimestamp(seconds, tz=UTC)


def _dedup_key(channel: str, kind: str, object_id: str, occurred_at: datetime) -> str:
    """One event, however many times Meta delivers it.

    The timestamp is part of the key on purpose: two reactions on the same post a minute apart are
    two events, while the same delivery replayed is one.
    """
    return f"{channel}:{kind}:{object_id}:{int(occurred_at.timestamp())}"


class PageActivityService:
    """Write and read the Page's event feed, per tenant."""

    @staticmethod
    async def record(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        channel: str,
        kind: str,
        object_id: str,
        occurred_at: datetime,
        parent_id: str | None = None,
        actor_name: str | None = None,
        actor_id: str | None = None,
        summary: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Store one event. Returns True when it was new, False when it was already there.

        A duplicate is not an error: Meta retries, and the same change can arrive in two
        deliveries. The row is left alone rather than updated, because the first delivery is the
        one staff were notified about.
        """
        object_id = str(object_id or "").strip()
        if not object_id:
            return False
        key = _dedup_key(channel, kind, object_id, occurred_at)
        existing = await session.scalar(
            select(PageActivity.id).where(
                PageActivity.tenant_id == tenant_id, PageActivity.dedup_key == key
            )
        )
        if existing is not None:
            return False
        session.add(
            PageActivity(
                tenant_id=tenant_id,
                channel=channel,
                kind=kind,
                object_id=object_id,
                parent_id=parent_id,
                actor_name=actor_name,
                actor_id=actor_id,
                summary=summary or summary_for(kind),
                payload=payload,
                occurred_at=occurred_at,
                dedup_key=key,
            )
        )
        return True

    @staticmethod
    async def record_changes(
        session: AsyncSession, tenant_id: uuid.UUID, channel: str, changes: list[dict]
    ) -> dict[str, int]:
        """Turn a Page delivery's `changes` into notifications, whatever else happens to them.

        This runs next to `PageEventProcessor.apply`, not instead of it: `apply` keeps the post
        and comment rows correct, this keeps the merchant informed. A change for a post we do not
        hold still produces a notification — the event is real even when the object is not ours to
        render.
        """
        written = 0
        duplicates = 0
        ignored = 0
        for change in changes:
            value = change.get("value") or {}
            item = str(value.get("item") or "").lower()
            field = str(change.get("field") or "").lower()
            post_id = str(value.get("post_id") or "").strip()
            verb = str(value.get("verb") or "add").lower()

            if field in {"mention", "mentions"}:
                kind = "mention"
                object_id = str(value.get("post_id") or value.get("comment_id") or "").strip()
            elif item in _REACTION_ITEMS:
                kind = "reaction"
                object_id = post_id
            elif item in _POST_ITEMS:
                kind = "post_delete" if verb == "remove" else "post"
                if kind == "post" and value.get("edited"):
                    kind = "post_edit"
                object_id = post_id
            elif item == "comment":
                kind = "comment"
                object_id = str(value.get("comment_id") or "").strip()
            else:
                ignored += 1
                continue

            if not object_id:
                ignored += 1
                continue

            occurred = _epoch(value.get("created_time") or value.get("timestamp")) or datetime.now(
                UTC
            )
            created = await PageActivityService.record(
                session,
                tenant_id,
                channel=channel,
                kind=kind,
                object_id=object_id,
                occurred_at=occurred,
                parent_id=post_id if post_id != object_id else None,
                actor_name=value.get("from", {}).get("name")
                if isinstance(value.get("from"), dict)
                else None,
                actor_id=value.get("from", {}).get("id")
                if isinstance(value.get("from"), dict)
                else None,
                summary=summary_for(kind),
                payload=value if isinstance(value, dict) else None,
            )
            if created:
                written += 1
            else:
                duplicates += 1
        return {"written": written, "duplicates": duplicates, "ignored": ignored}

    @staticmethod
    async def list_activity(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        channel: str = "facebook",
        only_unread: bool = False,
        limit: int = 50,
    ) -> list[PageActivity]:
        """The newest events first, as the notifications screen shows them."""
        query = select(PageActivity).where(
            PageActivity.tenant_id == tenant_id, PageActivity.channel == channel
        )
        if only_unread:
            query = query.where(PageActivity.read_at.is_(None))
        rows = await session.execute(
            query.order_by(PageActivity.occurred_at.desc()).limit(max(1, min(limit, 200)))
        )
        return list(rows.scalars())

    @staticmethod
    async def mark_read(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        channel: str = "facebook",
        up_to: datetime | None = None,
    ) -> int:
        """Mark everything up to `up_to` read for the whole tenant. Returns how many changed.

        `up_to` defaults to now: the screen's "mark all read". One row, every device — which is
        the whole point of moving the mark off `localStorage`.
        """
        cutoff = up_to or datetime.now(UTC)
        result = await session.execute(
            update(PageActivity)
            .where(
                PageActivity.tenant_id == tenant_id,
                PageActivity.channel == channel,
                PageActivity.read_at.is_(None),
                PageActivity.occurred_at <= cutoff,
            )
            .values(read_at=datetime.now(UTC))
        )
        return int(result.rowcount or 0)
