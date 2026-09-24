"""§135 — one PENDING approval per (tenant, conversation, action, payload_hash).

Revision ID: e6f7a8b9c0d1
Revises: f3b7d9c1a5e8
Create Date: 2026-09-28

The hole this closes
-------------------
``ApprovalService.request`` (``app/modules/ai/approvals.py``) dedupes an
existing PENDING approval with an UNLOCKED check-then-act: SELECT for a
PENDING row on (tenant_id, conversation_id, action, payload_hash, status =
'PENDING'), INSERT if none. Two simultaneous gate entries for one
conversation can each see no PENDING row and both INSERT — producing TWO
approval grants for one HIGH-risk action. ``decide`` and ``find_granted`` are
correctly serialised (``SELECT ... FOR UPDATE``, see ``d4e5f6a7b8c9`` and
``tests/gate/test_gate_approval_double_grant.py``); the CREATION side had no
rule at all, so a reviewer can be asked to approve the same action twice and
both grants can then be consumed by different executions. Consumption locking
cannot save this: two PENDING rows become two APPROVED rows, each legitimately
claimable once.

As with M5 (``c9f2a6b1d4e8``): a SELECT-then-INSERT guard cannot fix a race,
only the database can. This is a UNIQUE PARTIAL INDEX expressing exactly the
service's dedupe key, restricted to the state the service dedupes within.

Why PARTIAL (WHERE status = 'PENDING')
--------------------------------------
Decided rows are history: approve, reject, expire, then the next gate entry
must be able to park a *fresh* request for the same action again — the stale
flow of §135 depends on it. A full unique constraint would refuse the second
PENDING after the first was decided, turning the audit trail into a wall.

Why the conversation_id bucket is a COALESCE, not a bare column
---------------------------------------------------------------
``conversation_id`` is NULLABLE and the service compares it with ``==``,
which against ``None`` renders ``IS NULL`` — the service DOES dedupe the
no-conversation case. Postgres treats NULLs as DISTINCT in UNIQUE indexes
(the same limitation M5 documents and *accepts* for anonymous conversions),
so a bare ``conversation_id`` would silently fail to dedupe exactly those
rows. The key buckets NULL through the nil UUID, which no code path ever
generates as a real conversation id, so the bucket cannot collide with a
non-null conversation. ``payload_hash`` NULLs (pre-``a2b3c4d5e6f7`` legacy
rows) stay deliberately distinct on BOTH sides: the service's
``payload_hash = :fingerprint`` never matches NULL either — legacy pendings
fail closed, and the index mirrors the query rather than overreaching it.

Idempotency and transaction-safety
----------------------------------
``IF NOT EXISTS`` everywhere; no CONCURRENTLY (Alembic runs this inside one
transaction as the pre-deploy command); no GRANT/REVOKE, so no
``pg_roles`` guard needed (the ``sales_app``-may-not-exist constraint of
``a9b0c1d2e3f4`` only binds privilege statements). The collapse DELETE runs
first: on a database that already raced, ``CREATE UNIQUE INDEX`` without it
would abort the deploy. One statement per ``op.execute()`` — asyncpg's
extended-query protocol rejects multiple commands per call.

The exact index statement is pinned character-for-character by
``tests/test_approval_pending_dedupe_index.py`` against the service's compiled
dedupe SELECT, so index and query cannot drift.
"""
from __future__ import annotations

from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "f3b7d9c1a5e8"
branch_labels = None
depends_on = None

TABLE = "approval_requests"
INDEX_NAME = "uq_approvals_pending_dedupe"
#: Bucket for conversation_id IS NULL — the service dedupes those rows, and
#: NULLs are DISTINCT in a Postgres UNIQUE index, so the key must coalesce.
#: The nil UUID is never generated as a conversation id anywhere in this app.
NIL_UUID = "00000000-0000-0000-0000-000000000000"

_COLLAPSE_PENDING_SQL = f"""
DELETE FROM approval_requests a USING approval_requests b
WHERE a.id < b.id
  AND a.status = 'PENDING' AND b.status = 'PENDING'
  AND a.tenant_id = b.tenant_id
  AND a.action = b.action
  AND a.payload_hash = b.payload_hash
  AND coalesce(a.conversation_id, '{NIL_UUID}'::uuid)
      = coalesce(b.conversation_id, '{NIL_UUID}'::uuid)
"""

_CREATE_DEDUPE_INDEX_SQL = f"""
CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} ON {TABLE} (
    tenant_id,
    coalesce(conversation_id, '{NIL_UUID}'::uuid),
    action,
    payload_hash
)
WHERE status = 'PENDING'
"""


def upgrade() -> None:
    # Collapse pre-existing duplicate PENDING requests first (keep the newest
    # row per key — the one a re-entering gate would want to find anyway), or
    # the CREATE UNIQUE INDEX below aborts the deploy on the first database
    # that already raced. Same shape as c9f2a6b1d4e8's collapse-first.
    op.execute(_COLLAPSE_PENDING_SQL)
    op.execute(_CREATE_DEDUPE_INDEX_SQL)


def downgrade() -> None:
    """Drop only the rule. The collapsed duplicate rows are gone either way —
    like every dedupe migration here, a downgrade restores the ability to
    create duplicates, not the duplicates themselves.
    """
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
