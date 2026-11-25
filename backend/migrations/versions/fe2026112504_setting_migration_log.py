"""Add setting_migration_log table for the config migration framework.

Per-tenant idempotent log of applied config migrations (key renames, value
transforms). The highest ``migration_id`` applied is the tenant's effective
settings ``schema_version`` — analogous to ``alembic_version`` but scoped
per tenant.

Revision ID: fe2026112504
Revises: fe2026112503
Create Date: 2026-11-25 11:55:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112504"
down_revision: str | None = "fe2026112503"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.setting_migration_log (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
            migration_id  VARCHAR(127) NOT NULL,
            description   VARCHAR(255) NOT NULL DEFAULT '',
            applied_by    UUID REFERENCES public.users(id) ON DELETE SET NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_setting_migration_log_tenant_migration
                UNIQUE (tenant_id, migration_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_setting_migration_log_tenant "
        "ON public.setting_migration_log (tenant_id, created_at)"
    )
    # RLS: tenant-isolated, same pattern as every other tenant table.
    op.execute("ALTER TABLE public.setting_migration_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.setting_migration_log FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY setting_migration_log_tenant_isolation
            ON public.setting_migration_log
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.setting_migration_log")
