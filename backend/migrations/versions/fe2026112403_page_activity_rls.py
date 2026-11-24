"""``page_activity`` carries tenant isolation like every other tenant table.

The table was created by fe2026112304a without ENABLE/FORCE ROW LEVEL SECURITY, and the boot
reconciler refuses to start the app while a tenant table is unprotected (Invariant 13). The feed
holds one shop's post/reaction/mention events, so it is exactly the kind of row that must never
cross tenants.

Revision ID: fe2026112403
Revises: fe2026112402
Create Date: 2026-11-24 21:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112403"
down_revision: str | None = "fe2026112402"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("ALTER TABLE public.page_activity ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.page_activity FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.page_activity")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON public.page_activity
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )


def downgrade() -> None:
    # NO FORCE, but RLS stays ENABLED: turning tenant isolation off is not a rollback anyone wants.
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.page_activity")
    op.execute("ALTER TABLE public.page_activity NO FORCE ROW LEVEL SECURITY")
