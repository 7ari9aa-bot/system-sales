"""hierarchy tables FORCE RLS (§151 Q1)

Revision ID: e171ee171ee0
Revises: d170cc170dd0
Create Date: 2026-09-22

``workspaces`` and ``locations`` (created by 48528b41d6db, the §151 W2-a
migration) landed AFTER the b2c3d4e5f6a7 hardening sweep and received no
policy at all — cross-tenant isolation was app-filter-only. §151 makes the
hierarchy load-bearing (scope GUCs + admin API), so RLS must reflect the
ownership hierarchy. Canonical NULLIF guard (matches c136aa136aa1/c166dd166dd1):
an unset ``app.tenant_id`` matches ZERO rows instead of raising.

``user_location_access`` was already covered by the sweep (self-keyed
``location_access`` policy on app.user_id); its admin-grant OR-clause arrives
with the Q3 API, not here.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e171ee171ee0"
down_revision: str | None = "d170cc170dd0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    # One statement per op.execute(): asyncpg's extended protocol rejects
    # multiple commands per execute.
    for table in ("workspaces", "locations"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON public.{table}
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD})"""
        )


def downgrade() -> None:
    for table in ("workspaces", "locations"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
