"""§52/§57 — retention as a CHOSEN policy, executed partition by partition.

This is the half of §55-57 that the deleted ``archive_old_rows`` could not be:
a path that removes cold data, plus the decision about when it is allowed.
§52 makes retention per data class and per tenant and says a worker executes
it, not a UI; §57 makes it a ladder (hot -> archive -> delete) that must not
break Customer 360 or the legal audit trail. Neither section names a duration,
so the default below is taken from the only row in this repository that does:
``docs/PII_DATA_MAP.md`` gives ``ai_usage`` 13 months and says the retention
worker deletes it. That is ``DEFAULT_RETENTION_DAYS`` and the 13-month floor in
:meth:`app.core.partitioning.PARTITION_DROP_FLOOR_MONTHS`.

The rule, and why it is fail-closed
----------------------------------
§56 partitions by TIME, never by tenant — "do not create thousands of
partitions due to tenant count". Consequence, and the whole design of this
module: **one month belongs to every tenant at once**, so a ``DETACH``/``DROP``
cannot honour a per-tenant choice the way a row-level ``DELETE`` can.

* a tenant whose horizon is SHORTER than the others is served by the existing
  row-level worker (``retention.run`` over ``_RETENTABLE``), which deletes only
  its own rows and can therefore be as aggressive as that tenant wishes;
* a month may be dropped only when EVERY active tenant has chosen a policy for
  that store, actively, not by silence — so the LONGEST chosen horizon pins the
  month, and one tenant that never chose (or chose ``paused``) pins it for
  everyone. The result is reported, never swallowed.

Nothing here creates a policy row on a tenant's behalf. ``DEFAULT_RETENTION_DAYS``
is the value the opt-in surface offers; the database default for a policy row is
``paused`` (``f7a2c9d4e8b1``), so an un-answered question cannot delete data.
``choose_policy`` is the ONLY writer in this module, and it is an explicit
opt-in/opt-out call.

Boundaries kept on purpose
--------------------------
* no cross-module imports: ``retention_policies`` belongs to ``privacy`` and
  ``audit_logs`` to ``platform``, and ``tests/test_module_boundaries.py``
  ratchets that count at 94 — so the policy rows are read and written with bound
  raw SQL, and the audit append goes through ``app.core.audit`` (a core
  capability, not a domain).
* the cross-tenant tally is NOT computed here. ``retention_policies`` is FORCE
  RLS: this session may see one tenant's rows, and a worker that "knew" every
  tenant's choices by reading the table would be a tenant-isolation bug. It
  calls ``public.retention_drop_horizon(text)``, a SECURITY DEFINER aggregate
  that returns COUNTS and the longest horizon only — never another tenant's
  policy, its data class, or its existence by name.
* no timezone is resolved here (``analytics/timekit.py`` owns that). Partition
  boundaries are UTC months by construction, so this module plans in ``date``
  values and never in local days.
* this module is not a read model. ``analytics/service.py`` stays read-only;
  cold-data removal is DDL and lives beside the scheduler that runs it.

What is deliberately NOT enforced
---------------------------------
* a per-tenant floor: ``retention_days`` bounds (1..3650) exist in the
  migration, but only the shared month floor is checked at DDL time, because a
  day-level policy for one tenant cannot protect other tenants' rows in a shared
  partition;
* any store not in :data:`PARTITIONED_DATA_CLASSES` — ``messages``,
  ``event_log``, ``webhook_events`` cannot be partitioned (their single-column
  keys/foreign keys are the conflict target of an ``ON CONFLICT`` or an
  inbound FK), and ``audit_logs`` must never be hard-deleted (§57 legal
  retention). See ``app/core/partitioning.py``.

The merchant's door
-------------------
``analytics/router.py`` publishes the two halves of the opt-in seam:
``GET /analytics/retention`` (my policy + what the shared gate says + what would
unblock it) and ``PUT /analytics/retention/policies/{data_class}`` (the choice,
audited through ``app.core.audit``). Before those routes existed this module was
"governance by docstring" in the exact shape the gap register keeps hitting: the
table, the rule and the sweep were all there, but no caller could answer the
question, so the fail-closed gate refused forever and the purge was a job that
ran and always declined. The routes add no decision of their own — they call
:data:`CHOOSABLE_DATA_CLASSES`, :func:`policy_position`, :func:`read_policy`,
:func:`choose_policy` and :func:`read_drop_gate`, and refuse an illegal horizon
or status at the boundary the way §47 refuses an unknown currency.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import partitioning
from app.core.audit import write_audit_row

logger = logging.getLogger(__name__)

#: The store this module may purge partition-wise. Matches
#: ``app.core.partitioning.PARTITIONED_TABLES`` one-for-one.
PARTITIONED_DATA_CLASSES: Mapping[str, str] = {"ai_usage": "public.ai_usage"}

AI_USAGE_DATA_CLASS = "ai_usage"

#: docs/PII_DATA_MAP.md: "ai_usage | tokens/cost — NO content | metrics |
#: 13 months | retention worker". 13 months is offered as 390 days; the
#: month-exact floor (13 calendar months) is separately enforced in Python and
#: in the purge function, so the floor is never looser than this offer.
DEFAULT_RETENTION_DAYS: Mapping[str, int] = {AI_USAGE_DATA_CLASS: 390}
DEFAULT_RETENTION_SOURCE = (
    "docs/PII_DATA_MAP.md — ai_usage: 13 months, deleted by the retention "
    "worker (spec §52 per-data-class retention, §57 hot->archive->delete)"
)

#: A newly created policy row is inert until a tenant chooses. Kept as a
#: constant so the opt-in surface and the migration agree out loud.
DEFAULT_OFFER_STATUS = "paused"
POLICY_ACTIVE = "active"
POLICY_PAUSED = "paused"

#: Blocked reasons. ``None`` means "the plan has work to do".
REASON_OK = "ok"
BLOCKED_NO_ACTIVE_TENANTS = "no_active_tenants"
BLOCKED_NO_CHOSEN_POLICY = "policy_not_chosen_for_every_tenant"
BLOCKED_NO_POSITIVE_HORIZON = "non_positive_horizon"

PURGE_AUDIT_ACTION = "retention.partition_dropped"
PURGE_AUDIT_RESOURCE = "partition"

#: A retention choice IS a permission to delete, so it is audited like every
#: other governance write. Deliberately distinct from the purge action: whoever
#: reads the trail must be able to tell consent from deletion.
CHOOSE_AUDIT_ACTION = "retention.policy_chosen"
CHOOSE_AUDIT_RESOURCE = "retention_policy"

#: Bounds mirrored by the migration's CHECK on ``retention_policies``.
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650

#: The stores the HTTP door accepts a policy for: exactly the ones this module
#: can execute a DROP against. Kept as its own constant so the boundary refuses
#: a class it has no executor for — ``audit_logs`` above all, which §57 puts
#: under legal retention — instead of parking a policy row that governs nothing.
#: A row-level store (``messages``, ``webhook_events``, honoured by
#: ``app/workers/retention_worker._RETENTABLE``) is deliberately NOT here yet:
#: that worker has no permissioned write surface either, and a door for it would
#: have to say what ITS horizon binds, which is a per-tenant question this
#: partition-shaped read model does not answer.
CHOOSABLE_DATA_CLASSES: frozenset[str] = frozenset(PARTITIONED_DATA_CLASSES)

DROP_GATE_SQL = (
    "SELECT tenant_count, missing_policies, max_days "
    "FROM public.retention_drop_horizon(:data_class)"
)

#: Per-tenant visible read of that tenant's own rows. RLS is the guarantee that
#: this returns the bound tenant and nothing else; "chosen" is decided from it,
#: because a paused row is a withdrawn choice and must still be VISIBLE.
TENANT_POLICY_ROWS_SQL = """
SELECT data_class, retention_days, status, last_run_at, updated_at
  FROM retention_policies
 WHERE tenant_id = CAST(:tenant_id AS uuid)
 ORDER BY data_class
