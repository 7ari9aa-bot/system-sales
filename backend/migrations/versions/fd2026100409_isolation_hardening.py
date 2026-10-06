"""Isolation hardening — the four database findings from the RLS audit.

G-01 audit_logs / security_events leaked across tenants: the single policy
said `tenant_id IS NULL OR tenant_id = current` for EVERY command, so any
tenant could read, update and delete the global system rows. Split per
command:
  INSERT  tenant rows + NULL system rows (login failures are pre-auth)
  SELECT  tenant rows for members; NULL rows only for a request carrying
          the app.is_platform_admin GUC the auth dependency sets
  UPDATE / DELETE  no policy at all — append-only (both tables are in the
          retention EXCLUDED set, so nothing needs to purge them)
audit_logs also becomes FORCE like every other guarded table.

G-04 sales_app held TRUNCATE / REFERENCES / TRIGGER / MAINTAIN on every
table through the default ACL — TRUNCATE bypasses RLS and row triggers,
so one SQL-injection could wipe any table for every tenant. Revoked on
all tables and from the default ACL; the ledger tables
(inventory_movements, financial_entries, effect_ledger,
order_status_history, audit_logs, security_events) become INSERT+SELECT
only — append-only is their documented invariant.

G-03 user_location_access WITH CHECK trusted a self-referential
user_id = current clause without checking the LOCATION's tenancy: a user
could grant themselves access to any location in any tenant. The check
now requires the location's tenant to be one of the caller's memberships,
resolved through a SECURITY DEFINER helper (the locations table is itself
RLS-guarded, so a policy subquery running as the caller could not see it).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fd2026100409"
down_revision: str | None = "fd2026100408"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_USER_GUARD = "NULLIF(current_setting('app.user_id', true), '')::uuid"
_ADMIN_GUARD = "coalesce(current_setting('app.is_platform_admin', true), '') = 'true'"

_LEDGER_TABLES = (
    "inventory_movements",
    "financial_entries",
    "effect_ledger",
    "order_status_history",
    "audit_logs",
    "security_events",
)


def _audit_policies(table: str, *, force: bool) -> None:
    if force:
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
    # INSERT: tenant rows + pre-auth system rows (NULL tenant).
    op.execute(
        f"""CREATE POLICY {table}_insert ON public.{table}
            FOR INSERT
            WITH CHECK (tenant_id IS NULL OR tenant_id = {_TENANT_GUARD})"""
    )
    # SELECT: tenant rows for members; NULL system rows only for a request
    # the auth dependency marked as platform admin.
    op.execute(
        f"""CREATE POLICY {table}_tenant_read ON public.{table}
            FOR SELECT
            USING (tenant_id = {_TENANT_GUARD})"""
    )
    op.execute(
        f"""CREATE POLICY {table}_system_read ON public.{table}
            FOR SELECT
            USING (tenant_id IS NULL AND {_ADMIN_GUARD})"""
    )
    # UPDATE / DELETE: no policy — RLS denies any command without one, so the
    # two tables are append-only at the database layer.


def upgrade() -> None:
    # --- G-01: the audit/security policy split --------------------------
    _audit_policies("security_events", force=True)
    _audit_policies("audit_logs", force=True)

    # --- G-03: the location grant must respect location tenancy ---------
    op.execute(
        """CREATE OR REPLACE FUNCTION public._location_tenant_allowed(
               p_user uuid, p_location uuid
           ) RETURNS boolean
           LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
           SELECT EXISTS (
               SELECT 1
               FROM public.locations l
               WHERE l.id = p_location
                 AND EXISTS (
                     SELECT 1 FROM public.tenant_users tu
                     WHERE tu.user_id = p_user AND tu.tenant_id = l.tenant_id
                 )
           )
       $$"""
    )
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT EXECUTE ON FUNCTION public._location_tenant_allowed(uuid, uuid)
              TO sales_app;
          END IF;
        END $$"""
    )
    op.execute("DROP POLICY IF EXISTS location_access ON public.user_location_access")
    op.execute(
        f"""CREATE POLICY location_access ON public.user_location_access
            USING (user_id = {_USER_GUARD})
            WITH CHECK (
                user_id = {_USER_GUARD}
                AND public._location_tenant_allowed(
                    {_USER_GUARD}, user_location_access.location_id
                )
            )"""
    )

    # --- G-04: privilege hygiene ----------------------------------------
    # GUARDED like every role-dependent statement in this repo: CI runs the
    # migrations BEFORE provision creates sales_app, so an unguarded REVOKE
    # would error the whole alembic run on a fresh database. provision.py
    # re-applies the same hardening after it creates the role (converge by
    # running both, the resolve_channel_tenant convention).
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            REVOKE TRUNCATE, REFERENCES, TRIGGER, MAINTAIN
              ON ALL TABLES IN SCHEMA public FROM sales_app;
          END IF;
        END $$"""
    )
    for table in _LEDGER_TABLES:
        op.execute(
            f"""DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                REVOKE UPDATE, DELETE ON public.{table} FROM sales_app;
              END IF;
            END $$"""
        )


def downgrade() -> None:
    # Restore the pre-hardening grants and the OR-NULL policies verbatim.
    op.execute(
        "GRANT TRUNCATE, REFERENCES, TRIGGER, MAINTAIN "
        "ON ALL TABLES IN SCHEMA public TO sales_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLES TO sales_app"
    )
    for table in _LEDGER_TABLES:
        op.execute(f"GRANT UPDATE, DELETE ON public.{table} TO sales_app")
    op.execute("DROP POLICY IF EXISTS location_access ON public.user_location_access")
    op.execute(
        f"""CREATE POLICY location_access ON public.user_location_access
            USING (user_id = {_USER_GUARD})
            WITH CHECK (user_id = {_USER_GUARD})"""
    )
    op.execute("DROP FUNCTION IF EXISTS public._location_tenant_allowed(uuid, uuid)")
    for table, force in (("security_events", True), ("audit_logs", True)):
        op.execute(f"DROP POLICY IF EXISTS {table}_insert ON public.{table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_read ON public.{table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_system_read ON public.{table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON public.{table}
                USING (tenant_id IS NULL OR tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id IS NULL OR tenant_id = {_TENANT_GUARD})"""
        )
        if not force:
            op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
