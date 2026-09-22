"""tenant_restore_jobs RLS hardening (§164 review M7)

Revision ID: c166dd166dd1
Revises: c156cc156cc1
Create Date: 2026-09-22

``tenant_restore_jobs`` was created (``f9b0c1d2e3f4:331-407``) AFTER the
FORCE-RLS sweep (``b2c3d4e5f6a7``), so it received only ENABLE RLS and a
policy built on bare ``current_setting('app.tenant_id')::uuid`` — which
RAISES when the GUC is unset instead of matching zero rows, and which the
table-owner app role bypasses without FORCE. The restore service's own
docstring claims FORCE RLS makes cross-tenant access impossible; this
migration makes that claim true, mirroring ``c136aa136aa1``.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c166dd166dd1"
down_revision: str | None = "c156cc156cc1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Canonical tenant guard: NULLIF keeps an UNSET app.tenant_id from casting ''
# to uuid, so an unbound session matches ZERO rows instead of raising.
_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    # NOTE: one statement per op.execute() — migrations run through asyncpg,
    # whose extended-query protocol rejects multiple commands per execute.
    op.execute("ALTER TABLE public.tenant_restore_jobs FORCE ROW LEVEL SECURITY")
    # Replace the phase-9 legacy policy (bare current_setting, no WITH CHECK,
    # no NULLIF guard) with the canonical tenant_isolation policy.
    op.execute(
        "DROP POLICY IF EXISTS tenant_restore_jobs_tenant_isolation "
        "ON public.tenant_restore_jobs"
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'tenant_restore_jobs' AND policyname = 'tenant_isolation'
            ) THEN
                CREATE POLICY tenant_isolation ON public.tenant_restore_jobs
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD});
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.tenant_restore_jobs")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'tenant_restore_jobs'
                  AND policyname = 'tenant_restore_jobs_tenant_isolation'
            ) THEN
                CREATE POLICY tenant_restore_jobs_tenant_isolation
                ON public.tenant_restore_jobs
                USING (tenant_id = current_setting('app.tenant_id')::uuid);
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE public.tenant_restore_jobs NO FORCE ROW LEVEL SECURITY")
