"""Merchant-day bucketing for analytics (gap M10, §47/M10 remainder).

Spec §55's read models and the metric registry (``app/modules/platform/metrics.py``)
pin the rule: a calendar-day bucket is the MERCHANT's day, never UTC midnight.
Bucketing a UTC+4 market by UTC shifts every sale before 04:00 local into the
previous day, so a "daily" series is wrong by a few hours at both ends.

Where the zone comes from — ``resolve_timezone``, in ONE order:

1. the caller's own zone (an explicit ``?timezone=`` on the request),
2. ``tenants.timezone`` — the zone THIS merchant declared (§47/M10 remainder:
   the same move §47 made for money, where ``tenants.currency`` replaced a
   Python literal),
3. the DEPLOYMENT's ``ANALYTICS_TIMEZONE``,
4. UTC.

Layers 3-4 are a fallback, not a lie: one zone applied everywhere, NAMED in the
response, is honest in a way a silent UTC bucket is not. A tenant that wants its
own day sets it through the audited ``PUT /tenants/{id}/timezone``; existing
rows are NULL precisely so nothing moves under them.

Every answer also says WHICH layer produced it (`ResolvedTimezone.source`),
because "the merchant's day" and "the deployment's guess about the merchant's
day" are different claims and a reader must not be able to confuse them.

`merchant_day` is the single definition of the rule. The SQL in service.py
expresses the same rule with ``AT TIME ZONE``; keep the two in lockstep.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REPORTING_TZ_ENV = "ANALYTICS_TIMEZONE"
FALLBACK_TIMEZONE = "UTC"

#: The layers `resolve_timezone` walks, in order. Exported as a tuple so the
#: readers (and the API contract tests) name the same set this module walks.
TIMEZONE_SOURCES: tuple[str, ...] = ("param", "tenant", "deployment", "fallback")


class UnknownTimezoneError(ValueError):
    """An IANA zone name the runtime cannot resolve — refuse rather than
    silently fall back to UTC, which is the bug this module exists to fix."""


class ResolvedTimezone(str):
    """A zone that remembers which layer of the chain answered.

    It IS a string — ``ZoneInfo(zone)``, an ``AT TIME ZONE`` bind and JSON all
    take it unchanged — but the ``source`` is what lets a reader that resolved
    the chain EARLY hand it down without silencing a lower layer.
    ``analytics/router.py`` does exactly that today: it validates the query
    parameter before it has looked at the tenant's row. Without provenance, the
    deployment zone it produces would look like a caller's choice and would mask
    ``tenants.timezone`` — re-creating in one line the gap this closes.
    """

    source: str

    def __new__(cls, value: str, *, source: str) -> ResolvedTimezone:
        if source not in TIMEZONE_SOURCES:
            raise ValueError(f"not a resolution layer: {source!r}")
        instance = super().__new__(cls, value)
        instance.source = source
        return instance


def _validated(candidate: str, source: str) -> ResolvedTimezone:
    name = (candidate or "").strip()
    if not name:
        raise UnknownTimezoneError(f"unknown timezone: {candidate!r}")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise UnknownTimezoneError(f"unknown timezone: {name!r}") from exc
    return ResolvedTimezone(name, source=source)


def _from_caller(name: str | None) -> str | None:
    """The caller's own zone, or None when the caller deferred.

    A `ResolvedTimezone` whose source is NOT ``param`` was produced by a lower
    layer of this same chain — the caller forwarded it, it did not choose it —
    so the tenant layer still gets to speak.
    """
    if name is None:
        return None
    if isinstance(name, ResolvedTimezone) and name.source != "param":
        return None
    return (str(name)).strip() or None


def resolve_timezone(
    name: str | None = None, *, tenant_timezone: str | None = None
) -> ResolvedTimezone:
    """The zone a merchant's day is counted in, and who said so.

    Order: ``name`` (the caller's own) -> ``tenant_timezone`` (the tenant's
    column) -> ``ANALYTICS_TIMEZONE`` -> UTC. Every layer is validated here, in
    one place: a stored zone that no longer resolves fails closed rather than
    quietly bucketing a Cairo shop in UTC.
    """
    caller = _from_caller(name)
    if caller is not None:
        return _validated(caller, "param")

    tenant = (tenant_timezone or "").strip()
    if tenant:
        return _validated(tenant, "tenant")

    deployment = (os.getenv(REPORTING_TZ_ENV) or "").strip()
    if deployment:
        return _validated(deployment, "deployment")

    return _validated(FALLBACK_TIMEZONE, "fallback")


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
