"""Grant sales_app USAGE on extensions and add infra RLS policies.

Revision ID: fe2026100802
Revises: fe2026100801
Create Date: 2026-10-08 10:20:00.000000
"""
from collections.abc import Sequence

from alembic import op


revision: str = "fe2026100802"
down_revision: str | None = "fe2026100801"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Grant USAGE on extensions to sales_app (guarded)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'extensions') THEN
                    GRANT USAGE ON SCHEMA extensions TO sales_app;
                END IF;
            END IF;
        END $$;
        """
    )

    # 2. Add sales_app_all policies on infra tables (guarded)
    op.execute(
        """
        DO $$
        DECLARE
            tbl TEXT;
            tbls TEXT[] := ARRAY['outbox_events', 'idempotency_keys', 'processed_events'];
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                FOREACH tbl IN ARRAY tbls LOOP
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = tbl) THEN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_policies
                            WHERE schemaname = 'public' AND tablename = tbl AND policyname = 'sales_app_all'
                        ) THEN
                            EXECUTE format(
                                'CREATE POLICY sales_app_all ON public.%I FOR ALL TO sales_app USING (true) WITH CHECK (true)',
                                tbl
                            );
                        END IF;
                    END IF;
                END LOOP;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            tbl TEXT;
            tbls TEXT[] := ARRAY['outbox_events', 'idempotency_keys', 'processed_events'];
        BEGIN
            FOREACH tbl IN ARRAY tbls LOOP
                EXECUTE format('DROP POLICY IF EXISTS sales_app_all ON public.%I', tbl);
            END LOOP;
        END $$;
        """
    )
