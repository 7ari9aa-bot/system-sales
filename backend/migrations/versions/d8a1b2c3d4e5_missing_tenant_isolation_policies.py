"""missing tenant_isolation policies on the phase-9 tables (sweep blind spot)

Revision ID: d8a1b2c3d4e5
Revises: c3f4e5a6b7d8
Create Date: 2026-09-28

Diagnosis (CI run 36136180924, DB-backed, non-superuser sales_app)
-----------------------------------------------------------------
``test_every_tenant_scoped_model_table_has_a_policy`` found six tenant-scoped
tables with no ``tenant_isolation`` policy: campaign_runs, journey_runs,
journeys, notification_digests, sagas, source_of_truth_policies.

Why the b2c3d4e5f6a7 sweep missed them: that sweep is a POINT-IN-TIME scan of
information_schema, and every one of the six was created ~30 revisions later
by f9b0c1d2e3f4 (phase9). Not partitions, not exempt-listed, and each created
WITH its tenant_id — simply not existing yet when the sweep ran. The phase-9
migration's own RLS block (f9b0c1d2e3f4:385-407) then made it worse three
ways: it named the policies ``<table>_tenant_isolation`` instead of the
canonical ``tenant_isolation`` (which the sweep, scripts/provision.py and the
policy test all key on), it ENABLEd RLS without FORCE (so the table-owning
migration/app role bypasses it), and it built the guard on bare
``current_setting('app.tenant_id')::uuid`` — which RAISES on an unbound
session instead of matching zero rows, and declares no WITH CHECK.

This is a CLASS gap, not a six-table gap: ``tenant_restore_jobs`` from the
same migration needed c166dd166dd1 to repair it, and the voice tables carry
the same wrong-named policies (no ORM model backs them yet, so the policy
test cannot see them). A fix scoped to six names would reopen the next time
someone creates a table after a sweep. So, in the spirit of b2c3d4e5f6a7, the
upgrade is again DYNAMIC over information_schema — but restricted to tables
that still LACK the canonical policy, so everything the sweep and its
successors already covered (audit_logs/security_events NULL-tenant variants,
d5e6f7a8b9c0's scheduled_jobs/webhook_events, the user-guarded tenant_users)
is left byte-identical and this revision is a no-op there.

Why none of the six gets the user-guard OR-branch
-------------------------------------------------
notification_digests carries a user_id column, but per
app/modules/notifications/digest.py it is an ordinary attribute — every
access filters tenant_id explicitly. provision.py and the b2c3d4e5f6a7 sweep
reserve ``OR user_id = app.user_id`` for tenant_users alone, whose membership
discovery must run BEFORE any tenant GUC exists. OR-ing user_id in here would
let a session with app.user_id bound but app.tenant_id unbound read digests
across every tenant — a widening, not a hardening. The branch is kept in the
block below so the generated text matches the sweep exactly.

Downgrade
---------
Restores the exact phase-9 state for the six named tables only: drop the
canonical policy, recreate the legacy ``<table>_tenant_isolation`` (guarded,
IF NOT EXISTS) and NO FORCE — never DISABLE; RLS was already ENABLEd on these
tables before this revision and turning isolation off is never a rollback
anyone should want (b2c3d4e5f6a7, a1f2c3d4e5b6). Tables beyond the six that
the dynamic upgrade may have covered on a drifted database KEEP the canonical
policy — the mirror image of the upgrade's add-only contract.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d8a1b2c3d4e5"
down_revision: str | None = "c3f4e5a6b7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The six tables CI caught. Only the downgrade names them explicitly: it must
# restore exactly what phase9 created, and nothing else.
_PHASE9_STRAGGLERS = (
    "campaign_runs",
    "journey_runs",
    "journeys",
    "notification_digests",
    "sagas",
    "source_of_truth_policies",
)

# Same exemptions as the b2c3d4e5f6a7 sweep — system plumbing, no tenant rows
# read cross-tenant by design (audit_logs/security_events are special-cased
# there with their own NULL-tolerant policies). On a drifted database the
# dynamic upgrade below must never FORCE RLS onto these.
_RLS_EXEMPT = (
    "outbox_events",
    "idempotency_keys",
    "plans",
    "refresh_tokens",
    "webhook_events",
    "scheduled_jobs",
    "audit_logs",
    "security_events",
)

# Canonical guards — identical text to b2c3d4e5f6a7 / c166dd166dd1:
# NULLIF keeps an UNSET GUC from casting '' to uuid, so an unbound session
# matches ZERO rows instead of raising.
_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_USER_GUARD = "NULLIF(current_setting('app.user_id', true), '')::uuid"

# Membership discovery at login runs before any tenant context exists, so
# tenant_users keeps the OR-variant (mirrors b2c3d4e5f6a7 and provision.py).
_USER_GUARDED = ("tenant_users",)


def _missing_policy_do_block() -> str:
    """Cover every tenant_id table the canonical policy has not reached yet.

    Same loop as the b2c3d4e5f6a7 sweep, minus what it already fixed: the
    NOT EXISTS on pg_policies makes this revision add-only and idempotent —
    a table with tenant_isolation is never touched, so the special-cased
    variants installed by earlier revisions survive byte-identical.
    """
    exempt = ", ".join(f"'{t}'" for t in _RLS_EXEMPT)
    user_guarded = ", ".join(f"'{t}'" for t in _USER_GUARDED)
    return f"""
    DO $$
    DECLARE
        r record;
        -- The guards are DOLLAR-QUOTED and passed to format() as %s
        -- ARGUMENTS, never spliced into the format string. Splicing them
        -- put a raw single quote inside a single-quoted literal, so the
        -- whole DO block failed to parse (see b2c3d4e5f6a7).
        tenant_guard text := $g${_TENANT_GUARD}$g$;
        user_guard text := $g${_USER_GUARD}$g$;
    BEGIN
        FOR r IN
            SELECT DISTINCT c.table_name
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_name = c.table_name AND t.table_schema = 'public'
            WHERE c.table_schema = 'public'
              AND c.column_name = 'tenant_id'
              AND c.table_name NOT IN ({exempt})
              AND NOT EXISTS (
                  SELECT 1 FROM pg_policies p
                  WHERE p.schemaname = 'public'
                    AND p.tablename = c.table_name
                    AND p.policyname = 'tenant_isolation'
              )
        LOOP
            EXECUTE format(
                'ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.table_name);
            EXECUTE format(
                'ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', r.table_name);
            EXECUTE format(
                'DROP POLICY IF EXISTS tenant_isolation ON public.%I', r.table_name);
            -- phase9 named its policies <table>_tenant_isolation. That legacy
            -- policy must not survive next to the canonical one: permissive
            -- policies are OR-ed, and its bare current_setting qual RAISES on
            -- an unbound session. (Same replacement c166dd166dd1 made for
            -- tenant_restore_jobs.)
            EXECUTE format(
                'DROP POLICY IF EXISTS %I ON public.%I',
                r.table_name || '_tenant_isolation', r.table_name);
            IF r.table_name = ANY (ARRAY[{user_guarded}]) THEN
                EXECUTE format(
                    'CREATE POLICY tenant_isolation ON public.%I '
                    'USING (tenant_id = %s OR user_id = %s) '
                    'WITH CHECK (tenant_id = %s OR user_id = %s)',
                    r.table_name, tenant_guard, user_guard, tenant_guard, user_guard);
            ELSE
                EXECUTE format(
                    'CREATE POLICY tenant_isolation ON public.%I '
                    'USING (tenant_id = %s) WITH CHECK (tenant_id = %s)',
                    r.table_name, tenant_guard, tenant_guard);
            END IF;
        END LOOP;
    END $$;
    """


def upgrade() -> None:
    # NOTE: one statement per op.execute() — migrations run through asyncpg,
    # whose extended-query protocol rejects multiple commands in a single
    # execute ("cannot insert multiple commands into a prepared statement").
    op.execute(_missing_policy_do_block())


def downgrade() -> None:
    for table in _PHASE9_STRAGGLERS:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
        # Restore the legacy phase-9 policy this revision replaced, guarded so
        # a re-run after a partial failure is a no-op (mirrors c166dd166dd1).
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = '{table}'
                      AND policyname = '{table}_tenant_isolation'
                ) THEN
                    CREATE POLICY {table}_tenant_isolation ON public.{table}
                    USING (tenant_id = current_setting('app.tenant_id')::uuid);
                END IF;
            END $$;
            """
        )
        # ENABLE stays (f9b0c1d2e3f4 turned it on); only FORCE is given back.
        # There is deliberately no DISABLE ROW LEVEL SECURITY here.
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
