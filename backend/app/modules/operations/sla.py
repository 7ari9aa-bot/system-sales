"""SLA clock (spec §46) - business-hours, holiday and timezone aware.

The whole point of this module: an SLA deadline is NOT `created_at + N minutes`
on the wall clock. A merchant who closes at 17:00 and reopens at 09:00 must not
be marked as breaching at 02:00 — the clock is PAUSED while they are closed.

    Customer message -> SLA clock -> business hours -> pause after close
                                  -> resume next opening

Calendar shape (`BusinessCalendar.hours` is JSONB, keyed by weekday with
Monday = 0, each value a list of [open, close] "HH:MM" windows):

    {"0": [["09:00", "17:00"]], "5": [], "6": []}

An empty/absent `hours` means 24/7 — a tenant with no calendar configured is
never blocked by a misconfigured clock. `holidays` is a list of "YYYY-MM-DD"
strings in the calendar's own timezone.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "Africa/Cairo"

# A calendar with every day closed would otherwise spin forever. If no opening
# is found within this horizon we degrade to wall-clock time and log loudly —
# a broken calendar must not hang a worker or an API request.
MAX_SEARCH_DAYS = 30


def _parse_hhmm(raw: str) -> time | None:
    try:
        hour, minute = raw.strip().split(":", 1)
        return time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return None


@dataclass(frozen=True, slots=True)
class BusinessWindow:
    open_at: time
    close_at: time


# A 24/7 day: open from midnight to the last microsecond of the day.
_ALWAYS_OPEN = BusinessWindow(time(0, 0), time(23, 59, 59, 999999))


def _windows_for(hours: dict, weekday: int) -> list[BusinessWindow]:
    """Open windows for a weekday. Absent/empty config means 24/7."""
    if not hours:
        return [_ALWAYS_OPEN]
    raw = hours.get(str(weekday), hours.get(weekday))
    if raw is None:
        # The key is missing: treat as closed for that weekday only if the
        # calendar defines other days, otherwise 24/7.
        return [] if any(k in hours for k in range(7)) else [_ALWAYS_OPEN]
    windows: list[BusinessWindow] = []
    for pair in raw or []:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        start, end = _parse_hhmm(pair[0]), _parse_hhmm(pair[1])
        if start is not None and end is not None and end > start:
            windows.append(BusinessWindow(start, end))
    return windows


class BusinessClock:
    """Answers "when does N business minutes from now actually fall?"."""

    def __init__(self, calendar=None) -> None:
        self.timezone_name = getattr(calendar, "timezone", None) or DEFAULT_TIMEZONE
        try:
            self.tz = ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning("sla.unknown_timezone tz=%s", self.timezone_name)
            self.tz = ZoneInfo("UTC")
        self.hours: dict = getattr(calendar, "hours", None) or {}
        holidays = getattr(calendar, "holidays", None) or []
        self.holidays: set[str] = {str(h) for h in holidays}

    # -- primitives -------------------------------------------------------

    def local(self, at: datetime) -> datetime:
        """Convert an instant to the calendar's wall clock."""
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        return at.astimezone(self.tz)

    def is_holiday(self, day: date) -> bool:
        return day.isoformat() in self.holidays

    def is_open(self, at: datetime) -> bool:
        local = self.local(at)
        if self.is_holiday(local.date()):
            return False
        # HALF-OPEN window [open, close): at the closing instant the business
        # is already closed. With a closed interval, a deadline landing exactly
        # on close would read as "open with 0 minutes left", the walk would
        # make no progress and spin until the guard tripped.
        return any(
            window.open_at <= local.time() < window.close_at
            for window in _windows_for(self.hours, local.weekday())
        )

    def next_opening(self, at: datetime) -> datetime | None:
        """The next instant the business is open, at or after `at`."""
        local = self.local(at)
        for offset in range(MAX_SEARCH_DAYS + 1):
            day = local.date() + timedelta(days=offset)
            if self.is_holiday(day):
                continue
            windows = _windows_for(self.hours, day.weekday())
            for window in sorted(windows, key=lambda w: w.open_at):
                candidate = datetime.combine(day, window.open_at, tzinfo=self.tz)
                if offset == 0 and candidate < local:
                    continue
                return candidate
        return None

    def close_of_window(self, at: datetime) -> datetime | None:
        """The closing instant of the window containing `at`."""
        local = self.local(at)
        for window in _windows_for(self.hours, local.weekday()):
            if window.open_at <= local.time() < window.close_at:
                return datetime.combine(local.date(), window.close_at, tzinfo=self.tz)
        return None

    # -- the operation callers actually want ------------------------------

    def add_business_minutes(self, start: datetime, minutes: int) -> datetime:
        """Add `minutes` of OPEN time to `start`.

        Closed time does not count: the clock pauses at close and resumes at
        the next opening, skipping holidays.
        """
        if minutes <= 0:
            return self.local(start)
        if not self.hours and not self.holidays:
            # Fast path: a 24/7 calendar is just wall-clock arithmetic.
            return self.local(start) + timedelta(minutes=minutes)

        cursor = self.local(start)
        remaining = timedelta(minutes=minutes)
        for _ in range(MAX_SEARCH_DAYS * 24):
            if not self.is_open(cursor):
                nxt = self.next_opening(cursor)
                if nxt is None:
                    break
                cursor = nxt
                continue
            close_at = self.close_of_window(cursor)
            if close_at is None:
                break
            available = close_at - cursor
            if available >= remaining:
                return cursor + remaining
            remaining -= available
            cursor = close_at

        logger.warning(
            "sla.calendar_exhausted tz=%s holidays=%d — degrading to wall clock",
            self.timezone_name,
            len(self.holidays),
        )
        return self.local(start) + timedelta(minutes=minutes)


