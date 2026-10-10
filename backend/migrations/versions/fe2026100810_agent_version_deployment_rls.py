"""RLS on agent_versions and agent_deployments.

Revision ID: fe2026100810
Revises: fe2026100809
Create Date: 2026-10-09 23:40:00.000000

Both tables are tenant-scoped (TenantMixin) and created after the RLS sweep,
so they shipped with RLS enabled by nobody — the same gap `a7b8c9d0e1f2`
closed for `ai_budget_reservations`: "a table created after the RLS migration
has no policy yet".  Same shape here: ENABLE + FORCE + tenant_isolation on
`app.tenant_id`, so a tenant session cannot read or write another tenant's
immutable version snapshots or canary state.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026100810"
down_revision: str | None = "fe2026100809"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

_TABLES = ("agent_versions", "agent_deployments")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON public.{table}
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD})"""
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
