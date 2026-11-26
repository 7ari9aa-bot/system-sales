"""RLS for the pricing tables, and one canonical policy on teams/team_members.

`fe2026112614` created `price_lists`, `price_list_items` and `discount_rules` with a
`tenant_id` column and the app grants, but never enabled row-level security on them: every
authenticated session could read every shop's price lists and discount rules. The schema
wide gate (`tests/security/test_schema_wide_rls_policies.py`) caught it because it reads
`pg_class`/`pg_policies` rather than the ORM.

`fe2026112612` did enable and force RLS on `teams` and `team_members`, but with its own
`<table>_tenant_read` / `<table>_tenant_write` pair beside the canonical
`tenant_isolation`. Permissive policies are OR-ed, so a table is only as tight as its
loosest policy; the sweep in `d8a1b2c3d4e5` is add-only and therefore skipped them.

This revision makes all five tables match the canonical shape the sweep, `provision.py`
and the gate agree on: FORCE RLS plus exactly one `tenant_isolation` policy guarded by
`app.tenant_id`.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112617"
down_revision: str | None = "fe2026112615"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# Created by fe2026112614 with no RLS at all.
_UNGUARDED = ("price_lists", "price_list_items", "discount_rules")

# Created by fe2026112612 with a legacy read/write pair beside the canonical policy.
_LEGACY_PAIR = ("teams", "team_members")

_LEGACY_SUFFIXES = ("_tenant_read", "_tenant_write")


def _canonical(table: str) -> str:
    return (
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING (tenant_id = {_TENANT_GUARD}) "
        f"WITH CHECK (tenant_id = {_TENANT_GUARD})"
    )


def upgrade() -> None:
    for table in _UNGUARDED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(_canonical(table))

    for table in _LEGACY_PAIR:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        for suffix in _LEGACY_SUFFIXES:
            op.execute(f"DROP POLICY IF EXISTS {table}{suffix} ON {table}")
        # Recreated rather than left alone: a table is exactly as tight as its loosest
        # permissive policy, so the surviving one has to BE the canonical one.
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(_canonical(table))


def downgrade() -> None:
    for table in _UNGUARDED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    for table in _LEGACY_PAIR:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        # Byte-faithful to fe2026112612, so a downgrade lands on the schema the
        # previous revision actually produced.
        op.execute(
            f"CREATE POLICY {table}_tenant_read ON {table} "
            f"FOR SELECT USING (tenant_id = {_TENANT_GUARD})"
        )
        op.execute(
            f"CREATE POLICY {table}_tenant_write ON {table} "
            f"FOR ALL USING (tenant_id = {_TENANT_GUARD}) "
            f"WITH CHECK (tenant_id = {_TENANT_GUARD})"
        )
