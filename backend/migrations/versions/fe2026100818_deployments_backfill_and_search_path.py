"""Activate deployments for current published versions + pin function search_path.

Revision ID: fe2026100818
Revises: fe2026100817
Create Date: 2026-10-10 12:00:00.000000

Two halves, one purpose — a published version must actually RUN:

1. DEPLOYMENT BACKFILL. fe2026100811 gave every active agent a published v1
   snapshot, and the publish endpoint keeps minting newer ones, but nothing
   ever wrote `agent_deployments`: production carried 22 published versions
   and ZERO deployment rows, so every run took the runtime's documented
   `fallback:no_deployment` branch and executed the agent's MUTABLE settings —
   the exact scenario the immutable-version platform exists to prevent. This
   backfill activates, at 100% stable / 0% canary, the CURRENT (highest-
   numbered) published version of every active agent that has no deployment
   row, mirroring the column semantics of fe2026100808's model exactly:
   `stable_version_id` = the current published version, `candidate_version_id`
   = NULL, `canary_percent` = 0, `status` = 'active'.

   Scope deliberately mirrors fe2026100811's version backfill: ACTIVE agents
   only (`agents.is_active`) — the runtime's loader refuses an inactive agent,
   so a deployment for one would be dead weight; agents with only DRAFT
   versions get nothing, because there is no published snapshot to pin. An
   agent that already has a deployment row — any status, including
   `rolled_back` — is left entirely alone: this migration activates stores the
   deployment machinery never reached, it does not second-guess a canary or a
   rollback a human or the evaluation service put in place.

   Idempotent by construction: the guarded `INSERT ... SELECT ... WHERE NOT
   EXISTS` matches nothing on a second run, and the table's
   `uq_agent_deployments_tenant_agent` unique constraint is named as the
   conflict target as a hard backstop.

   The plain INSERT is safe despite fe2026100810's FORCE RLS because the
   migration connection runs as a BYPASSRLS role (postgres on Supabase,
   verified live 2026-10-10); FORCE binds owners, not BYPASSRLS roles. The
   tenant_isolation policy itself is untouched — app-role writes still go
   through `app.tenant_id` as before.

2. SEARCH_PATH PIN. Supabase's `function_search_path_mutable` lint flags
   `agent_versions_published_immutability()` (fe2026100811): its body relies
   on the session's search_path, so a compromised `SET search_path` before an
   UPDATE on `agent_versions` could redirect the unqualified names it touches.
   The trigger body references no relations — only TG_OP/OLD/NEW — so pinning
   `search_path = public` is purely defensive; the function's shape is
   preserved byte-for-byte. Forward-safe both ways: on a fresh database the
   function is created by fe2026100811 before this runs, and on an existing
   database the ALTER is a no-op re-pin.
"""

from collections.abc import Sequence

from alembic import op


revision: str = "fe2026100818"
down_revision: str | None = "fe2026100817"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One statement per execute(): asyncpg's extended protocol accepts exactly
    # one command per call, so a multi-statement string aborts
    # `alembic upgrade head` — the first step of every deploy.
    op.execute(
        """
        INSERT INTO agent_deployments
            (tenant_id, agent_id, stable_version_id, canary_percent, status)
        SELECT cur.tenant_id, cur.agent_id, cur.version_id, 0, 'active'
        FROM (
            SELECT DISTINCT ON (v.tenant_id, v.agent_id)
                v.id AS version_id, v.tenant_id, v.agent_id
            FROM agent_versions v
            JOIN agents a ON a.id = v.agent_id AND a.tenant_id = v.tenant_id
            WHERE v.status = 'published'
              AND a.is_active
            ORDER BY v.tenant_id, v.agent_id, v.version DESC
        ) AS cur
        WHERE NOT EXISTS (
            SELECT 1 FROM agent_deployments d
            WHERE d.tenant_id = cur.tenant_id AND d.agent_id = cur.agent_id
        )
        ON CONFLICT (tenant_id, agent_id) DO NOTHING
        """
    )
    op.execute(
        "ALTER FUNCTION public.agent_versions_published_immutability() "
        "SET search_path = public"
    )


def downgrade() -> None:
    op.execute(
        "ALTER FUNCTION public.agent_versions_published_immutability() "
        "RESET search_path"
    )
    # The backfilled deployment rows are data, not schema — left in place,
    # exactly like fe2026100811's version backfill. Deleting them here would
    # un-pin every store the backfill just made reproducible.