class SlaService:
    """Applies the SLA policy to conversations (spec §46)."""

    @staticmethod
    async def resolve_policy(session: AsyncSession, tenant_id: uuid.UUID, channel: str | None):
        """Channel-specific policy wins; otherwise the tenant default."""
        from app.modules.operations.models import SLAPolicy

        rows = (
            await session.execute(
                select(SLAPolicy).where(
                    SLAPolicy.tenant_id == tenant_id, SLAPolicy.status == "active"
                )
            )
        ).scalars().all()
        if not rows:
            return None
        if channel:
            for row in rows:
                if row.applies_to_channel == channel:
                    return row
        for row in rows:
            if row.is_default:
                return row
        return rows[0]

    @staticmethod
    async def resolve_clock(session: AsyncSession, tenant_id: uuid.UUID) -> BusinessClock:
        from app.modules.operations.models import BusinessCalendar

        rows = (
            await session.execute(
                select(BusinessCalendar).where(BusinessCalendar.tenant_id == tenant_id)
            )
        ).scalars().all()
        if not rows:
            return BusinessClock(None)
        for row in rows:
            if row.is_default:
                return BusinessClock(row)
        return BusinessClock(rows[0])

    @staticmethod
    async def start(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        conversation_id: uuid.UUID,
        channel: str | None = None,
        now: datetime | None = None,
    ):
        """Open a `running` first-response SLA for a conversation.

        Idempotent: a conversation already being tracked is returned as-is, so
        a replayed inbound event cannot restart (and thereby extend) its clock.
        """
        from app.modules.operations.models import SLAEvent

        existing = (
            await session.execute(
                select(SLAEvent).where(
                    SLAEvent.tenant_id == tenant_id,
                    SLAEvent.conversation_id == conversation_id,
                    SLAEvent.kind == "first_response",
                    SLAEvent.status == "running",
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        policy = await SlaService.resolve_policy(session, tenant_id, channel)
        if policy is None:
            return None
        clock = await SlaService.resolve_clock(session, tenant_id)
        now = now or datetime.now(UTC)
        deadline = clock.add_business_minutes(now, policy.first_response_minutes)
        event = SLAEvent(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            policy_id=policy.id,
            kind="first_response",
            status="running",
            deadline_at=deadline.astimezone(UTC),
        )
        session.add(event)
        await session.flush()
        return event

    @staticmethod
    async def mark_met(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        conversation_id: uuid.UUID,
        kind: str = "first_response",
        now: datetime | None = None,
    ):
        """Satisfy a running SLA (a human or AI actually replied in time)."""
        from app.modules.operations.models import SLAEvent

        event = (
            await session.execute(
                select(SLAEvent).where(
                    SLAEvent.tenant_id == tenant_id,
                    SLAEvent.conversation_id == conversation_id,
                    SLAEvent.kind == kind,
                    SLAEvent.status == "running",
                )
            )
        ).scalar_one_or_none()
        if event is None:
            return None
        event.status = "met"
        event.met_at = now or datetime.now(UTC)
        await session.flush()
        return event

    @staticmethod
    async def sweep(
        session: AsyncSession, tenant_id: uuid.UUID, *, now: datetime | None = None
    ) -> dict:
        """Mark running SLAs whose deadline has passed as breached.

        Runs on a schedule; without it a deadline is only decorative because
        nothing ever notices it passing.
        """
        from sqlalchemy import update

        from app.modules.operations.models import SLAEvent

        now = now or datetime.now(UTC)
        result = await session.execute(
            update(SLAEvent)
            .where(
                SLAEvent.tenant_id == tenant_id,
                SLAEvent.status == "running",
                SLAEvent.deadline_at.is_not(None),
                SLAEvent.deadline_at < now,
            )
            .values(status="breached")
        )
        breached = result.rowcount or 0
        if breached:
            logger.warning("sla.breached tenant=%s count=%s", tenant_id, breached)
        return {"breached": breached}


def validate_calendar(hours: dict | None, holidays: list | None) -> None:
    """Reject a calendar that could never open, or a malformed window."""
    if hours:
        if not isinstance(hours, dict):
            raise ValidationError("hours must be an object keyed by weekday")
        for key, raw in hours.items():
            if str(key) not in {str(d) for d in range(7)}:
                raise ValidationError(f"invalid weekday key: {key!r} (0=Monday..6=Sunday)")
            for pair in raw or []:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise ValidationError(f"invalid window for weekday {key}: {pair!r}")
                start, end = _parse_hhmm(pair[0]), _parse_hhmm(pair[1])
                if start is None or end is None:
                    raise ValidationError(f"window must be HH:MM pairs: {pair!r}")
                if end <= start:
                    raise ValidationError(f"window close must be after open: {pair!r}")
    if holidays is not None and not isinstance(holidays, list):
        raise ValidationError("holidays must be a list of YYYY-MM-DD strings")


def find_calendar_or_404(rows: list, calendar_id: uuid.UUID):
    for row in rows:
        if row.id == calendar_id:
            return row
    raise NotFoundError("business calendar not found")


__all__ = [
    "DEFAULT_TIMEZONE",
    "BusinessClock",
    "BusinessWindow",
    "SlaService",
    "find_calendar_or_404",
    "validate_calendar",
]
