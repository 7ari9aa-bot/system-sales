"""Give sales_app a read policy on the RBAC reference plane.

Revision ID: fe2026100805
Revises: fe2026100804
Create Date: 2026-10-09 09:10:00.000000

`fd2026100410` made `permissions`, `roles`, `role_permissions` and `plans`
SELECT-ONLY for the runtime role — reads were supposed to keep working, and
`tests/test_auth_tables_isolation.py::test_reads_still_work` pins exactly that.

`fd2026100502` then ran `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` on those four
tables as part of "enable RLS on reference and system tables to satisfy the
security audit" — and created no policy. Enabling RLS without one is not
"restrict some reads", it is DENY ALL reads for every non-owner. The owner
bypasses it (these tables are not FORCE'd), which is why `scripts/provision.py`
seeds `roles=3` and reports success while the app role reads zero rows from the
same table.

The blast radius is the whole platform, not the audit checkbox: `roles` empty for
`sales_app` means `_role_permissions()` returns nothing and the tenant_users →
roles join resolves no `role_code`, so every `require_permission` call denies and
`require_ai_approve`'s owner pass-through never fires. Any deployment actually
running the documented runtime DSN (config.py: "sales_app, no bypassrls — RLS
applies to it") has no working RBAC plane at all. It is invisible today only
because every environment currently connects as the owner.

In CI this is not subtle: 1070 of 1091 errors are `tests/conftest.py:132`
raising `NoResultFound` on `Role.code == "owner"` — the session fixture cannot
build a tenant context, so no database-backed test ever runs.

Writes stay refused twice over: `fd2026100410`'s REVOKE of INSERT/UPDATE/DELETE
still applies, and this policy is FOR SELECT only, so the reference plane is
read-only at both the privilege layer and the row layer.
"""

from collections.abc import Sequence

from alembic import op


revision: str = "fe2026100805"
down_revision: str | None = "fe2026100804"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The four tables `fd2026100502` enabled RLS on without ever giving the runtime
#: role a way to read them back. `plans` is here because the same statement
#: covered it and billing entitlements read it through the same role.
_REFERENCE_TABLES = ("permissions", "roles", "role_permissions", "plans")


def upgrade() -> None:
    for table in _REFERENCE_TABLES:
        # One statement per migration step: asyncpg's driver cannot prepare a
        # multi-statement string, which is the rule `d2d8179` had to conform to.
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app')
                   AND EXISTS (SELECT 1 FROM information_schema.tables
                               WHERE table_schema = 'public'
                                 AND table_name = '{table}')
                   AND NOT EXISTS (
                        SELECT 1 FROM pg_policies
                        WHERE schemaname = 'public'
                          AND tablename = '{table}'
                          AND policyname = 'sales_app_read'
                   )
                THEN
                    EXECUTE format(
                        'CREATE POLICY sales_app_read ON public.%I ' ||
                        'FOR SELECT TO sales_app USING (true)',
                        '{table}'
                    );
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    # Back to `fd2026100502`'s state: RLS enabled, no policy, the runtime role
    # reads nothing. That is the broken state this revision exists to leave, so
    # a downgrade is a deliberate regression and says so by restoring it.
    for table in _REFERENCE_TABLES:
        op.execute(f"DROP POLICY IF EXISTS sales_app_read ON public.{table}")
