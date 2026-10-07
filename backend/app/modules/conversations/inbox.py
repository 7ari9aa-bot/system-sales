"""§137 — ``InboxQuery``: the inbox READ MODEL.

Spec §137 ("CROSS-MODULE READ LAYER") keeps ``No cross-module repository
access`` and allows one thing instead: a Read/Query Layer that answers a
cross-module list. Its worked example is exactly this surface —

    Inbox: Conversation + Customer + Last Message + Assignment
    not via  ConversationRepository -> CustomerRepository
    but via  InboxQuery   (or a read model)

Before this file existed the inbox had no such seam. ``GET /conversations``
was served by ``ConversationService.list_inbox``, which imported
``CustomerService`` to batch in the customer columns and then bolted
``customer_name``/``customer_phone`` onto ORM ``Conversation`` instances — the
repository-to-repository shape §137 names as the wrong one, performed by the
write service. The last-message preview and the SLA clock were not answered at
all: the browser made a second request to ``GET /sla/risk`` and joined the two
client-side, which cannot page, cannot filter "My Inbox"/"Unassigned" in SQL,
and re-joins on every poll. (``frontend/src/lib/queries.ts`` records that
state in its §99 comment.)

WHY A QUERY AND NOT A PROJECTION TABLE. §137 offers "or a read model" and its
Consistency paragraph assumes a projection LAGS ("لا نفترض أن كل read model
immediately consistent"), which then obliges the same paragraph to carve out an
"authoritative read" for read-after-write. This design takes the first option
and gets the second for free: it reads the live rows in one statement, so
``mark_read`` zeroing a counter is visible on the next page with no updater, no
backfill, and no drift window to reconcile. The counter it projects
(``conversations.unread_count``) is already moved inside the same transaction
as the message insert that earns it (``ConversationService.append_message``),
which is the outbox discipline of ``app/core/events/outbox.py`` — mark and fact
commit together — applied to a standing column instead of an event row. A
materialized inbox table would have had to be kept as consistent as that, plus
a backfill, for no read it cannot already do.

WHAT ONE PAGE COSTS: ONE statement, at any page size (§110 "No N+1",
"No unbounded queries"). The preview and the SLA clock arrive as
``LEFT JOIN LATERAL ... LIMIT 1`` — index-backed by
``ix_messages_tenant_conversation_created`` and, for SLA, by the index this
migration adds — so neither degenerates into a per-row lookup. Filters, sort
and the keyset cursor are SQL predicates, never Python passes over a fetched
page. See ``tests/test_inbox_read_model.py``, which counts the statements.

HOW IT STAYS TENANT-SAFE. Like ``customers/timeline.py``, it reads another
domain's columns with parameter-bound SQL instead of importing that domain's
mapped classes, and every table it touches is filtered twice over: the explicit
``tenant_id`` predicate below, and the FORCE-RLS ``tenant_isolation`` policy on
the ``app.tenant_id`` GUC the request bound. That is also why one statement
beats batching here — RLS applies to each table reference inside the statement,
including the joined ones, so a batched "fetch the ids then ask the other
module" hop has strictly less protection than this has. No new table is
introduced, so no new RLS surface is either.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidCursorError

# How much of the last message a list row carries. Truncated in SQL, at the
# place the row is read, so a 4 kB reply cannot ride the inbox page (§110 "No
# huge payloads").
INBOX_PREVIEW_CHARS = 160

# §46: the inbox clock is the FIRST-RESPONSE SLA. A resolution SLA is a
# different question and a different list.
_INBOX_SLA_KIND = "first_response"


class InboxQuery:
    """The §137 read side of the staff inbox. Read-only: it never writes.

    ``add``/``flush`` are not merely un-called here — the module imports no
    models it could mutate and issues a single ``SELECT``.
    """

    #: Hard ceiling on one page, independent of what a caller asks for.
    MAX_LIMIT = 200

    @staticmethod
    async def page(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        status: str | None = None,
        assignee_user_id: UUID | None = None,
        unassigned: bool = False,
        channel: str | None = None,
        customer_id: UUID | None = None,
        limit: int = 50,
        before_at: datetime | None = None,
        before_id: UUID | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """One page of the inbox: conversation, customer, last message, assignment, SLA.

        Pagination is keyset on the page's own sort — ``(last_message_at, id)``
        newest first, NULLS LAST — so a concurrent insert cannot shift a row
        across the page boundary the way OFFSET does. ``before_at``/``before_id``
        come from the cursor the caller got back; pass ``limit + 1`` rows' worth
        if the caller needs to know whether a next page exists (this method
        returns whatever the statement matched, it does not slice).

        ``unassigned`` answers §99's "Unassigned" view; it takes precedence over
        ``assignee_user_id``, because a request that says both has asked for
        rows owned by nobody, and no row can satisfy both predicates at once.
        """
        fetch = min(max(int(limit), 1), InboxQuery.MAX_LIMIT) + 1
        where = ["c.tenant_id = :tenant_id"]
        params: dict[str, object] = {"tenant_id": str(tenant_id), "limit": fetch}

        if status:
            where.append("c.status = :status")
            params["status"] = status
        if channel:
            where.append("c.channel = :channel")
            params["channel"] = channel
        if customer_id is not None:
            where.append("c.customer_id = :customer_id")
            params["customer_id"] = str(customer_id)
        if unassigned:
            where.append("c.assignee_user_id IS NULL")
        elif assignee_user_id is not None:
            where.append("c.assignee_user_id = :assignee_user_id")
            params["assignee_user_id"] = str(assignee_user_id)
        if before_id is not None:
            # The sort is `last_message_at DESC NULLS LAST, id DESC`, so "after
            # the cursor row" has two shapes: still inside the dated rows (a
            # row-constructor compare) or already in the never-messaged tail
            # (every NULL sorts below every date). A plain `<` on the tuple
            # would drop the whole tail on the first cursor, because anything
            # compared to NULL is NULL — which is how a keyset list silently
            # loses its last page. And once the cursor is ITSELF a tail row
            # (`before_at` NULL), the tail must narrow by id, or every page
            # after that one returns the same rows forever.
            where.append(
                "("
                "  (c.last_message_at IS NOT NULL"
                "   AND (c.last_message_at, c.id) <"
                "       (CAST(:before_at AS timestamptz), CAST(:before_id AS uuid)))"
                "  OR ("
                "     c.last_message_at IS NULL"
                "     AND (CAST(:before_at AS timestamptz) IS NOT NULL"
                "          OR c.id < CAST(:before_id AS uuid))"
                "  )"
                ")"
            )
            # `before_at` binds as a datetime, NOT an ISO string: the CAST tells
            # Postgres the parameter is timestamptz, and asyncpg then demands a
            # datetime for that slot (its uuid codec accepts a string, which is
            # why the ids below stay strings). Passing text here would raise at
            # the second page instead of the first, i.e. only in production.
            params["before_at"] = before_at
            params["before_id"] = str(before_id)

        sql = text(
            f"""
            SELECT
                c.id,
                c.status,
                c.channel,
                c.customer_id,
                c.assignee_user_id,
                c.workspace_id,
                c.created_at,
                c.last_message_at,
                c.last_customer_message_at,
                c.messaging_policy_state,
                c.unread_count,
                cust.name  AS customer_name,
                cust.phone AS customer_phone,
                CASE WHEN lm.deleted THEN NULL
                     ELSE left(lm.body, {INBOX_PREVIEW_CHARS}) END AS last_message_preview,
                lm.content_type AS last_message_content_type,
                lm.direction    AS last_message_direction,
                lm.sender_type  AS last_message_sender_type,
                lm.created_at   AS last_message_created_at,
                sla.kind        AS sla_kind,
                sla.status      AS sla_status,
                sla.deadline_at AS sla_deadline_at
              FROM conversations c
              LEFT JOIN customers cust
                ON cust.id = c.customer_id
               AND cust.tenant_id = c.tenant_id
              LEFT JOIN LATERAL (
                    SELECT m.body, m.content_type, m.direction, m.sender_type,
                           m.created_at, m.deleted
                      FROM messages m
                     WHERE m.tenant_id = c.tenant_id
                       AND m.conversation_id = c.id
                     ORDER BY m.created_at DESC, m.id DESC
                     LIMIT 1
              ) lm ON TRUE
              LEFT JOIN LATERAL (
                    SELECT se.kind, se.status, se.deadline_at
                      FROM sla_events se
                     WHERE se.tenant_id = c.tenant_id
                       AND se.conversation_id = c.id
                       AND se.kind = :sla_kind
                     ORDER BY se.created_at DESC, se.id DESC
                     LIMIT 1
              ) sla ON TRUE
             WHERE {" AND ".join(where)}
             ORDER BY c.last_message_at DESC NULLS LAST, c.id DESC
             LIMIT :limit
            """
        )
        params["sla_kind"] = _INBOX_SLA_KIND

        rows = (await session.execute(sql, params)).all()
        reference = now or datetime.now(UTC)
        return [InboxQuery._to_item(row, reference=reference) for row in rows]

    @staticmethod
    def _to_item(row: Any, *, reference: datetime) -> dict[str, Any]:
        """One SQL row -> one inbox row. Formatting only; nothing is decided here.

        ``sla_minutes_remaining`` is the only computed value, and it is the
        minutes between two numbers already in the row — the same derivation
        ``operations/router.py::sla_risk`` makes, so both surfaces tell the
        staff the same thing about the same clock.
        """
        deadline_at = row.sla_deadline_at
        minutes_remaining: int | None = None
        if deadline_at is not None:
            # DateTime(timezone=True) yields aware rows; the guard is for a
            # naive value reaching us from a test double, not from Postgres.
            if deadline_at.tzinfo is None:
                deadline_at = deadline_at.replace(tzinfo=UTC)
            minutes_remaining = int((deadline_at - reference).total_seconds() // 60)

        return {
            "id": str(row.id),
            "status": row.status,
            "channel": row.channel,
            "customer_id": str(row.customer_id) if row.customer_id else None,
            "customer_name": row.customer_name,
            "customer_phone": row.customer_phone,
            "assignee_user_id": str(row.assignee_user_id) if row.assignee_user_id else None,
            "workspace_id": str(row.workspace_id) if row.workspace_id else None,
            "created_at": _iso(row.created_at),
            "last_message_at": _iso(row.last_message_at),
            "last_customer_message_at": _iso(row.last_customer_message_at),
            "messaging_policy_state": row.messaging_policy_state,
            "unread_count": int(row.unread_count or 0),
            "last_message_preview": row.last_message_preview,
            "last_message_content_type": row.last_message_content_type,
            "last_message_direction": row.last_message_direction,
            "last_message_sender_type": row.last_message_sender_type,
            "last_message_created_at": _iso(row.last_message_created_at),
            "sla_kind": row.sla_kind,
            "sla_status": row.sla_status,
            "sla_deadline_at": _iso(deadline_at),
            "sla_minutes_remaining": minutes_remaining,
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# ------------------------------------------------------------- keyset cursor ---

# The page sorts ``last_message_at DESC NULLS LAST``, and that column is
# nullable: a conversation opened before its first message lands in the tail
# (``ConversationService.get_or_create`` creates the row, ``append_message``
# stamps the instant afterwards). ``app.core.pagination.encode_cursor`` cannot
# carry a NULL instant — its ``created_at`` is a required ISO string — and
# substituting a sentinel would be wrong twice over: a dated cursor makes
# ``page`` re-include every dated row that sorts ABOVE the cursor, which is the
# infinite-page loop a keyset exists to prevent. So the inbox cursor carries
# ``at: null`` explicitly, and ``page`` narrows the tail by id only when it
# reads one.
#
# Decoding also accepts the ``created_at`` shape ``/conversations`` already
# issued: an in-flight cursor across a deploy then pages once from a shifted
# boundary instead of failing with a 400 that the client cannot distinguish
# from a corrupt token.


def encode_keyset(at: datetime | None, row_id: UUID | str) -> str:
    """Opaque, URL-safe position for a NULLable sort key."""
    payload = json.dumps(
        {"at": at.isoformat() if at else None, "id": str(row_id)},
        separators=(",", ":"),
        sort_keys=True,
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_keyset(cursor: str) -> tuple[datetime | None, UUID]:
    """``(instant | None, id)`` from :func:`encode_keyset`.

    Raises :class:`app.core.errors.InvalidCursorError` for a corrupt cursor —
    the same 4xx contract every other list gives — rather than swallowing it: a
    silently ignored cursor reads to a client four pages deep as "start over",
    which looks like a bug in the list rather than in its token.
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        parsed = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        raw_at = parsed["at"] if "at" in parsed else parsed.get("created_at")
        row_id = UUID(str(parsed["id"]))
        instant = None if raw_at in (None, "") else datetime.fromisoformat(str(raw_at))
    except (binascii.Error, UnicodeDecodeError, KeyError, TypeError, ValueError) as exc:
        raise InvalidCursorError(details={"cursor": cursor[:128]}) from exc
    return instant, row_id
