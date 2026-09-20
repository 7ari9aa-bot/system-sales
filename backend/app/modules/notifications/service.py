"""NOTIFICATIONS service — create, list, mark-read, mark-all-read."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.notifications.models import Notification


def _now() -> datetime:
    return datetime.now(UTC)


class NotificationService:
    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        kind: str,
        body: str,
        title: str | None = None,
        action_url: str | None = None,
        payload: dict | None = None,
        dedup_key: str | None = None,
    ) -> Notification:
        """Create a notification, or skip silently on duplicate dedup_key."""
        if dedup_key:
            # Idempotent upsert: if a row with the same dedup_key already
            # exists for this tenant+user, return without inserting a duplicate.
            existing = (
                await session.execute(
                    select(Notification).where(
                        Notification.tenant_id == tenant_id,
                        Notification.user_id == user_id,
                        Notification.dedup_key == dedup_key,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing

        notif = Notification(
            tenant_id=tenant_id,
            user_id=user_id,
            kind=kind,
            title=title,
            body=body,
            action_url=action_url,
            payload=payload or {},
            dedup_key=dedup_key,
        )
        session.add(notif)
        await session.flush()
        return notif

    @staticmethod
    async def list_for_user(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        unread_only: bool = False,
        kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Notification]:
        stmt = (
            select(Notification)
            .where(
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
            )
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(min(limit, 200))
            .offset(offset)
        )
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        if kind:
            # The centre filters by kind; without this the UI would have to
            # fetch everything and filter in the browser, which cannot page.
            stmt = stmt.where(Notification.kind == kind)
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)

    @staticmethod
    async def summary(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> dict:
        """Counts the centre needs to label its filters: total, unread, by kind."""
        rows = (
            await session.execute(
                select(
                    Notification.kind,
                    func.count().label("total"),
                    func.count()
                    .filter(Notification.read_at.is_(None))
                    .label("unread"),
                )
                .where(
                    Notification.tenant_id == tenant_id,
                    Notification.user_id == user_id,
                )
                .group_by(Notification.kind)
            )
        ).all()

        by_kind = [
            {"kind": kind, "total": int(total), "unread": int(unread)}
            for kind, total, unread in rows
        ]
        by_kind.sort(key=lambda row: row["total"], reverse=True)
        return {
            "total": sum(row["total"] for row in by_kind),
            "unread": sum(row["unread"] for row in by_kind),
            "by_kind": by_kind,
        }

    @staticmethod
    async def mark_read(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_id: uuid.UUID,
    ) -> Notification:
        """Mark one notification read.

        Raises NotFoundError rather than returning None: the route used to
        answer HTTP 200 with {"detail": "not found"}, so a client marking a
        notification that had been deleted believed it had worked.
        """
        notif = (
            await session.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.user_id == user_id,
                    Notification.id == notification_id,
                )
            )
        ).scalar_one_or_none()
        if notif is None:
            raise NotFoundError("notification not found")
        if notif.read_at is None:
            notif.read_at = _now()
        return notif

    @staticmethod
    async def mark_many_read(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_ids: list[uuid.UUID],
    ) -> int:
        """Bulk mark-read, scoped to this user's own notifications."""
        result = await session.execute(
            update(Notification)
            .where(
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
                Notification.id.in_(notification_ids),
                Notification.read_at.is_(None),
            )
            .values(read_at=_now())
        )
        return result.rowcount  # type: ignore[return-value]

    @staticmethod
    async def mark_all_read(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> int:
        """Mark all unread notifications as read. Returns count updated."""
        result = await session.execute(
            update(Notification)
            .where(
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
            .values(read_at=_now())
        )
        return result.rowcount  # type: ignore[return-value]

    @staticmethod
    async def unread_count(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> int:
        from sqlalchemy import func
        from sqlalchemy import select as sa_select

        result = (
            await session.execute(
                sa_select(func.count()).where(
                    Notification.tenant_id == tenant_id,
                    Notification.user_id == user_id,
                    Notification.read_at.is_(None),
                )
            )
        ).scalar_one()
        return result or 0