"""

#: The same rows, narrowed to the ones that authorise work today. Kept as its own
#: constant so the "chose" predicate is one readable thing and not a Python
#: re-implementation of SQL.
POLICY_READ_SQL = """
SELECT data_class, retention_days, status, last_run_at, updated_at
  FROM retention_policies
 WHERE tenant_id = CAST(:tenant_id AS uuid)
   AND status = 'active'
   AND retention_days > 0
 ORDER BY data_class
"""

#: One store's row for this tenant, for the ``before`` image of an audit record.
#: The visible read (no ``status`` filter): a change FROM a withdrawn choice is
#: still a change, and an audit row that only shows the new value cannot say so.
ONE_POLICY_SQL = """
SELECT data_class, retention_days, status, last_run_at, updated_at
  FROM retention_policies
 WHERE tenant_id = CAST(:tenant_id AS uuid)
   AND data_class = :data_class
"""

_NAME_RE = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True)
class DropGate:
    """What the tenants chose, as an aggregate. No tenant is identifiable in it."""

    tenant_count: int
    missing_policies: int
    max_days: int | None
    may_drop: bool
    reason: str


@dataclass(frozen=True)
class PurgePlan:
    """The months a purge may drop, or the single reason it may not."""

    droppable: tuple[date, ...]
    blocked_reason: str | None
    considered: int
    pinned_by_days: int | None


def evaluate_gate(
    *, tenant_count: int, missing_policies: int, max_days: int | None
) -> DropGate:
    """Pure consent rule, so it can be argued with (and tested) without a database.

    Every active tenant must have chosen — a missing row and a ``paused`` row
    both count as not chosen, which is why ``missing_policies`` is derived from
    the tenant list rather than from the policy rows.
    """
    if tenant_count <= 0:
        reason = BLOCKED_NO_ACTIVE_TENANTS
    elif missing_policies > 0:
        reason = BLOCKED_NO_CHOSEN_POLICY
    elif max_days is None or max_days <= 0:
        reason = BLOCKED_NO_POSITIVE_HORIZON
    else:
        reason = REASON_OK
    return DropGate(
        tenant_count=tenant_count,
        missing_policies=missing_policies,
        max_days=max_days,
        may_drop=reason == REASON_OK,
        reason=reason,
    )


def _floor_bound(now: date, floor_months: int) -> date:
    """First day of the oldest month that may still be kept: a month leaves only
    once it is entirely before this date."""
    total = now.year * 12 + (now.month - 1) - floor_months
    return date(total // 12, total % 12 + 1, 1)


def _upper_bound(month_start: date) -> date:
    return partitioning.month_bounds(month_start.year, month_start.month)[1]


def build_purge_plan(
    *,
    months: Sequence[date],
    gate: DropGate,
    now: date,
    floor_months: int = partitioning.PARTITION_DROP_FLOOR_MONTHS,
) -> PurgePlan:
    """Decide which whole months may leave. Pure: no session, no clock, no DDL.

    A month is droppable only when BOTH hold:

    1. it is entirely older than the LONGEST horizon any active tenant chose
       (the shared partition must satisfy the most conservative tenant);
    2. it is entirely before the current month minus ``floor_months`` — the
       legal floor, which no policy may undercut.

    ``months`` comes from the catalog's own ``FOR VALUES`` bounds and excludes
    the DEFAULT partition, so an unroutable row can never be dropped with a
    month it was not written into.
    """
    considered = len(months)
    if not gate.may_drop:
        return PurgePlan(
            droppable=(), blocked_reason=gate.reason, considered=considered, pinned_by_days=None
        )
    if gate.max_days is None:  # unreachable via evaluate_gate; guards the type only
        return PurgePlan(
            droppable=(),
            blocked_reason=BLOCKED_NO_POSITIVE_HORIZON,
            considered=considered,
            pinned_by_days=None,
        )
    horizon_cutoff = now - timedelta(days=gate.max_days)
    floor_cutoff = _floor_bound(now, floor_months)
    droppable = tuple(
        month
        for month in sorted(months)
        if _upper_bound(month) <= horizon_cutoff and _upper_bound(month) <= floor_cutoff
    )
    return PurgePlan(
        droppable=droppable,
        blocked_reason=None,
        considered=considered,
        pinned_by_days=gate.max_days,
    )


async def read_drop_gate(
    session: AsyncSession, data_class: str = AI_USAGE_DATA_CLASS
) -> DropGate:
    """Ask the database how many tenants chose, then apply the rule in Python.

    The aggregate runs as ``SECURITY DEFINER`` because FORCE RLS would otherwise
    hide every other tenant's policy from this very session — and it returns
    counts only, so no tenant's choice is exposed to another. If its owner is
    ever a role that is NOT RLS-exempt, it sees zero policy rows, every tenant
    looks un-chosen, and nothing is dropped: the failure mode is a silent no-op,
    never a silent delete.
    """
    row = (await session.execute(text(DROP_GATE_SQL), {"data_class": data_class})).one()
    tenant_count, missing, max_days = int(row[0]), int(row[1]), row[2]
    return evaluate_gate(
        tenant_count=tenant_count,
        missing_policies=missing,
        max_days=None if max_days is None else int(max_days),
    )


async def policy_position(session: AsyncSession, tenant_id) -> list[dict[str, Any]]:
    """The per-tenant answer to "what is my retention policy, and what does it
    allow?" — visible, because a policy nobody can read is not a choice.
    """
    rows = (
        await session.execute(text(TENANT_POLICY_ROWS_SQL), {"tenant_id": str(tenant_id)})
    ).all()
    by_class = {row[0]: row for row in rows}
    # "Chose" is defined once, in SQL, and not re-derived in Python.
    chosen_classes = {
        row[0]
        for row in (
            await session.execute(text(POLICY_READ_SQL), {"tenant_id": str(tenant_id)})
        ).all()
    }
    gate = await read_drop_gate(session)
    out: list[dict[str, Any]] = []
    for data_class in sorted(PARTITIONED_DATA_CLASSES):
        row = by_class.get(data_class)
        chosen = data_class in chosen_classes
        out.append(
            {
                "data_class": data_class,
                "table": PARTITIONED_DATA_CLASSES[data_class],
                "chosen": chosen,
                "status": row[2] if row is not None else None,
                "retention_days": row[1] if row is not None else None,
                "last_run_at": row[3].isoformat() if row is not None and row[3] else None,
                "offered_default_days": DEFAULT_RETENTION_DAYS.get(data_class),
                "legal_floor_months": partitioning.PARTITION_DROP_FLOOR_MONTHS,
                "shared_gate_reason": gate.reason,
                "shared_gate_blocks_me": gate.reason == BLOCKED_NO_CHOSEN_POLICY,
            }
        )
    return out


async def read_policy(
    session: AsyncSession, tenant_id, data_class: str
) -> dict[str, Any] | None:
    """This tenant's own row for one store, chosen or not.

    Only what an audit record needs to say what it replaced: a governance write
    whose ``before`` image is missing cannot be read back as a history of
    consent. One row, one tenant, RLS-bound — no cross-tenant read here.
    """
    row = (
        await session.execute(
            text(ONE_POLICY_SQL),
            {"tenant_id": str(tenant_id), "data_class": data_class},
        )
    ).first()
    if row is None:
        return None
    return {
        "data_class": row[0],
        "retention_days": row[1],
        "status": row[2],
        "last_run_at": row[3].isoformat() if row[3] else None,
    }


async def choose_policy(
    session: AsyncSession,
    tenant_id,
    data_class: str,
    *,
    retention_days: int,
    enabled: bool = True,
) -> dict[str, Any]:
    """The ONLY WRITER of a policy row in this module: one tenant's explicit
    opt-in (``enabled=True``) or opt-out (``enabled=False``, which parks the
    policy without forgetting the horizon it was given).

    It is a single upsert keyed on ``(tenant_id, data_class)`` — the unique index
    ``f7a2c9d4e8b1`` adds — so a tenant has exactly one answer per store, and
    "the policy" is never two contradicting rows. ``retention_policies`` is
    FORCE RLS with a ``WITH CHECK`` guard, so this writes only for the tenant
    whose GUC the caller already bound; a call for someone else's tenant raises
    rather than silently succeeding.
    """
    if not MIN_RETENTION_DAYS <= retention_days <= MAX_RETENTION_DAYS:
        raise ValueError(
            f"retention_days must be between {MIN_RETENTION_DAYS} and "
            f"{MAX_RETENTION_DAYS}; {retention_days} would either delete "
            "everything or nothing"
        )
    if data_class not in DEFAULT_RETENTION_DAYS and data_class not in PARTITIONED_DATA_CLASSES:
        logger.info("retention.policy.unknown_data_class %s (still recorded)", data_class)
    await session.execute(
        text(
            "INSERT INTO retention_policies "
            "(id, tenant_id, data_class, retention_days, status, created_at, updated_at) "
            "VALUES (gen_random_uuid(), CAST(:tenant_id AS uuid), :data_class, "
            ":retention_days, :status, now(), now()) "
            "ON CONFLICT (tenant_id, data_class) DO UPDATE SET "
            "retention_days = EXCLUDED.retention_days, "
            "status = EXCLUDED.status, updated_at = now()"
        ),
        {
            "tenant_id": str(tenant_id),
            "data_class": data_class,
            "retention_days": retention_days,
            "status": POLICY_ACTIVE if enabled else POLICY_PAUSED,
        },
    )
    return {
        "data_class": data_class,
        "retention_days": retention_days,
        "status": POLICY_ACTIVE if enabled else POLICY_PAUSED,
        "chosen": enabled,
    }


async def _partition_row_count(session: AsyncSession, name: str) -> int:
    """How much data is about to leave, for the audit record. The name is the
    parent's own child from the catalog, re-validated as a plain identifier
    because an identifier cannot be bound as a parameter.
    """
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"not a partition name: {name!r}")
    # An identifier cannot be bound as a parameter, so the shape is validated
    # above and `name` is derived from the catalog's own child list, never from a
    # policy row or a request.
    return int(
        (await session.execute(text(f"SELECT count(*) FROM public.{name}"))).scalar_one()
    )


async def purge_expired_partitions(session: AsyncSession, tenant_id) -> dict[str, Any]:
    """Run the destructive half, if and only if the tenants authorised it.

    Ordered deliberately: read the gate, read the catalog, decide, and only then
    touch DDL — so a run that is going to do nothing does nothing, without
    needing the database to refuse it. The database refuses anyway
    (``partitioning_purge_month`` re-checks the floor AND the same consent
    aggregate), because the plan is Python and the sharp edge is not.
    """
    parent = PARTITIONED_DATA_CLASSES[AI_USAGE_DATA_CLASS]
    gate = await read_drop_gate(session, AI_USAGE_DATA_CLASS)
    months = await partitioning.list_partition_months(session, parent)
    plan = build_purge_plan(months=months, gate=gate, now=datetime.now(UTC).date())
    if plan.blocked_reason:
        logger.info(
            "retention.purge.blocked tenant=%s reason=%s months=%d",
            tenant_id,
            plan.blocked_reason,
            plan.considered,
        )
        return {
            "purged": [],
            "skipped_reason": plan.blocked_reason,
            "considered": plan.considered,
            "pinned_by_days": None,
        }

    purged: list[str] = []
    for month in plan.droppable:
        name = partitioning.partition_name(parent, month)
        rows = await _partition_row_count(session, name)
        dropped = await partitioning.purge_month(session, parent, month)
        if dropped is None:  # another worker won the race for this month
            continue
        purged.append(dropped)
        await write_audit_row(
            session,
            tenant_id,
            None,
            PURGE_AUDIT_ACTION,
            PURGE_AUDIT_RESOURCE,
            dropped,
            before={"month": month.isoformat(), "rows": rows, "partition": dropped},
            after={
                "dropped": dropped,
                "rows": rows,
                "pinned_by_days": plan.pinned_by_days,
                "consent": "every_active_tenant_chose",
            },
        )
    if purged:
        logger.warning(
            "retention.purge tenant=%s dropped=%s horizon_days=%s",
            tenant_id,
            purged,
            plan.pinned_by_days,
        )
    return {
        "purged": purged,
        "skipped_reason": None,
        "considered": plan.considered,
        "pinned_by_days": plan.pinned_by_days,
    }
