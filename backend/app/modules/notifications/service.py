"""NOTIFICATIONS service — create, list, mark-read, mark-all-read."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

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
        limit: int = 50,
        offset: int = 0,
    ) -> list[Notification]:
        stmt = (
            select(Notification)
            .where(
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
            )
            .order_by(Notification.created_at.desc())
            .limit(min(limit, 200))
            .offset(offset)
        )
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)

    @staticmethod
    async def mark_read(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_id: uuid.UUID,
    ) -> Notification | None:
        notif = (
            await session.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.user_id == user_id,
                    Notification.id == notification_id,
                )
            )
        ).scalar_one_or_none()
        if notif and notif.read_at is None:
            notif.read_at = _now()
        return notif

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
        from sqlalchemy import func, select as sa_select

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
