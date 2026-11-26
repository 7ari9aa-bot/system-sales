"""NOTIFICATIONS service — create, list, mark-read, mark-all-read."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.errors import NotFoundError, ValidationError
from app.modules.notifications import schemas
from app.modules.notifications.models import Notification, NotificationPreference

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


async def person_timezone(session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """The zone this person reads a clock in: their own, else the workspace's.

    It is the same resolution ``GET /users/me/preferences`` reports as
    ``effective_timezone``, and it exists so a quiet-hours window is compared
    against the clock the person is actually living in. A stored zone Python
    cannot resolve falls back to UTC rather than raising: a notification is not
    worth failing a checkout over.
    """
    from sqlalchemy import text as _text

    zone = (
        await session.execute(
            _text(
                "SELECT COALESCE(u.timezone, t.timezone) FROM users u "
                "JOIN tenants t ON t.id = :tenant_id WHERE u.id = :user_id"
            ),
            {"tenant_id": tenant_id, "user_id": user_id},
        )
    ).scalar_one_or_none()
    return zone or "UTC"


async def person_local_time(
    session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> time:
    """The person's current local time of day, for quiet-hours comparison."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    zone = await person_timezone(session, tenant_id, user_id)
    try:
        moment = datetime.now(ZoneInfo(zone))
    except (ZoneInfoNotFoundError, ValueError):
        moment = datetime.now(UTC)
    return moment.time().replace(tzinfo=None)


