"""§137 inbox read model: the two indexes its one statement depends on.

``conversations/inbox.py`` answers an inbox page in ONE statement, and two of
its shapes only stay one statement if the planner can reach them by index.
Without these, the same query is correct and slow, which is the failure mode a
read model is supposed to remove rather than relocate.

1. ``ix_conversations_tenant_assignee`` — the §99 "My Inbox" and "Unassigned"
   views are ``WHERE assignee_user_id = :me`` / ``IS NULL`` over the tenant's
   conversations. Neither existed as a pushdown before: ``/conversations`` had
   no assignee parameter at all and the browser filtered the rows it happened to
   load (``INBOX_CLIENT_VIEWS`` in ``frontend/src/lib/queries.ts``). The only
   index on the table that could serve a conversation list is
   ``ix_conversations_tenant_status_last`` (tenant, status, last_message_at),
   which cannot answer "mine" without a status filter, and not at all for
   "unassigned".

2. ``ix_sla_events_conversation_kind`` — the SLA clock arrives as
   ``LEFT JOIN LATERAL (SELECT ... FROM sla_events WHERE conversation_id = c.id
   AND kind = 'first_response' ORDER BY created_at DESC LIMIT 1)``, i.e. one
   top-of-index probe per row on the page. ``sla_events`` had
   (tenant_id), and (tenant_id, status, deadline_at) — the breach sweep's
   shape, the OTHER direction of the same question ("what is running", across
   every conversation). Neither can serve "this conversation's clock", so
   without this index the LATERAL degrades to a scan of the tenant's SLA rows
   once per row on the page: the N+1 the single statement was meant to avoid,
   smuggled back in as an inner loop. That index is also what
   ``operations/router.py::sla_risk`` was forced to work around by reading
   every running/breached event and joining it client-side.

Index-only, idempotent, and no new table — so no new RLS surface: nothing here
needs the FORCE RLS + tenant-GUC treatment that a new table would (see
``d5e6f7a8b9c0_scheduled_jobs_rls`` for that shape). Every statement stays
tenant-prefixed the way the queries that use them do.

``CREATE INDEX`` (not ``CONCURRENTLY``) because Alembic runs this migration
inside a transaction, which is the repo's existing convention for every index
here — the same trade ``b8c9d0e1f2a3`` records. It takes a brief write lock on
each table; at inbox scale that is the cheaper of the two wrong choices, and
releasing the transaction to go CONCURRENTLY would break the all-or-nothing
upgrade every sibling migration relies on.
"""
from __future__ import annotations

from alembic import op

revision: str = "f3b7d9c1a5e8"
down_revision: str | None = "a9b0c1d2e3f4"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # One statement per op.execute(): asyncpg's extended-query protocol rejects
    # multiple commands in a single execute().
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conversations_tenant_assignee
            ON conversations (tenant_id, assignee_user_id, last_message_at DESC NULLS LAST, id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_sla_events_conversation_kind
            ON sla_events (tenant_id, conversation_id, kind, created_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    """Drop only what this migration added.

    The two indexes are independent of any query correctness, so a rollback is
    a rollback: the read model still answers the right rows, just more slowly.
    """
    op.execute("DROP INDEX IF EXISTS ix_sla_events_conversation_kind")
    op.execute("DROP INDEX IF EXISTS ix_conversations_tenant_assignee")
