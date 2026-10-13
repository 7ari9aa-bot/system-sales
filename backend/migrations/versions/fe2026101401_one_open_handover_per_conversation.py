"""ai_handovers — at most ONE open handover per conversation.

Revision ID: fe2026101401
Revises: fe2026100816
Create Date: 2026-10-14 01:40:00.000000

Spec §37/§150: a conversation must not hold two open handovers. The service
(``app/modules/ai/handover.py``) already refuses to add a second one, but that
is a read-then-act check: two concurrent writers — a redelivered event and a
live turn, or two withhold paths in one run — can both pass it. The guarantee
belongs in the database, so this adds a PARTIAL unique index over the open
statuses only.

A resolved/closed handover does not occupy the slot: a conversation can be
handed over, resolved, and handed over again later, which is normal operation.

Pre-existing duplicates are collapsed BEFORE the index is created, keeping the
newest open row per conversation and resolving the older ones with an explicit
outcome — otherwise the CREATE would fail on a database that already carries the
bug this migration closes. Production has zero ``ai_handovers`` rows today, so
this is a belt, not a repair.

Runs as the alembic admin role (``postgres``, BYPASSRLS), which is what makes a
cross-tenant collapse possible at all: RLS is FORCED on this table for every
other role.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026101401"
down_revision: str | None = "fe2026100816"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPEN_STATUSES = "('pending', 'claimed')"

# One statement (asyncpg): keep the newest open row per conversation, resolve
# the rest with a truthful outcome so the queue does not silently lose them.
_COLLAPSE_DUPLICATES = f"""
UPDATE ai_handovers AS h
SET status = 'resolved',
    outcome = COALESCE(h.outcome, 'other'),
    outcome_note = COALESCE(
        h.outcome_note,
        'closed by migration fe2026101401: duplicate open handover for this conversation'
    ),
    resolved_at = COALESCE(h.resolved_at, now())
WHERE h.status IN {_OPEN_STATUSES}
  AND h.id <> (
      SELECT keep.id
      FROM ai_handovers AS keep
      WHERE keep.conversation_id = h.conversation_id
        AND keep.status IN {_OPEN_STATUSES}
      ORDER BY keep.created_at DESC, keep.id DESC
      LIMIT 1
  )
"""

# Partial: only open rows compete for the slot.
_CREATE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_handovers_open_conversation "
    "ON ai_handovers (conversation_id) "
    f"WHERE status IN {_OPEN_STATUSES}"
)

_DROP_INDEX = "DROP INDEX IF EXISTS uq_handovers_open_conversation"


def upgrade() -> None:
    op.execute(_COLLAPSE_DUPLICATES)
    op.execute(_CREATE_INDEX)


def downgrade() -> None:
    op.execute(_DROP_INDEX)
