"""Merchant-day bucketing for analytics (gap M10).

Spec §55's read models and the metric registry (``app/modules/platform/metrics.py``)
pin the rule: a calendar-day bucket is the MERCHANT's day, never UTC midnight.
Bucketing a UTC+4 market by UTC shifts every sale before 04:00 local into the
previous day, so a "daily" series is wrong by a few hours at both ends.

Where the zone comes from: ``tenants`` has no timezone column, and adding one is
a migration nobody has approved. The registry already anticipates this — "the
concrete IANA zone is resolved from tenant settings at query time ... it is a
caller-supplied parameter". So the zone is a parameter here, and when no caller
supplies one we fall back to the DEPLOYMENT's configured zone (``ANALYTICS_TIMEZONE``,
UTC by default). That fallback is honest: it is one zone applied everywhere,
labelled in the response, rather than a silent UTC bucket dressed up as local.

`merchant_day` is the single definition of the rule. The SQL in service.py
expresses the same rule with ``AT TIME ZONE``; keep the two in lockstep.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REPORTING_TZ_ENV = "ANALYTICS_TIMEZONE"
FALLBACK_TIMEZONE = "UTC"


class UnknownTimezoneError(ValueError):
    """An IANA zone name the runtime cannot resolve — refuse rather than
    silently fall back to UTC, which is the bug this module exists to fix."""


def resolve_timezone(name: str | None = None) -> str:
    """Validate ``name`` as an IANA zone, falling back to the deployment zone."""
    candidate = (name or os.getenv(REPORTING_TZ_ENV) or FALLBACK_TIMEZONE).strip()
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise UnknownTimezoneError(f"unknown timezone: {candidate!r}") from exc
    return candidate


def merchant_day(instant: datetime, tz: str | None = None) -> date:
    """The merchant calendar day an instant belongs to.

    A naive instant is read as UTC: every timestamp column in this schema is
    ``timestamptz``, so a naive value only arrives from a hand-written test.
    """
    zone = ZoneInfo(resolve_timezone(tz))
    aware = instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)
    return aware.astimezone(zone).date()


def merchant_day_window(day: date, tz: str | None = None) -> tuple[datetime, datetime]:
    """The ``[since, until)`` UTC instants covering one merchant calendar day.

    Returned in UTC because every window filter in this codebase compares
    against a ``timestamptz`` column; the day itself is a merchant-day label.
    A day that contains a DST fold has no valid local midnight, which
    ``ZoneInfo`` resolves to an offset guess — acceptable here because a
    merchant-day *bucket* is still well defined by `merchant_day`.
    """
    zone = ZoneInfo(resolve_timezone(tz))
    since = datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(UTC)
    until = (datetime(day.year, day.month, day.day, tzinfo=zone) + timedelta(days=1)).astimezone(
        UTC
    )
    return since, until
