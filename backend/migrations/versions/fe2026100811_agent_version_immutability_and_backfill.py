"""Published agent versions: DB-level immutability + v1 backfill for existing agents.

Revision ID: fe2026100811
Revises: fe2026100810
Create Date: 2026-10-10 00:30:00.000000

Two halves, one purpose — the version rows must mean what they claim:

1. IMMUTABILITY. A published snapshot is the audit reference a run was served
   from; editing it in place would rewrite history (the same prompt with a
   different body). The trigger allows exactly one transition —
   published → archived — and refuses every other UPDATE of a published row
   and every DELETE of one. Draft rows stay editable.

2. BACKFILL. Every active agent that has no published version gets one (v1)
   snapshot of its current row. Without it, `approve_rollout` has no
   "previous published version" to pin as stable, and the canary machinery
   could not start for any pre-existing tenant. The runtime still serves the
   mutable agent row until a deployment actually exists — the backfill only
   creates the anchor, it does not flip any traffic.

   The plain INSERT is safe despite fe2026100810's FORCE RLS because the
   migration connection runs as a BYPASSRLS role (postgres on Supabase,
   verified live 2026-10-10); FORCE binds owners, not BYPASSRLS roles.
"""

from collections.abc import Sequence

from alembic import op


revision: str = "fe2026100811"
down_revision: str | None = "fe2026100810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION agent_versions_published_immutability()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status = 'published' THEN
                    RAISE EXCEPTION 'published agent versions are immutable'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                RETURN OLD;
            END IF;
            -- UPDATE: a published row may only flip to archived, with every
            -- snapshot column untouched.
            IF OLD.status = 'published' THEN
                IF NEW.status NOT IN ('published', 'archived')
                   OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                   OR NEW.agent_id IS DISTINCT FROM OLD.agent_id
                   OR NEW.version IS DISTINCT FROM OLD.version
                   OR NEW.system_prompt IS DISTINCT FROM OLD.system_prompt
                   OR NEW.model IS DISTINCT FROM OLD.model
                   OR NEW.temperature IS DISTINCT FROM OLD.temperature
                   OR NEW.max_output_tokens IS DISTINCT FROM OLD.max_output_tokens
                   OR NEW.run_limits IS DISTINCT FROM OLD.run_limits
                   OR NEW.tool_policy IS DISTINCT FROM OLD.tool_policy
                   OR NEW.published_at IS DISTINCT FROM OLD.published_at
                   OR NEW.published_by IS DISTINCT FROM OLD.published_by THEN
                    RAISE EXCEPTION 'published agent versions are immutable (archive-only)'
                        USING ERRCODE = 'restrict_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    # One statement per execute(): asyncpg's extended protocol accepts exactly
    # one command per call, so a "DROP ...; CREATE ..." pair aborts
    # `alembic upgrade head` — the first step of every deploy.
    op.execute(
        "DROP TRIGGER IF EXISTS agent_versions_published_immutability "
        "ON public.agent_versions"
    )
    op.execute(
        """
        CREATE TRIGGER agent_versions_published_immutability
            BEFORE UPDATE OR DELETE ON public.agent_versions
            FOR EACH ROW EXECUTE FUNCTION
                agent_versions_published_immutability();
        """
    )
    # v1 snapshots for every active agent that has none. COALESCE keeps the
    # NOT NULL JSONB columns satisfied for agent rows predating the defaults.
    op.execute(
        """
        INSERT INTO agent_versions (
            tenant_id, agent_id, version, system_prompt, model, temperature,
            max_output_tokens, run_limits, tool_policy, status, published_at
        )
        SELECT
            a.tenant_id, a.id, 1, a.system_prompt, a.model,
            COALESCE(a.temperature, 0.7), a.max_output_tokens,
            COALESCE(a.run_limits, '{}'::jsonb), '{}'::jsonb,
            'published', now()
        FROM agents a
        WHERE a.is_active
          AND NOT EXISTS (
              SELECT 1 FROM agent_versions v
              WHERE v.tenant_id = a.tenant_id AND v.agent_id = a.id
          )
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS agent_versions_published_immutability ON public.agent_versions")
    op.execute("DROP FUNCTION IF EXISTS agent_versions_published_immutability()")
    # The backfilled v1 snapshots are data, not schema — left in place.
