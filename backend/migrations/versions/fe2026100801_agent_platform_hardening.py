"""Agent platform hardening: infra RLS policies, vector extension schema, and performance indexes.
"""
from collections.abc import Sequence

from alembic import op


revision: str = "fe2026100801"
down_revision: str | None = "fd2026100502"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. System infrastructure tables: add explicit service_role_all policy
    op.execute(
        """
        DO $$
        DECLARE
            tbl TEXT;
            tbls TEXT[] := ARRAY[
                'idempotency_keys',
                'outbox_events',
                'processed_events',
                'dr_policy',
                'restore_test_runs',
                'alembic_version'
            ];
        BEGIN
            FOREACH tbl IN ARRAY tbls LOOP
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = tbl) THEN
                    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tbl);
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_policies
                        WHERE schemaname = 'public' AND tablename = tbl AND policyname = 'service_role_all'
                    ) THEN
                        EXECUTE format(
                            'CREATE POLICY service_role_all ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',
                            tbl
                        );
                    END IF;
                END IF;
            END LOOP;
        END $$;
        """
    )

    # 2. Relocate vector extension out of public schema to extensions schema (Supabase best practice)
    op.execute(
        """
        DO $$
        BEGIN
            CREATE SCHEMA IF NOT EXISTS extensions;
            GRANT USAGE ON SCHEMA extensions TO postgres, anon, authenticated, service_role;
            IF EXISTS (
                SELECT 1 FROM pg_extension e
                JOIN pg_namespace n ON n.oid = e.extnamespace
                WHERE e.extname = 'vector' AND n.nspname = 'public'
            ) THEN
                ALTER EXTENSION vector SET SCHEMA extensions;
            END IF;
        END $$;
        """
    )

    # 3. Add hot-path performance indexes for agent runtime & handover queries
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_handovers_tenant_convo
            ON public.ai_handovers (tenant_id, conversation_id);
        CREATE INDEX IF NOT EXISTS ix_agent_runs_tenant_agent_created
            ON public.agent_runs (tenant_id, agent_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_agent_tools_tenant_agent_active
            ON public.agent_tools (tenant_id, agent_id, is_active);
        CREATE INDEX IF NOT EXISTS ix_agent_profiles_tenant_kind
            ON public.agent_profiles (tenant_id, agent_kind);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agent_profiles_tenant_kind;")
    op.execute("DROP INDEX IF EXISTS ix_agent_tools_tenant_agent_active;")
    op.execute("DROP INDEX IF EXISTS ix_agent_runs_tenant_agent_created;")
    op.execute("DROP INDEX IF EXISTS ix_ai_handovers_tenant_convo;")
