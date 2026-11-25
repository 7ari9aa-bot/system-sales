"""The two settings tables carry the canonical ``tenant_isolation`` policy.

``fe2026112501`` and ``fe2026112504`` created their tables through raw SQL and named the policy
after the table (``setting_change_requests_isolation``, ``setting_migration_log_tenant_isolation``).
Neither table has an ORM model, so ``scripts/provision.py`` — which sweeps ``Base.metadata`` — never
sees them, and the schema-wide gate (``tests/security/test_schema_wide_rls_policies.py``) requires
exactly the canonical ``tenant_isolation`` policy and nothing beside it: policies are permissive
and OR together, so a second one opens the table.

``setting_change_requests`` also had no ``WITH CHECK``, which let an INSERT write a row for any
tenant; the canonical policy checks the written row too.

Revision ID: fe2026112506
Revises: fe2026112505
Create Date: 2026-11-25 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112506"
down_revision: str | None = "fe2026112505"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# table -> the non-canonical policy name its creating migration left behind
_LEGACY = {
    "setting_change_requests": "setting_change_requests_isolation",
    "setting_migration_log": "setting_migration_log_tenant_isolation",
}


def upgrade() -> None:
    for table, legacy in _LEGACY.items():
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {legacy} ON public.{table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON public.{table}
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD})"""
        )


def downgrade() -> None:
    # NO policy and NO FORCE, but RLS stays ENABLED: turning tenant isolation off is not a
    # rollback anyone wants, and a table with RLS on and no policy denies every non-owner read.
    for table in _LEGACY:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
