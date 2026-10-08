"""Agent platform hardening: infra RLS policies, vector extension schema, and performance indexes.
"""
from collections.abc import Sequence

from alembic import op


revision: str = "fe2026100801"
down_revision: str | None = "fd2026100502"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. System infrastructure tables: add explicit service_role_all & sales_app app_all policies
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
                    -- service_role policy (guarded)
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
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
                    -- sales_app policy (resolving P0-1: sales_app blocked by RLS on infra tables)
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_policies
                            WHERE schemaname = 'public' AND tablename = tbl AND policyname = 'app_all'
                        ) THEN
                            EXECUTE format(
                                'CREATE POLICY app_all ON public.%I FOR ALL TO sales_app USING (true) WITH CHECK (true)',
                                tbl
                            );
                        END IF;
                    END IF;
                END IF;
            END LOOP;
        END $$;
        """
    )

    # 2. Relocate vector extension out of public schema to extensions schema (resolving P0-2)
    op.execute(
        """
        DO $$
        BEGIN
            CREATE SCHEMA IF NOT EXISTS extensions;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'postgres') THEN
                GRANT USAGE ON SCHEMA extensions TO postgres;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                GRANT USAGE ON SCHEMA extensions TO sales_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
                GRANT USAGE ON SCHEMA extensions TO service_role;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                GRANT USAGE ON SCHEMA extensions TO authenticated;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                GRANT USAGE ON SCHEMA extensions TO anon;
            END IF;
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

    # 3. Seed ai:approve RBAC permission and grant to owner & manager (resolving P1-3)
    op.execute(
        """
        DO $$
        DECLARE
            perm_id UUID;
            r_id UUID;
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'permissions') THEN
                IF NOT EXISTS (SELECT 1 FROM public.permissions WHERE name = 'ai:approve') THEN
                    INSERT INTO public.permissions (id, module, action, name, description, created_at)
                    VALUES (gen_random_uuid(), 'ai', 'approve', 'ai:approve', 'Approve AI-driven agent actions and tool executions', now())
                    RETURNING id INTO perm_id;
                ELSE
                    SELECT id INTO perm_id FROM public.permissions WHERE name = 'ai:approve' LIMIT 1;
                END IF;

                IF perm_id IS NOT NULL AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'role_permissions') THEN
                    FOR r_id IN (SELECT id FROM public.roles WHERE name IN ('owner', 'manager')) LOOP
                        IF NOT EXISTS (SELECT 1 FROM public.role_permissions WHERE role_id = r_id AND permission_id = perm_id) THEN
                            INSERT INTO public.role_permissions (role_id, permission_id) VALUES (r_id, perm_id);
                        END IF;
                    END LOOP;
                END IF;
            END IF;
        END $$;
        """
    )

    # 4. Add hot-path performance indexes (isolated single statements for asyncpg)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_handovers_tenant_convo
            ON public.ai_handovers (tenant_id, conversation_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_agent_runs_tenant_agent_created
            ON public.agent_runs (tenant_id, agent_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_agent_tools_tenant_agent_active
            ON public.agent_tools (tenant_id, agent_id, is_active)
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'agent_profiles') THEN
                CREATE INDEX IF NOT EXISTS ix_agent_profiles_tenant_kind
                    ON public.agent_profiles (tenant_id, agent_kind);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agent_profiles_tenant_kind;")
    op.execute("DROP INDEX IF EXISTS ix_agent_tools_tenant_agent_active;")
    op.execute("DROP INDEX IF EXISTS ix_agent_runs_tenant_agent_created;")
    op.execute("DROP INDEX IF EXISTS ix_ai_handovers_tenant_convo;")

