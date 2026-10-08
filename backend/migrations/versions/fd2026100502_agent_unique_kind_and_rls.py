"""Add uq_agents_tenant_kind unique constraint, enable RLS on system tables, and sync agent_profiles.
"""
from collections.abc import Sequence

from alembic import op


revision: str = "fd2026100502"
down_revision: str | None = "fd2026100501"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enforce unique (tenant_id, kind) on agents if not already present
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_agents_tenant_kind') THEN
                ALTER TABLE public.agents ADD CONSTRAINT uq_agents_tenant_kind UNIQUE (tenant_id, kind);
            END IF;
        END $$;
        """
    )

    # 2. Sync legacy agent_profiles and install sync trigger (each statement isolated for asyncpg)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agent_profiles_agent_kind_check') THEN
                ALTER TABLE public.agent_profiles DROP CONSTRAINT agent_profiles_agent_kind_check;
            END IF;

            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'agent_profiles') THEN
                UPDATE agent_profiles SET agent_kind = 'customer' WHERE agent_kind = 'support';
                UPDATE agent_profiles SET agent_kind = 'sales_intelligence' WHERE agent_kind = 'analytics';
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION sync_agent_profile_kind()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $func$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'agent_profiles') THEN
                IF TG_OP = 'INSERT' THEN
                    EXECUTE 'INSERT INTO agent_profiles (id, tenant_id, agent_id, agent_kind, is_enabled, created_at, updated_at) '
                         || 'VALUES ($1, $2, $3, $4, $5, now(), now()) '
                         || 'ON CONFLICT (agent_id) DO UPDATE '
                         || 'SET agent_kind = EXCLUDED.agent_kind, is_enabled = EXCLUDED.is_enabled, updated_at = now()'
                    USING gen_random_uuid(), NEW.tenant_id, NEW.id, NEW.kind, NEW.is_active;
                ELSIF TG_OP = 'UPDATE' THEN
                    EXECUTE 'UPDATE agent_profiles SET agent_kind = $1, is_enabled = $2, updated_at = now() WHERE agent_id = $3'
                    USING NEW.kind, NEW.is_active, NEW.id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $func$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            REVOKE EXECUTE ON FUNCTION public.sync_agent_profile_kind() FROM public;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE EXECUTE ON FUNCTION public.sync_agent_profile_kind() FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE EXECUTE ON FUNCTION public.sync_agent_profile_kind() FROM authenticated;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'agent_profiles') THEN
                DROP TRIGGER IF EXISTS trg_sync_agent_profile_kind ON agents;
                CREATE TRIGGER trg_sync_agent_profile_kind
                AFTER INSERT OR UPDATE OF kind, is_active ON agents
                FOR EACH ROW
                EXECUTE FUNCTION sync_agent_profile_kind();
            END IF;
        END $$;
        """
    )

    # 3. Enable RLS on public reference and system tables to satisfy security audit
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'permissions') THEN
                ALTER TABLE public.permissions ENABLE ROW LEVEL SECURITY;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'roles') THEN
                ALTER TABLE public.roles ENABLE ROW LEVEL SECURITY;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'role_permissions') THEN
                ALTER TABLE public.role_permissions ENABLE ROW LEVEL SECURITY;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'plans') THEN
                ALTER TABLE public.plans ENABLE ROW LEVEL SECURITY;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'idempotency_keys') THEN
                ALTER TABLE public.idempotency_keys ENABLE ROW LEVEL SECURITY;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'outbox_events') THEN
                ALTER TABLE public.outbox_events ENABLE ROW LEVEL SECURITY;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'processed_events') THEN
                ALTER TABLE public.processed_events ENABLE ROW LEVEL SECURITY;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'dr_policy') THEN
                ALTER TABLE public.dr_policy ENABLE ROW LEVEL SECURITY;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'restore_test_runs') THEN
                ALTER TABLE public.restore_test_runs ENABLE ROW LEVEL SECURITY;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_sync_agent_profile_kind ON agents;")
    op.execute("DROP FUNCTION IF EXISTS sync_agent_profile_kind();")
    op.drop_constraint("uq_agents_tenant_kind", "agents", type_="unique")