class NotificationPreferencesService:
    """The person's own notification settings: which channels, and when to be quiet.

    One row per person (migration fe2026112611). Reading CREATES the row when it is
    missing, because the screen has to show real state — "no row yet" and "email is
    on" are the same thing, and a screen that renders neither is a screen the person
    cannot reason about. The defaults are the model's: email on, push off, no quiet
    hours.
    """

    @staticmethod
    async def get_or_create(
        session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> NotificationPreference:
        pref = (
            await session.execute(
                select(NotificationPreference).where(
                    NotificationPreference.tenant_id == tenant_id,
                    NotificationPreference.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if pref is not None:
            return pref
        pref = NotificationPreference(tenant_id=tenant_id, user_id=user_id)
        session.add(pref)
        try:
            await session.flush()
        except IntegrityError:
            # Two tabs opened the screen at once: the other one created the row.
            await session.rollback()
            pref = (
                await session.execute(
                    select(NotificationPreference).where(
                        NotificationPreference.tenant_id == tenant_id,
                        NotificationPreference.user_id == user_id,
                    )
                )
            ).scalar_one()
        return pref

    @staticmethod
    async def read(
        session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> NotificationPreference | None:
        """The person's row, or None when they have never opened the screen.

        Deliberately does not create one: ``dispatch`` runs inside the caller's
        transaction, and a preference write there could roll back the notification
        it was called to deliver. No row means the model's defaults, which the
        caller applies itself.
        """
        return (
            await session.execute(
                select(NotificationPreference).where(
                    NotificationPreference.tenant_id == tenant_id,
                    NotificationPreference.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def update(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        email_enabled: bool | None = None,
        push_enabled: bool | None = None,
        quiet_start: str | None = None,
        quiet_end: str | None = None,
    ) -> NotificationPreference:
        """Rewrite the person's channels and quiet window.

        ``None`` leaves a value alone, so one switch saves without resending the
        rest. An empty string on either end of the window CLEARS the window — a
        half-open window is not a thing, and silently keeping yesterday's end time
        would be a screen that lies about when it goes quiet.
        """
        pref = await NotificationPreferencesService.get_or_create(session, tenant_id, user_id)

        if email_enabled is not None and email_enabled != pref.email_enabled:
            pref.email_enabled = email_enabled
        if push_enabled is not None and push_enabled != pref.push_enabled:
            pref.push_enabled = push_enabled

        if quiet_start is not None or quiet_end is not None:
            raw_start = quiet_start if quiet_start is not None else ""
            raw_end = quiet_end if quiet_end is not None else ""
            if not raw_start.strip() and not raw_end.strip():
                pref.quiet_start = None
                pref.quiet_end = None
            else:
                pref.quiet_start = NotificationPreferencesService._parse_time(
                    raw_start, "quiet hours start"
                )
                pref.quiet_end = NotificationPreferencesService._parse_time(
                    raw_end, "quiet hours end"
                )
                if pref.quiet_start == pref.quiet_end:
                    raise ValidationError(
                        "a quiet window needs two different times",
                        details={"quiet_start": raw_start, "quiet_end": raw_end},
                    )

        await session.flush()
        return pref

    @staticmethod
    def _parse_time(value: str, label: str) -> time:
        """``HH:MM`` (24h) is the only shape the screen sends. Anything else is a 400."""
        raw = (value or "").strip()
        try:
            hour, minute = raw.split(":")
            parsed = time(hour=int(hour), minute=int(minute))
        except (ValueError, TypeError) as exc:
            raise ValidationError(
                f"{label} must be a time of day as HH:MM, got '{raw}'",
                details={"value": raw},
            ) from exc
        if not (0 <= parsed.hour <= 23 and 0 <= parsed.minute <= 59):
            raise ValidationError(f"{label} must be a time of day as HH:MM, got '{raw}'")
        return parsed


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
    # §166 — Notification dispatch (email / push gating)
    # ------------------------------------------------------------------

    @staticmethod
    async def dispatch(
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
        """Create an in-app notification and fan out to email/push channels.

        Email delivery is gated by ``notifications.email_enabled`` (default
        False); push by ``notifications.push_enabled`` (default False).
        The in-app bell always receives the row — only the external
        channels are conditional.  The settings are read via
        ``app.core.settings_read`` (no import cycle with settings).
        """
        from app.core.settings_read import resolve_settings

        notif = await NotificationService.create(
            session,
            tenant_id,
            user_id,
            kind=kind,
            body=body,
            title=title,
            action_url=action_url,
            payload=payload,
            dedup_key=dedup_key,
        )

        channels = await resolve_settings(
            session,
            tenant_id,
            ["notifications.email_enabled", "notifications.push_enabled"],
        )

        # Two gates, and both must be open. The WORKSPACE decides whether this
        # deployment sends the channel at all (a shop that has no email provider
        # configured must not send email); the PERSON decides whether they want it
        # and whether they are currently quiet. Before this, the personal screen had
        # nothing to write to and the switches would have been decoration.
        pref = await NotificationPreferencesService.read(session, tenant_id, user_id)
        quiet = False
        if pref is not None and pref.quiet_start is not None and pref.quiet_end is not None:
            from app.modules.notifications.digest import NotificationAggregator

            local_now = await person_local_time(session, tenant_id, user_id)
            quiet = NotificationAggregator._in_quiet_hours(pref, now_time=local_now)

        # No row yet means the model defaults: email on, push off.
        person_email = True if pref is None else pref.email_enabled
        person_push = False if pref is None else pref.push_enabled
        want_email = channels["notifications.email_enabled"] and person_email and not quiet
        want_push = channels["notifications.push_enabled"] and person_push and not quiet

        delivery_ok = True
        try:
            if want_email:
                await NotificationService._send_email(
                    session, tenant_id, user_id, title=title or kind, body=body
                )
            if want_push:
                await NotificationService._send_push(
                    session, tenant_id, user_id, title=title or kind, body=body
                )
        except Exception:
            delivery_ok = False
            raise
        finally:
            from app.core.metrics import increment

            await increment(
                "notification_delivery_total",
                value=1,
                strict=False,
                outcome="delivered" if delivery_ok else "failed",
            )

        return notif

    @staticmethod
    async def _send_email(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        title: str,
        body: str,
    ) -> None:
        """Queue an email notification for the user.

        Uses the existing outbox pattern so delivery is durable and retried
        by the worker.  The email provider (Resend) is configured separately
        via ``auth_email_delivery_configured``; when it is not configured the
        email is silently skipped — the in-app notification still lands.
        """
        from sqlalchemy import text as _text

        from app.core.events.writer import add_outbox_event

        # Look up the recipient address (RLS-scoped by tenant_id GUC) — raw SQL
        # to avoid a cross-module import into identity.models.
        row = (
            await session.execute(
                _text("SELECT email FROM users WHERE id = :uid"), {"uid": user_id}
            )
        ).first()
        if row is None or not row[0]:
            return
        await add_outbox_event(
            session,
            aggregate_type="notification",
            aggregate_id=user_id,
            event_type="notification.email",
            tenant_id=tenant_id,
            producer="notifications",
            payload={
                "to": row[0],
                "subject": title,
                "body": body,
                "user_id": str(user_id),
            },
        )

    @staticmethod
    async def _send_push(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        title: str,
        body: str,
    ) -> None:
        """Queue a push notification for the user.

        Push tokens are stored per-user (future: a device-token table).
        For now the event is staged in the outbox so a push worker can pick
        it up when a provider is configured.
        """
        from app.core.events.writer import add_outbox_event

        await add_outbox_event(
            session,
            aggregate_type="notification",
            aggregate_id=user_id,
            event_type="notification.push",
            tenant_id=tenant_id,
            producer="notifications",
            payload={
                "title": title,
                "body": body,
                "user_id": str(user_id),
            },
        )

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

    @staticmethod
    async def record_monitor_alerts(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        owner_ids: list[uuid.UUID],
        alerts: list[dict],
    ) -> int:
        """Land tripped tenant-health monitors in the owners' bell.

        The producer is the platform monitors scheduler (workers layer), which
        passes the alert dicts and the owner ids it already resolved — this
        module imports nothing from the monitoring module, so the dependency
        stays one-directional (deep-review boundary discipline). Dedup key
        carries the UTC date: a monitor that stays tripped reminds the
        merchant once per day, not every five minutes.
        """
        from datetime import datetime as _dt

        if not alerts or not owner_ids:
            return 0
        today = _dt.now(UTC).strftime("%Y-%m-%d")
        created = 0
        for alert in alerts:
            for user_id in owner_ids:
                await NotificationService.create(
                    session,
                    tenant_id,
                    user_id,
                    kind="health",
                    title=f"Monitor: {alert['code']}",
                    body=alert["detail"],
                    payload={"severity": alert["severity"], "code": alert["code"]},
                    dedup_key=f"monitor:{alert['fingerprint']}:{today}",
                )
                created += 1
        return created
