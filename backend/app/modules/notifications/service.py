"""NOTIFICATIONS service — create, list, mark-read, mark-all-read."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.errors import NotFoundError, ValidationError
from app.modules.notifications import schemas
from app.modules.notifications.models import Notification

#: The columns a row is read back with. ``updated_at`` is deliberately NOT one
#: of them (see ``mark_read``): a full-entity SELECT lists it, and a guard that
#: looks for a refused write in the emitted SQL then reads the column name as
#: the write itself. Loading only what ``NotificationOut`` renders also keeps the
#: centre from dragging every notification's body through a badge refresh.
_ROW_COLUMNS = (
    Notification.id,
    Notification.kind,
    Notification.title,
    Notification.body,
    Notification.action_url,
    Notification.payload,
    Notification.read_at,
    Notification.created_at,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _checked_page(*, limit: int, offset: int) -> tuple[int, int]:
    """The P7 bounds, enforced where the SQL is built rather than only at the edge.

    ``GET /notifications`` refuses a bad query string with 422 before this runs,
    but the route is not the only caller: an in-process ``limit=-1`` used to ride
    into ``LIMIT -1`` and ``offset=-1`` into ``OFFSET must not be negative`` —
    both Postgres errors, both a 500 from a caller that never touched HTTP.
    A negative (or absent) page is a bug in the caller, so it is refused; an
    oversized ``limit`` is a caller that just wants everything, so it is capped
    at ``PAGE_MAX`` like it always was — the cap is the contract, not the number.
    An oversized ``offset`` is refused rather than clamped: silently moving the
    page boundary would hand back a different list than the one asked for.
    """
    if limit < 1:
        raise ValidationError(
            f"limit must be at least 1, got {limit}",
            details={"limit": limit, "min": 1, "max": schemas.PAGE_MAX},
        )
    if offset < 0:
        raise ValidationError(
            f"offset must be 0 or more, got {offset}",
            details={"offset": offset, "min": 0, "max": schemas.OFFSET_MAX},
        )
    if offset > schemas.OFFSET_MAX:
        raise ValidationError(
            f"offset beyond {schemas.OFFSET_MAX} needs a cursor, not a bigger page",
            details={"offset": offset, "min": 0, "max": schemas.OFFSET_MAX},
        )
    return min(limit, schemas.PAGE_MAX), offset


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
        """Create a notification, or skip silently on duplicate dedup_key.

        Server-side only, on purpose: no route calls this, because a
        client-writable create would let any user push a row into another user's
        inbox in the same tenant. Every producer is in-process — the AI gateway,
        break-glass, automation runs.
        """
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
        # The pre-check above is check-then-act: two concurrent producers can
        # both see "absent". The partial unique index
        # (ix_notifications_tenant_user_dedup) makes the database the arbiter —
        # the loser's savepoint rolls back and it returns the winner's row,
        # exactly the ToolCall insert-race pattern.
        try:
            async with session.begin_nested():
                session.add(notif)
                await session.flush()
        except IntegrityError:
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
            raise
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
        limit, offset = _checked_page(limit=limit, offset=offset)
        stmt = (
            select(Notification)
            .options(load_only(*_ROW_COLUMNS))
            .where(
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
            )
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
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
    ) -> dict[str, Any]:
        """Counts the centre needs to label its filters: total, unread, by kind.

        The shape is the wire contract ``schemas.NotificationSummary``; the route
        validates this dict against it, so a renamed key fails there rather than
        quietly changing the body.
        """
        rows = (
            await session.execute(
                select(
                    Notification.kind,
                    func.count().label("total"),
                    func.count().filter(Notification.read_at.is_(None)).label("unread"),
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
        notification that had been deleted believed it had worked. The lookup
        runs BEFORE anything is written, so a refused read stamps no row — and
        it loads only the projected columns, so the one statement this path
        emits is a plain read.
        """
        notif = (
            await session.execute(
                select(Notification)
                .options(load_only(*_ROW_COLUMNS))
                .where(
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
        result = (
            await session.execute(
                select(func.count()).where(
                    Notification.tenant_id == tenant_id,
                    Notification.user_id == user_id,
                    Notification.read_at.is_(None),
                )
            )
        ).scalar_one()
        return result or 0

    # ------------------------------------------------------------------
    # §166 — Notification dedupe/digest
    # ------------------------------------------------------------------
    # The dedupe path is already wired (dedup_key above). The DIGEST path
    # groups unread notifications by kind and returns a summary so a user
    # can see "5 new orders, 2 SLA breaches" instead of 7 individual rows.
    # The route uses this to power the bell's collapsed view.

    @staticmethod
    async def digest(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> dict[str, Any]:
        """§166: group unread notifications by kind for the bell's collapsed view.

        The shape is the wire contract ``schemas.NotificationDigest``.
        """
        rows = (
            await session.execute(
                select(
                    Notification.kind,
                    func.count().label("count"),
                    func.max(Notification.created_at).label("latest_at"),
                )
                .where(
                    Notification.tenant_id == tenant_id,
                    Notification.user_id == user_id,
                    Notification.read_at.is_(None),
                )
                .group_by(Notification.kind)
                .order_by(func.count().desc())
            )
        ).all()

        groups = [
            {
                "kind": kind,
                "count": int(count),
                "latest_at": latest_at.isoformat() if latest_at else None,
            }
            for kind, count, latest_at in rows
        ]
        return {
            "total_unread": sum(g["count"] for g in groups),
            "groups": groups,
        }
