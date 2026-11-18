"""einvoice: tenant isolation (RLS) on einvoice_devices and einvoice_documents.

Revision ID: fe2026111730
Revises: fe2026111729
Create Date: 2026-11-18 00:30:00.000000

WHY. fe2026111625 created the two e-invoice tables with a tenant_id column but no row level
security. The boot reconciler checks that every tenant table has RLS enabled, forced, and the
canonical ``tenant_isolation`` policy (invariant 13), so the service refused to start
(``einvoice_devices: RLS is NOT enabled``, exit code 3) as soon as the migration reached
production. Every other tenant table gets this from its own migration or from
scripts/provision.py, which only CI runs.

Both tables are empty in production when this runs (checked), so enabling RLS changes no data and
hides no row. The statements are the same ones scripts/provision.py and the sibling migrations use,
and are safe to run twice.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026111730"
down_revision: str | None = "fe2026111729"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_TABLES = ("einvoice_devices", "einvoice_documents")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
