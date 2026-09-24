"""Spec §56 — monthly partitioning of the append-only series, and its maintenance.

What this module IS: the thin Python seam over the partition-maintenance
functions that ``f7a2c9d4e8b1`` installs. The DDL itself cannot live here,
because ``sales_app`` is granted USAGE on ``public`` plus table privileges and
deliberately NOT ``CREATE`` (``scripts/provision.py``), so no worker holding an
application connection may create or drop a table. The maintenance functions are
therefore SECURITY DEFINER, owned by the migration role, with a pinned
``search_path`` and a hard table allowlist inside the SQL body — the same shape
as ``resolve_channel_tenant`` in ``b2c3d4e5f6a7``. This module calls them; it
does not build DDL from strings.

HISTORY — what this module used to be, and why the claims were removed. Every
one of these was verified against the schema and the Postgres documentation, not
assumed:

* it asserted "declarative partitioning by created_at (range, monthly) is used"
  while NO table in the schema was partitioned. Nothing could call it without
  raising on the first ``PARTITION OF``, because a plain table cannot be a
  parent. It was not "primitives with no caller" — it was primitives for a
  structure that did not exist;
* ``detach_old_partitions()`` issued ``ALTER TABLE <child> DETACH PARTITION
  CONCURRENTLY``, which is not a statement: DETACH is issued against the PARENT
  (``ALTER TABLE parent DETACH PARTITION child [CONCURRENTLY]``). It also ran
  CONCURRENTLY inside the job's transaction, which Postgres forbids;
* it discovered partitions by matching ``tablename LIKE 'table_%'``, so it
  would have found ordinary tables whose names merely start the same way, and
  parsed a month out of the suffix with ``int(suffix[:4])`` — an
  ``IndexError``/``ValueError`` away from detaching the wrong object;
* it built bounds from naive ``datetime`` values against ``timestamptz``/``date``
  keys, and created a per-partition tenant index, duplicating the partitioned
  index the parent already propagates.

WHAT IS PARTITIONED (``PARTITIONED_TABLES``), and what §56 asked for:

    ai_usage   RANGE (period_date), monthly

The other four §56 candidates are NOT partitioned, and each reason is a
structural one, recorded where the gap can be seen rather than in a document
nobody reads:

* ``messages`` — inbound single-column FKs reference ``messages.id``
  (``attachments``, ``delivery_attempts``; see ``49303e2e2dd0`` and
  ``8a1f6fb95fc6``). A partitioned table can only carry a unique/PK constraint
  that includes the partition key, so ``messages.id`` could no longer be
  globally unique, and every one of those foreign keys becomes impossible.
  Statement of the blocker: ``app/modules/analytics/retention.py`` and
  ``migrations/versions/f7a2c9d4e8b1_*`` both name it; the retention worker's
  row-level path stays the mechanism for this store.
* ``event_log`` — ``app/core/events/outbox.py`` writes with
  ``ON CONFLICT (event_id) DO NOTHING``. Outbox idempotency would degrade to
  per-partition uniqueness, i.e. a duplicate event in a later month would be
  published twice. Not partitioned.
* ``webhook_events`` — ``uq_webhook_events_provider_external`` is the S10 replay
  guard (see ``b2c3d4e5f6a7``). Same argument as ``event_log``: a replay in a
  different month would slip past a month-local uniqueness check. Not partitioned.
* ``audit_logs`` — §57 and ``docs/PII_DATA_MAP.md`` put this store under legal
  retention, "never hard-delete". Partitioning it would exist to enable a DROP
  that must never happen. Not partitioned, and it is not on the maintenance
  allowlist either, so the purge path cannot reach it even by mistake.

§56 also warns "do not create thousands of partitions due to tenant count" —
which this shape honours: one partition per month per table, never per tenant.
That is exactly why a dropped month is a shared act, and why
``analytics/retention.py`` will not drop one unless every active tenant chose it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Store the migration actually partitions -> its range key. Anything here may be
#: maintained; anything absent may not (and the SQL side enforces the same list).
PARTITIONED_TABLES: Mapping[str, str] = {"public.ai_usage": "period_date"}

#: Parents the SECURITY DEFINER maintenance functions accept. Kept separate from
#: ``PARTITIONED_TABLES`` because a table can be partitioned by hand without ever
#: being auto-maintained; today the two sets are identical on purpose.
PARTITION_MAINTENANCE_ALLOWLIST: tuple[str, ...] = tuple(sorted(PARTITIONED_TABLES))

#: The name the conversion leaves behind. It is NOT dropped: it is the rollback
#: that does not depend on a restore from backup.
LEGACY_SNAPSHOT_TABLE = "ai_usage_pre_partition"

#: ``ai_usage_default`` — the catch-all that keeps a business write from failing
#: when a month has not been pre-created. Never a purge target.
DEFAULT_PARTITION_SUFFIX = "_default"

#: Months a month partition must be older than before ANYONE may drop it, even
#: with a per-tenant policy that asks for less. 13 is the horizon
#: ``docs/PII_DATA_MAP.md`` states for ``ai_usage`` ("metrics ... 13 months").
#: Enforced a second time inside ``partitioning_purge_month``, because a Python
#: constant cannot stop a caller that reaches the function directly.
PARTITION_DROP_FLOOR_MONTHS = 13

ENSURE_ONE_FUNCTION = "public.partitioning_ensure_partition"
ENSURE_FUNCTION = "public.partitioning_ensure_months"
PURGE_FUNCTION = "public.partitioning_purge_month"

#: `FOR VALUES FROM ('2026-09-01') TO ('2026-10-01')` as the catalog renders it.
_BOUND_RE = re.compile(r"FROM \('(\d{4}-\d{2}-\d{2})'\) TO \('(\d{4}-\d{2}-\d{2})'\)")

_MONTH_RE = re.compile(r"^(?P<base>.+)_(?P<year>\d{4})_(?P<month>\d{2})$")


class PartitionMaintenanceError(RuntimeError):
    """Base class: partition maintenance did not happen, and nothing was lost."""


class PartitionMaintenanceUnavailable(PartitionMaintenanceError):
    """The helpers are missing or the connected role may not use them.

    Raised instead of quietly returning "0 created": a deployment whose
    migrations lag behind the code must fail the job loudly. That is the exact
    class of invisible no-op this repo has already been burned by twice
    (``ensure_recurring_jobs`` running unbound, retention never being seeded).
    """


class PartitionMaintenanceRefused(PartitionMaintenanceError):
    """The database said no to the argument: not an allowlisted parent, not a
    whole month, or still inside :data:`PARTITION_DROP_FLOOR_MONTHS`."""


def _classify(exc: DBAPIError, *, action: str) -> PartitionMaintenanceError:
    """Map Postgres SQLSTATEs onto the two honest failure modes."""
    state = getattr(getattr(exc, "orig", None), "sqlstate", None) or ""
    message = str(getattr(exc, "orig", exc))
    if state == "22023":  # invalid_parameter_value — raised by the functions below
        return PartitionMaintenanceRefused(f"{action} refused by the database: {message}")
    if state in ("42501", "3F000", "42883", "42P01"):
        # insufficient_privilege / undefined schema / undefined function /
        # undefined table: the migration is missing, lagging, or the role lost
        # its EXECUTE grant.
        return PartitionMaintenanceUnavailable(
            f"{action} is unavailable in this database ({message.strip()}). "
            "Expected the SECURITY DEFINER maintenance functions from "
            "f7a2c9d4e8b1 and EXECUTE granted to the application role."
        )
    return PartitionMaintenanceError(f"{action} failed: {message.strip()}")


async def _call(session: AsyncSession, statement: str, params: dict[str, Any], *, action: str):
    try:
        result = await session.execute(text(statement), params)
    except DBAPIError as exc:
        raise _classify(exc, action=action) from exc
    return result


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """Half-open ``[first-of-month, first-of-next-month)`` in UTC terms."""
    if not 1 <= month <= 12 or not 1 <= year <= 9999:
        raise ValueError(f"not a month: {year}-{month:02d}")
    end_year, end_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return date(year, month, 1), date(end_year, end_month, 1)


def month_of(value: date) -> date:
    return date(value.year, value.month, 1)


def partition_name(parent: str, month_start: date) -> str:
    """`public.ai_usage` + 2026-09 -> `ai_usage_2026_09` (the naming the SQL uses)."""
    if not isinstance(month_start, date) or month_start.day != 1:
        raise ValueError(f"not a month start: {month_start}")
    base = parent.split(".")[-1]
    return f"{base}_{month_start:%Y_%m}"


def is_default_partition(name: str) -> bool:
    return name.endswith(DEFAULT_PARTITION_SUFFIX)


def is_month_partition(name: str) -> bool:
    return bool(_MONTH_RE.match(name))


def _require_parent(parent: str) -> str:
    if parent not in PARTITIONED_TABLES:
        raise ValueError(
            f"{parent} is not a partitioned table of this schema "
            f"(partitioned: {sorted(PARTITIONED_TABLES)}). §56 candidates that "
            "cannot be converted are listed in this module's docstring."
        )
    return parent


async def ensure_partition_for_month(
    session: AsyncSession, parent: str, month_start: date
) -> str | None:
    """Create one monthly partition (grants + RLS included). None if it exists."""
    _require_parent(parent)
    created = await _call(
        session,
        f"SELECT {ENSURE_ONE_FUNCTION}(:parent, CAST(:month AS date)) AS name",
        {"parent": parent, "month": month_start},
        action=f"{ENSURE_ONE_FUNCTION}({parent}, {month_start})",
    )
    return created.scalar()


async def ensure_month_partitions(
    session: AsyncSession, *, months_ahead: int = 3
) -> list[str]:
    """Ensure this month plus the next ``months_ahead`` exist, for every table
    on the maintenance allowlist. Returns the partitions actually created.

    Ahead-of-time, monthly, and idempotent: a healthy month creates nothing.
    """
    if not 0 <= months_ahead <= 24:
        raise ValueError(f"months_ahead out of range: {months_ahead}")
    created: list[str] = []
    for parent in sorted(PARTITION_MAINTENANCE_ALLOWLIST):
        rows = await _call(
            session,
            f"SELECT unnest({ENSURE_FUNCTION}(:parent, :ahead)) AS name",
            {"parent": parent, "ahead": months_ahead},
            action=f"{ENSURE_FUNCTION}({parent}, {months_ahead})",
        )
        names = [r[0] for r in rows]
        if names:
            logger.info("partition.created %s: %s", parent, ", ".join(names))
        created.extend(names)
    return created


async def purge_month(session: AsyncSession, parent: str, month_start: date) -> str | None:
    """DETACH + DROP one whole month partition. Returns the dropped name, or None
    when that month's partition was already gone.

    Deliberately narrow, in four directions:

    * the parent must be on the allowlist (checked here AND in the SQL body);
    * the month must be a real attached child, never the DEFAULT partition;
    * the database refuses anything inside :data:`PARTITION_DROP_FLOOR_MONTHS`
      regardless of what a policy says;
    * non-concurrent ``DETACH``, so it commits or rolls back with the caller's
      job transaction, and an advisory lock inside the function so two workers
      cannot race the same month.

    It is still an unrecoverable act, which is why the only caller with a
    legitimate reason to use it is ``analytics.retention.purge_expired_partitions``
    — after the consent gate, not before it.
    """
    _require_parent(parent)
    dropped = await _call(
        session,
        f"SELECT {PURGE_FUNCTION}(:parent, CAST(:month AS date)) AS name",
        {"parent": parent, "month": month_start},
        action=f"{PURGE_FUNCTION}({parent}, {month_start})",
    )
    name = dropped.scalar()
    if name:
        logger.warning("partition.dropped %s.%s", parent, name)
    return name


async def list_partition_months(session: AsyncSession, parent: str) -> list[date]:
    """Month starts of the ATTACHED children, read from the partition bounds.

    The catalog is the only source of truth: names are a convention, ``FOR
    VALUES`` is a fact. The DEFAULT partition is excluded — it has no month and
    no horizon.
    """
    _require_parent(parent)
    rows = (
        await _call(
            session,
            "SELECT c.relname, pg_get_expr(cc.relpartbound, c.oid) "
            "FROM pg_inherits i "
            "JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class cc ON cc.oid = c.oid "
            "WHERE i.inhparent = to_regclass(:parent) ORDER BY c.relname",
            {"parent": parent},
            action=f"list_partition_months({parent})",
        )
    ).all()
    months: list[date] = []
    for name, bound in rows:
        if is_default_partition(name) or not bound:
            continue
        match = _BOUND_RE.search(bound)
        if not match:  # a non-monthly child: not ours to decide about
            logger.warning("partition.unparsed_bound %s: %s", name, bound)
            continue
        months.append(date.fromisoformat(match.group(1)))
    return sorted(months)
