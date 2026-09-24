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

* a tenant whose horizon is SHORTER than the others is served by the row-level
  purge in this module (:func:`purge_row_store`, run by the ``retention.run``
  sweep), which deletes only its own rows and can therefore be as aggressive as
  that tenant wishes;
* a month may be dropped only when EVERY active tenant has chosen a policy for
  that store, actively, not by silence — so the LONGEST chosen horizon pins the
  month, and one tenant that never chose (or chose ``paused``) pins it for
  everyone. The result is reported, never swallowed.

Both halves read THE SAME ``retention_policies`` rows and apply THE SAME consent
rule (:func:`evaluate_gate`, reached by :func:`read_drop_gate` for a shared month
and :func:`evaluate_row_gate` for one tenant's rows), so there is one answer to
"did anyone authorise deleting this?" and one vocabulary for refusing
(``BLOCKED_NO_ACTIVE_TENANTS`` / ``BLOCKED_NO_CHOSEN_POLICY`` /
``BLOCKED_NO_POSITIVE_HORIZON``). That matters most for the row stores, because
they are the PII-bearing ones: ``messages`` is conversation content,
``attachments`` is the media that content points at (so a message purge that
misses it orphans every object its cascade deleted), ``webhook_events`` is raw
inbound ingress, and ``leads`` is phone/email captured before a customer exists.
§52 makes retention per data class and per tenant, so a horizon a merchant
cannot state is a store whose retention is not a policy at all — which is why
:data:`ROW_LEVEL_DATA_CLASSES` is the single allowlist of deletable tables and
``app/workers/retention_worker.py`` reads it instead of keeping its own.

Nothing here creates a policy row on a tenant's behalf. ``DEFAULT_RETENTION_DAYS``
is the value the opt-in surface offers; the database default for a policy row is
``paused`` (``f7a2c9d4e8b1``), so an un-answered question cannot delete data.
``choose_policy`` is the ONLY writer in this module, and it is an explicit
opt-in/opt-out call.

Boundaries kept on purpose
--------------------------
* no cross-module imports: ``retention_policies`` belongs to ``privacy`` and
  ``audit_logs`` to ``platform``, and ``tests/test_module_boundaries.py``
  ratchets that count at 94 — so the policy rows, the tenant-liveness probe and
  the row deletes are bound raw SQL, and the audit append goes through
  ``app.core.audit`` (a core capability, not a domain).
* the cross-tenant tally is NOT computed here. ``retention_policies`` is FORCE
  RLS: this session may see one tenant's rows, and a worker that "knew" every
  tenant's choices by reading the table would be a tenant-isolation bug. It
  calls ``public.retention_drop_horizon(text)``, a SECURITY DEFINER aggregate
  that returns COUNTS and the longest horizon only — never another tenant's
  policy, its data class, or its existence by name. A row purge does not need
  it: its consent is exactly one tenant's, read from its own visible row.
* no timezone is resolved here (``analytics/timekit.py`` owns that). Partition
  boundaries are UTC months by construction, so this module plans in ``date``
  values and never in local days; a row purge compares ``timestamptz`` to an
  aware ``datetime`` and converts neither.
* this module is not a read model. ``analytics/service.py`` stays read-only;
  cold-data removal is DDL or a bounded DELETE and lives beside the scheduler
  that runs it.

What is deliberately NOT enforced
---------------------------------
* a per-tenant floor on a row purge: ``retention_days`` bounds (1..3650) exist in
  the migration, but :data:`~app.core.partitioning.PARTITION_DROP_FLOOR_MONTHS`
  guards a SHARED month, which is a different question. A tenant shortening its
  own conversation history below thirteen months is a per-tenant choice §52
  grants; the floor protects data other tenants still hold in the same relation.
* any store not named by :data:`PARTITIONED_DATA_CLASSES` or
  :data:`ROW_LEVEL_DATA_CLASSES`. Stores that hold personal data and are NOT
  purged are not left to inference: each one is named in
  :data:`REFUSED_DATA_CLASSES` with the section that keeps it and the residual
  risk, so "absent from the allowlist" no longer conflates "not yet wired" with
  "decided never". ``audit_logs`` must never be hard-deleted (§57 legal
  retention), ``event_log`` is §152's replay source, and stores that cannot be
  partitioned are explained in ``app/core/partitioning.py``; the ones a row
  purge may reach are listed in :data:`ROW_LEVEL_DATA_CLASSES`, each with the
  age column and the rows ANOTHER rule keeps.

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
from app.core.storage import get_storage

logger = logging.getLogger(__name__)

#: The store this module may purge partition-wise. Matches
#: ``app.core.partitioning.PARTITIONED_TABLES`` one-for-one.
PARTITIONED_DATA_CLASSES: Mapping[str, str] = {"ai_usage": "public.ai_usage"}

AI_USAGE_DATA_CLASS = "ai_usage"


@dataclass(frozen=True)
class MediaChild:
    """A child table whose rows leave with the parent's, and whose objects must
    leave with them.

    ``attachments.message_id`` is ``ON DELETE CASCADE`` (``49303e2e2dd0``), so a
    parent DELETE silently takes media rows with it. Silently is the problem: the
    row is the only thing that knows which bucket key holds a customer's voice
    note, so a purge that lets the cascade fire removes the pointer and keeps the
    PII forever, with no row left to retry from. Declaring the child here makes
    the sweep delete those rows FIRST, keys in hand.
    """

    table: str
    key_column: str
    link_column: str


@dataclass(frozen=True)
class RowStore:
    """One store a row purge may execute against, and the rows it must not touch.

    ``table``/``ts_column`` are SQL identifiers, so they are interpolated into the
    DELETE from this static spec and never from a policy row or a request (an
    identifier cannot be bound as a parameter). ``keep`` is a predicate the DELETE
    always carries: retention ages data out, another rule may still need it, and a
    purge that forgot which would quietly retire evidence the §24 dead letter or
    the §130 reconciler is still working on.

    ``media_key_column`` says the rows of THIS store name an object in the bucket
    (``attachments``): the purge therefore gathers the batch by key and deletes it
    by explicit id list, so the objects it releases are exactly the rows it
    removed. ``media_child`` says the opposite direction — my rows carry someone
    else's objects away by cascade. A store may set one, both, or neither; a store
    that sets neither is deleted by the plain LIMIT-shaped statement.
    """

    data_class: str
    table: str
    ts_column: str
    keep: str | None = None
    keep_reason: str | None = None
    media_key_column: str | None = None
    media_child: MediaChild | None = None


#: The stores purged by ROW rather than by month — and the single allowlist of
#: tables a chosen retention policy may ever cause a ``DELETE`` against.
#: ``app/workers/retention_worker.py`` reads this instead of keeping its own copy,
#: because two lists of "which tables may be destroyed" is how the wrong one
#: drifts. Only a store whose PII-map row (docs/PII_DATA_MAP.md, §131) says the
#: retention worker deletes it belongs here; the stores the map marks "legal
#: retention" / "keep" — orders, payments, audit_logs, customers — never will, and
#: :data:`REFUSED_DATA_CLASSES` says so store by store rather than by silence.
#:
#: DECLARATION ORDER IS A CONTRACT: the sweep visits these stores in this order
#: (``retention_worker._SWEEP_ORDER``), and a child whose rows leave with a
#: parent's cascade is declared BEFORE that parent so the parent never wins.
ROW_LEVEL_DATA_CLASSES: Mapping[str, RowStore] = {
    "attachments": RowStore(
        data_class="attachments",
        table="attachments",
        ts_column="created_at",
        keep=(
            "scan_status NOT IN ('pending', 'downloading') "
            "AND processing_status NOT IN ('pending', 'processing') "
            "AND COALESCE(transcription_status, 'ready') NOT IN "
            "('pending', 'processing')"
        ),
        keep_reason=(
            "§33-35: a media row still being fetched, screened or transcribed is "
            "an in-flight pipeline, not cold data — the same reasoning §130 "
            "applies to an unreconciled message"
        ),
        media_key_column="storage_key",
    ),
    "messages": RowStore(
        data_class="messages",
        table="messages",
        ts_column="created_at",
        keep="status NOT IN ('sending', 'unknown')",
        keep_reason=(
            "§130: a message whose provider outcome is 'sending'/'unknown' is "
            "still being reconciled — its outcome is evidence, not cold data"
        ),
        media_child=MediaChild(
            table="attachments", key_column="storage_key", link_column="message_id"
        ),
    ),
    "ai_usage": RowStore(
        data_class=AI_USAGE_DATA_CLASS,
        table="ai_usage",
        ts_column="created_at",
    ),
    "webhook_events": RowStore(
        data_class="webhook_events",
        table="webhook_events",
        ts_column="received_at",
        keep="processing_status IN ('processed', 'ignored', 'resolved')",
        keep_reason=(
            "§24: a 'dead' ingress row awaits human hands (replay / ignore / "
            "resolve); only the terminal close-outs are allowed to age out"
        ),
    ),
    "leads": RowStore(
        data_class="leads",
        table="leads",
        ts_column="created_at",
    ),
}

#: Stores §52 asks about that this module will NEVER execute a policy for, and the
#: rule that keeps them. The list exists because "unreachable" and "deliberately
#: kept" look identical from the outside, and a compliance claim that cannot tell
#: them apart is an assertion, not a check. Each reason names a spec section, and
#: ``tests/test_media_and_lead_retention.py`` reads ``docs/PII_DATA_MAP.md`` as a
#: contract: a store the map hands to the retention worker must appear here or in
#: :data:`ROW_LEVEL_DATA_CLASSES`, never in neither.
REFUSED_DATA_CLASSES: Mapping[str, str] = {
    "audit_logs": (
        "§57/§66 legal retention: 'never hard-delete'. A purge that could empty "
        "the audit trail would break the very requirement §57 says archival must "
        "not touch, and it is not on the partition maintenance allowlist either "
        "(app/core/partitioning.py), so no path reaches it"
    ),
    "event_log": (
        "§152: the replay source. Emptying it makes an outbox replay impossible, "
        "which is an availability bug paid for by a retention win. docs/"
        "PII_DATA_MAP.md still says 'retention worker' for EventLog — the map "
        "predates §152 and is the stale half of that pair"
    ),
    "customers": (
        "§143/§172 Customer 360: tombstone (deleted_at/by/reason) is the deletion "
        "act, not a DELETE. docs/PII_DATA_MAP.md: 'life of tenant'"
    ),
    "orders": (
        "§54/§57 financial legal retention: an immutable snapshot is the invoice's "
        "source of truth; 'never hard-delete' (docs/PII_DATA_MAP.md)"
    ),
    "payments": (
        "§57 financial legal retention, same rule as orders — a refund state is a "
        "record that money moved"
    ),
    "memories": (
        "§158 provenance + §172 propagation: a memory's own ``expires_at`` is its "
        "horizon and recall honours it; erasure goes through "
        "``DeletionService.propagate_customer_deletion`` (hard DELETE), not a "
        "per-tenant sweep. OPEN RESIDUAL: a row past ``expires_at`` keeps its "
        "content text until then, which is what app/modules/ai/knowledge.py:197 "
        "documents as 'stored for audit'"
    ),
    "agent_runs": (
        "BLOCKED, NOT DECIDED: agent_runs.input/output hold run content, so a "
        "horizon is owed — but approval_requests.run_id is ON DELETE CASCADE "
        "(ai/models.py:312), so purging a run would also erase the §135 proof of "
        "who authorised which action, which §57 forbids. A nullable-FK/SET NULL "
        "migration is the prerequisite; until then this store is unpurged and "
        "says why here rather than in a TODO"
    ),
    "knowledge_items": (
        "§39-40 business knowledge, not customer PII: superseded on re-index, "
        "tenant-scoped delete (docs/PII_DATA_MAP.md 'until superseded')"
    ),
}

#: docs/PII_DATA_MAP.md: "ai_usage | tokens/cost — NO content | metrics |
#: 13 months | retention worker" and "messages | conversation content | PII |
#: policy (default 365d) | ... | retention worker". 13 months is offered as 390
#: days; the month-exact floor (13 calendar months) is separately enforced in
#: Python and in the purge function, so the floor is never looser than this
#: offer. A store the map gives no number for gets NO offered default here rather
#: than an invented one — ``webhook_events`` is that store, so the door pre-fills
#: nothing and the merchant must state the horizon.
DEFAULT_RETENTION_DAYS: Mapping[str, int] = {AI_USAGE_DATA_CLASS: 390, "messages": 365}
DEFAULT_RETENTION_SOURCE = (
    "docs/PII_DATA_MAP.md — ai_usage: 13 months (=390 days, the partition drop "
    "floor); messages: policy (default 365d). Both rows say 'retention worker' "
    "deletes them (spec §52 per-data-class retention, §57 hot->archive->delete). "
    "webhook_events has no documented duration and is therefore offered none."
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

#: A data_class that is in NEITHER allowlist: this module has no executor for it,
#: so the request is refused rather than parked as a policy that governs nothing.
#: Keeps the worker's old ``"unknown_data_class"`` wording so a log or a summary
#: that already reads it does not change meaning mid-flight.
REASON_NOT_A_ROW_STORE = "unknown_data_class"

#: The media half of a purge result when no media was involved. Spelled once so a
#: refusal and an executed purge return the SAME keys and a caller never has to
#: guess which shape it got.
_EMPTY_MEDIA: Mapping[str, Any] = {
    "media_rows_deleted": 0,
    "media_objects_released": 0,
    "media_objects_failed": [],
}

PURGE_AUDIT_ACTION = "retention.partition_dropped"
PURGE_AUDIT_RESOURCE = "partition"

#: A row purge destroys conversation bodies, so it leaves the same kind of trail
#: as a DROP — under its OWN action, because whoever reads the audit log must be
#: able to tell "a shared month left with everyone's consent" from "one tenant's
#: rows left, one sweep at a time".
ROW_PURGE_AUDIT_ACTION = "retention.rows_purged"
ROW_PURGE_AUDIT_RESOURCE = "retention_row_store"

#: Rows deleted per statement, and how many statements one tenant may spend in
#: one run. Together they bound the work: a sweep must not hold a hot table's
#: transaction open for minutes, so a backlogged store is the next run's problem.
#: The horizon is an absolute timestamp, so stopping early is idempotent — the
#: rows left are exactly the rows the next sweep would have taken anyway.
ROW_PURGE_BATCH_SIZE = 500
ROW_PURGE_MAX_BATCHES = 20

#: A retention choice IS a permission to delete, so it is audited like every
#: other governance write. Deliberately distinct from the purge action: whoever
#: reads the trail must be able to tell consent from deletion.
CHOOSE_AUDIT_ACTION = "retention.policy_chosen"
CHOOSE_AUDIT_RESOURCE = "retention_policy"

#: Bounds mirrored by the migration's CHECK on ``retention_policies``.
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650

#: The stores the HTTP door accepts a policy for: exactly the ones an executor in
#: this module can carry out — a DROP for :data:`PARTITIONED_DATA_CLASSES`, the
#: gated row purge for :data:`ROW_LEVEL_DATA_CLASSES`. Kept as its own constant so
#: the boundary refuses a class it has no executor for — ``audit_logs`` above all,
#: which §57 puts under legal retention — instead of parking a policy row that
#: governs nothing, and so the executor and the door can never disagree about
#: which questions are answerable. That disagreement was the bug this set closes:
#: the row sweep honoured ``retention_policies`` for stores no surface could write
#: a policy for, which made a merchant's conversation-history horizon unaskable.
CHOOSABLE_DATA_CLASSES: frozenset[str] = frozenset(PARTITIONED_DATA_CLASSES) | frozenset(
    ROW_LEVEL_DATA_CLASSES
)

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

#: Is this tenant one of the tenants retention may execute for at all? The same
#: predicate the SECURITY DEFINER aggregate uses for its ``tenant_count``
#: (``tenants.is_active``, ``f7a2c9d4e8b1``), stated once more in Python because a
#: row purge has no cross-tenant aggregate to ask — and a suspended tenant's
#: choices are not consent from anyone.
TENANT_IS_ACTIVE_SQL = "SELECT is_active FROM tenants WHERE id = CAST(:tenant_id AS uuid)"

#: The one row that authorises a row purge, read WITHOUT a status or horizon
#: filter: the gate must see what the row actually says so it can name the reason
#: ("not chosen" vs "a horizon that would delete everything"), instead of
#: flattening a legacy ``retention_days = 0`` into "nobody answered".
ROW_POLICY_SQL = """
SELECT retention_days, status
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


def evaluate_row_gate(
    *, tenant_active: bool, retention_days: int | None, status: str | None
) -> DropGate:
    """The SAME consent rule, in the shape one tenant's rows need.

    Not a second policy language: this adapts the inputs and delegates to
    :func:`evaluate_gate`, so a refusal means the same thing for a ``DETACH`` and
    for a ``DELETE``, and a third reason cannot appear in one path and not the
    other. A row purge's "every active tenant" is exactly one tenant — its own —
    which is precisely why a row purge can honour a short horizon a shared month
    never could.
    """
    answered = tenant_active and status == POLICY_ACTIVE
    return evaluate_gate(
        tenant_count=1 if tenant_active else 0,
        missing_policies=0 if answered else 1,
        max_days=retention_days if answered else None,
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

    Every choosable store is listed, partitioned or row-level, because the door
    that can write the policy and the read model that explains it must cover the
    same set. The two gates are reported separately and mean different things:
    ``shared_gate_reason`` is about a MONTH this tenant shares with others (None
    where no month is involved — another tenant's silence must never be blamed on
    a store of the tenant's own rows), ``row_gate_reason`` is about this tenant's
    rows and is derived from the policy row already in hand, so reading one's own
    position asks the database no new questions.
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
    for data_class in sorted(CHOOSABLE_DATA_CLASSES):
        row = by_class.get(data_class)
        chosen = data_class in chosen_classes
        partitioned = data_class in PARTITIONED_DATA_CLASSES
        spec = ROW_LEVEL_DATA_CLASSES.get(data_class)
        entry: dict[str, Any] = {
            "data_class": data_class,
            "table": PARTITIONED_DATA_CLASSES[data_class] if partitioned else spec.table,
            "purge_paths": (["row"] if spec is not None else []) + (
                ["partition"] if partitioned else []
            ),
            "chosen": chosen,
            "status": row[2] if row is not None else None,
            "retention_days": row[1] if row is not None else None,
            "last_run_at": row[3].isoformat() if row is not None and row[3] else None,
            "offered_default_days": DEFAULT_RETENTION_DAYS.get(data_class),
            "row_gate_reason": evaluate_row_gate(
                # A tenant reading its own position is an active tenant until the
                # gate says otherwise; the liveness probe belongs to the purge.
                tenant_active=True,
                retention_days=row[1] if row is not None else None,
                status=row[2] if row is not None else None,
            ).reason
            if spec is not None
            else None,
        }
        if spec is not None and spec.keep is not None:
            entry["keep_predicate"] = spec.keep
            entry["keep_reason"] = spec.keep_reason
        if spec is not None and (spec.media_key_column or spec.media_child):
            # A store whose rows name an object in the bucket: the merchant is
            # entitled to know that the horizon governs the BYTES, not only the
            # row, and which rows the sweep clears on the way to another store.
            entry["media"] = {
                "key_column": spec.media_key_column,
                "cascades_from_child": (
                    None
                    if spec.media_child is None
                    else f"{spec.media_child.table}.{spec.media_child.link_column}"
                ),
            }
        if partitioned:
            entry["legal_floor_months"] = partitioning.PARTITION_DROP_FLOOR_MONTHS
            entry["shared_gate_reason"] = gate.reason
            entry["shared_gate_blocks_me"] = gate.reason == BLOCKED_NO_CHOSEN_POLICY
        else:
            entry["legal_floor_months"] = None
            entry["shared_gate_reason"] = None
            entry["shared_gate_blocks_me"] = False
        out.append(entry)
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
    if data_class not in CHOOSABLE_DATA_CLASSES:
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


# ---------------------------------------------------------------------------
# The other half of the ladder: a ROW purge, for the stores that cannot be
# partitioned (``messages`` is FK-parented to conversations, ``webhook_events``
# resolves its tenant itself — see ``app/core/partitioning.py``), and for a
# tenant whose horizon is shorter than the shared month can allow.
# ---------------------------------------------------------------------------


def _check_identifiers(spec: RowStore) -> None:
    """Re-validate every SQL identifier this store can interpolate.

    An identifier cannot be bound as a parameter, so the shapes come from a
    static spec and are checked here anyway: a media child added later with a
    typo or a dotted name must fail before it reaches the driver.
    """
    names = [spec.table, spec.ts_column]
    if spec.media_key_column:
        names.append(spec.media_key_column)
    if spec.media_child:
        names.extend(
            [spec.media_child.table, spec.media_child.key_column, spec.media_child.link_column]
        )
    for name in names:
        if not _NAME_RE.fullmatch(name):
            raise ValueError(f"not a deletable row store: {spec.data_class!r} ({name!r})")


def _doomed_ids_sql(spec: RowStore) -> str:
    """The batch this purge is allowed to take: one tenant's rows, past the
    horizon THAT TENANT chose, minus the rows another rule keeps, bounded, in a
    total order.

    ``id`` is in the ORDER BY because a timestamp alone is not a total order: two
    rows sharing an instant could swap sides of the LIMIT between two evaluations,
    and a media purge evaluates this twice on purpose (once to gather keys, once
    to delete). The docstring has always claimed the batch is deterministic; this
    is what makes the claim true.
    """
    keep = f" AND ({spec.keep})" if spec.keep else ""
    return (
        f"SELECT id FROM {spec.table} "
        f"WHERE tenant_id = :tenant_id AND {spec.ts_column} < :cutoff{keep} "
        f"ORDER BY {spec.ts_column}, id LIMIT {ROW_PURGE_BATCH_SIZE}"
    )


def _row_purge_sql(spec: RowStore) -> str:
    """The one DELETE shape this module issues against a content store.

    ``table``, ``ts_column`` and the keep predicate are SQL fragments, which
    cannot be bound as parameters, so they are interpolated from
    :data:`ROW_LEVEL_DATA_CLASSES` — a static spec, never a policy row, never a
    request — and re-validated as plain identifiers. Three properties are baked in
    here and are not the caller's to remember:

    * ``LIMIT`` — a sweep deletes a batch, not a backlog;
    * an explicit ``tenant_id`` predicate — belt-and-suspenders beside RLS, and
      load-bearing for ``webhook_events``, whose tenant is resolved at ingress;
    * the store's keep predicate — rows another rule still needs (§24 dead letter,
      §130 unreconciled outcome) are not this rule's to retire.

    ``ORDER BY`` the age column makes the batch deterministic, so a run that stops
    early resumes where it stopped instead of skipping rows.

    A store that owns or cascades bucket media is not deleted this way: its keys
    have to be read before its rows go, so it goes by explicit id list instead
    (:func:`_media_gather_sql`, :func:`_media_delete_sql`).
    """
    _check_identifiers(spec)
    return f"DELETE FROM {spec.table} WHERE id IN ({_doomed_ids_sql(spec)})"


def _media_gather_sql(spec: RowStore) -> str:
    """``(id, storage_key)`` for the media rows this batch takes with it.

    Two shapes, one purpose. When the store IS the media table (``attachments``)
    the doomed set is its own rows past the horizon. When the store merely
    cascades a child (``messages`` -> ``attachments``) the doomed set is derived
    from that parent's own batch subquery, so a media row is only ever gathered
    because its parent is about to be deleted by the same cutoff.

    A NULL ``storage_key`` is kept in the SELF shape, not filtered out: it means
    the object was never written durably (S3 unconfigured, pass-through), and the
    ROW still has to age out. The caller drops NULL keys before releasing. In the
    CHILD shape a keyless row is filtered, because the parent's own cascade will
    take that row anyway and there is no object to lose track of.
    """
    _check_identifiers(spec)
    if spec.media_key_column:
        return (
            f"SELECT id, {spec.media_key_column} FROM {spec.table} "
            f"WHERE id IN ({_doomed_ids_sql(spec)})"
        )
    child = spec.media_child
    if child is None:  # pragma: no cover - the caller checks first
        raise ValueError(f"no media declared for {spec.data_class!r}")
    return (
        f"SELECT c.id, c.{child.key_column} FROM {child.table} c "
        f"WHERE c.{child.link_column} IN ({_doomed_ids_sql(spec)}) "
        f"AND c.tenant_id = :tenant_id AND c.{child.key_column} IS NOT NULL"
    )


def _media_delete_sql(child_table: str) -> str:
    """Delete exactly the ids whose keys were just read — never a re-evaluated
    predicate, which could reach a row this batch never gathered a key for.

    The cast is not decoration: the ids are bound as TEXT because that is what a
    list of ``str(uuid)`` adapts to, and Postgres will not compare ``uuid`` to
    ``text``. Every store here has a UUID primary key, so the cast is total.
    """
    if not _NAME_RE.fullmatch(child_table):
        raise ValueError(f"not a media table: {child_table!r}")
    return (
        f"DELETE FROM {child_table} "
        f"WHERE id = ANY(CAST(:ids AS uuid[])) AND tenant_id = :tenant_id"
    )


async def release_media_objects(keys: Sequence[str]) -> list[str]:
    """Remove the bucket objects behind purged media rows; return what stayed.

    A module-level function rather than an inline call for two reasons: the tests
    replace it with a spy (a purge test must not need a bucket), and it is the
    ONLY place this module touches object storage. It never raises — by the time
    it is called the rows are already deleted, so an exception would roll the
    purge back to a state where live rows point at objects nobody attempted to
    delete, which is worse than a reported leak.
    """
    pending = [k for k in keys if k]
    if not pending:
        return []
    try:
        return list(await get_storage().delete_objects(pending))
    except Exception as exc:  # a dead bucket is a reported leak, not a failed job
        logger.warning(
            "retention.media_release.unreachable keys=%d error=%s", len(pending), exc
        )
        return pending


async def purge_row_store(
    session: AsyncSession,
    tenant_id,
    data_class: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Delete one tenant's rows older than the horizon THAT TENANT chose.

    Same consent gate as a partition drop, same refusal vocabulary, and the same
    rule about what may supply a horizon: ``retention_policies``. There is no TTL
    in config and no default applied at delete time — :data:`DEFAULT_RETENTION_DAYS`
    is only what the door pre-fills for a merchant who answers. An absent,
    ``paused`` or non-positive policy is a refusal that deletes nothing, and a
    store outside :data:`ROW_LEVEL_DATA_CLASSES` is refused before it is looked at
    (no statement of any kind), because guessing a table name is how an
    unrecoverable data loss starts.

    The policy row is read here, at delete time, rather than passed in: this is
    the authoritative copy, so a sweep cannot act on a stale enumeration of it.
    ``session`` must already be bound to ``tenant_id`` — the caller owns the
    transaction, and the tenant predicate rides along for the tables RLS alone
    would not police.

    Returns ``{"data_class", "deleted", "skipped_reason", "horizon_days",
    "cutoff", "truncated", "media_rows_deleted", "media_objects_released",
    "media_objects_failed"}``; ``cutoff`` is the isoformat string an audit reader
    can compare, ``truncated`` says the batch cap stopped this run so the rest of
    the backlog belongs to the next, and the ``media_*`` keys say what left the
    bucket and WHICH KEYS DID NOT — a media purge that cannot report the objects it
    failed to remove has simply moved the leak somewhere nobody reads.
    """
    spec = ROW_LEVEL_DATA_CLASSES.get(data_class)
    if spec is None:
        return {
            "data_class": data_class,
            "deleted": 0,
            "skipped_reason": REASON_NOT_A_ROW_STORE,
            "horizon_days": None,
            "cutoff": None,
            "truncated": False,
            **_EMPTY_MEDIA,
        }

    tenant_active = bool(
        (
            await session.execute(
                text(TENANT_IS_ACTIVE_SQL), {"tenant_id": str(tenant_id)}
            )
        ).scalar()
    )
    policy = (
        await session.execute(
            text(ROW_POLICY_SQL),
            {"tenant_id": str(tenant_id), "data_class": data_class},
        )
    ).first()
    gate = evaluate_row_gate(
        tenant_active=tenant_active,
        retention_days=policy[0] if policy is not None else None,
        status=policy[1] if policy is not None else None,
    )
    if not gate.may_drop:
        logger.info(
            "retention.row_purge.blocked tenant=%s data_class=%s reason=%s",
            tenant_id,
            data_class,
            gate.reason,
        )
        return {
            "data_class": data_class,
            "deleted": 0,
            "skipped_reason": gate.reason,
            "horizon_days": gate.max_days,
            "cutoff": None,
            "truncated": False,
            **_EMPTY_MEDIA,
        }

    moment = now or datetime.now(UTC)
    horizon = gate.max_days if gate.max_days is not None else 0
    cutoff = moment - timedelta(days=horizon)
    cutoff_iso = cutoff.isoformat()
    params = {"tenant_id": tenant_id, "cutoff": cutoff}

    # A store whose own rows name the objects it carries (``attachments``) is
    # deleted BY THOSE IDS and nothing else: the key must be in hand before the
    # pointer to it goes. A store that merely cascades such rows (``messages``)
    # keeps its own LIMIT-shaped DELETE untouched — the child is cleared first, so
    # the cascade has nothing left to take silently.
    media_self = spec.media_key_column is not None
    gather_sql = _media_gather_sql(spec) if (media_self or spec.media_child) else None
    child_table = spec.table if media_self else (
        spec.media_child.table if spec.media_child else None
    )
    media_delete_sql = _media_delete_sql(child_table) if child_table else None
    purge_sql = None if media_self else _row_purge_sql(spec)

    deleted = 0
    media_rows_deleted = 0
    keys: list[str] = []
    batches = 0
    truncated = True
    while batches < ROW_PURGE_MAX_BATCHES:
        store_batch = 0
        if gather_sql is not None:
            rows = (await session.execute(text(gather_sql), params)).all()
            ids = [str(row[0]) for row in rows]
            keys.extend(str(row[1]) for row in rows if row[1] is not None)
            if ids:
                taken = (
                    await session.execute(
                        text(media_delete_sql), {"ids": ids, "tenant_id": tenant_id}
                    )
                ).rowcount or 0
                if media_self:
                    store_batch = taken
                    deleted += taken
                else:
                    media_rows_deleted += taken
        if not media_self:
            store_batch = (await session.execute(text(purge_sql), params)).rowcount or 0
            deleted += store_batch
        batches += 1
        if store_batch < ROW_PURGE_BATCH_SIZE:
            truncated = False
            break

    failed: list[str] = []
    if keys:
        # AFTER the rows are gone, deliberately: see :func:`release_media_objects`.
        failed = list(await release_media_objects(keys) or [])
    released = len(keys) - len(failed)

    if deleted or media_rows_deleted or failed:
        # A destructive act with no trail is the §66 hole; a daily sweep that
        # audited "nothing happened" every day is noise nobody reads.
        await write_audit_row(
            session,
            tenant_id,
            None,
            ROW_PURGE_AUDIT_ACTION,
            ROW_PURGE_AUDIT_RESOURCE,
            data_class,
            before={
                "status": gate.reason,
                "horizon_days": horizon,
                "keep_predicate": spec.keep,
            },
            after={
                "data_class": data_class,
                "table": spec.table,
                "deleted": deleted,
                "batches": batches,
                "horizon_days": horizon,
                "cutoff": cutoff_iso,
                "truncated": truncated,
                "consent": "tenant_chosen_policy",
                "media_rows_deleted": media_rows_deleted,
                "media_objects_gathered": len(keys),
                "media_objects_released": released,
                "media_objects_failed": failed,
            },
        )
        logger.warning(
            "retention.row_purge tenant=%s data_class=%s deleted=%d horizon_days=%d truncated=%s",
            tenant_id,
            data_class,
            deleted,
            horizon,
            truncated,
        )
    if failed:
        logger.error(
            "retention.media_leak tenant=%s data_class=%s keys=%d",
            tenant_id,
            data_class,
            len(failed),
        )
    return {
        "data_class": data_class,
        "deleted": deleted,
        "skipped_reason": None,
        "horizon_days": horizon,
        "cutoff": cutoff_iso,
        "truncated": truncated,
        "media_rows_deleted": media_rows_deleted,
        "media_objects_released": released,
        "media_objects_failed": failed,
    }
