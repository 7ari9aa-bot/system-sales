"""§55-57 — the partition DDL retention needed, and retention as a CHOSEN policy.

Revision ID: f7a2c9d4e8b1
Revises: e3b7d2a9c4f1
Create Date: 2026-09-29

Why this migration exists at all
--------------------------------
``docs/GAP_REGISTER.md`` left §55-57 open with a reason: "`archive_old_rows` is
dead ... wiring retention needs a partition DDL that does not exist, so a partial
wire would delete rows on a schedule nobody chose." Both halves of that sentence
are answered here, and the order matters: the DDL first, then the policy that
authorises using it.

§56 asks for range partitioning of the high-volume append-only tables, monthly,
by time, with ``tenant_id`` indexed and explicitly NOT thousands of partitions
from tenant count. §57 asks for hot -> archive -> delete without breaking
Customer 360 or the legal audit trail. §52 says retention is per data class, per
tenant, and executed by a worker rather than a screen.

Half 1 — what is partitioned, and what is NOT
--------------------------------------------
``ai_usage`` becomes a monthly RANGE partition on ``period_date``. It is the
store the open gap names ("the daily series grows unbounded"), and it is the only
§56 candidate whose existing keys already survive the one rule Postgres will not
waive: "to create a unique or primary key constraint on a partitioned table ...
the constraint's columns must include all of the partition key columns".

That rule is why the other four are deliberately NOT converted, and each one is a
structural blocker, not a preference:

* ``messages`` — ``attachments`` and ``delivery_attempts`` hold single-column
  foreign keys on ``messages.id`` (``49303e2e2dd0``, ``8a1f6fb95fc6``). Once
  ``period``/``created_at`` is the partition key, ``messages.id`` can only be
  unique *per partition*, and a foreign key may not reference a
  non-unique-or-composite key. Converting would have to delete those constraints.
* ``event_log`` — ``app/core/events/outbox.py`` writes
  ``ON CONFLICT (event_id) DO NOTHING``. A month-local uniqueness check makes a
  duplicate event in a later month publishable twice.
* ``webhook_events`` — ``uq_webhook_events_provider_external`` IS the S10 replay
  guard (see ``b2c3d4e5f6a7``). Same objection, worse consequence: a replayed
  webhook would be ingested again.
* ``audit_logs`` — under legal retention ("never hard-delete") per
  ``docs/PII_DATA_MAP.md``. Partitioning it would exist only to enable a DROP
  that must never be issued, so it is not on the maintenance allowlist either.

The conversion is the shape Postgres requires, because there is no in-place
``ALTER TABLE ... PARTITION BY``: rename, create the partitioned parent, copy,
keep the old table. ``ai_usage_pre_partition`` is therefore NOT dropped. It is
the rollback that does not depend on a restore from backup; retiring it is an
operator decision after a soak, and nothing here deletes it.

What this costs, stated plainly: the primary key was ``(id)`` and had to become
``(id, period_date)``, so **``ai_usage.id`` is no longer database-enforced as a
globally unique value** — it is uniqueness within a month, plus the fact that ids
are Python-side uuid4. That is the only invariant in this table that the partition
structure cannot hold. Nothing references ``ai_usage.id`` by foreign key, and
``ai/usage.py``'s upsert targets ``uq_ai_usage_tenant_period_agent``, which
already contains ``period_date`` — a conflicting pair therefore always lands in
the same month partition, so ``ON CONFLICT`` still fires (verified against the
declarative-partitioning limitations rather than assumed; the ``ON CONFLICT``
caveat about "unique violations on the specified target relation, not its child
relations" is documented under legacy *inheritance*-based partitioning, not
declarative). ``tests/test_ai_usage_partition_shape.py`` pins it with a live
double-write anyway.

Half 1b — who may run the DDL
----------------------------
It cannot be the application role. ``scripts/provision.py`` gives ``sales_app``
USAGE on ``public`` plus table and sequence privileges and NO ``CREATE``, so no
worker holding an application connection can ``CREATE TABLE ... PARTITION OF``
or ``DROP TABLE``. Rather than widen that grant (which would let any code path
that gets a session create tables), this migration installs four SECURITY DEFINER
functions owned by the migration role, each with a pinned ``search_path`` and
``EXECUTE`` revoked from PUBLIC — the same mechanism ``b2c3d4e5f6a7`` uses for
``resolve_channel_tenant``, including the "return the minimum the caller may
see" discipline:

* ``partitioning_ensure_partition(text, date)`` — one month: create, set RLS,
  grant the app role. Refuses any parent not on its hard-coded allowlist.
* ``partitioning_ensure_months(text, integer)`` — this month + N ahead.
* ``retention_drop_horizon(text)`` — how many active tenants chose, how many did
  not, and the LONGEST horizon. Counts only: no other tenant's policy, store, or
  existence is returned.
* ``partitioning_purge_month(text, date)`` — DETACH + DROP one whole month, and
  it re-checks for itself: the allowlist, the 13-month floor, the consent
  aggregate, and the horizon. An advisory lock on ``(parent, month)`` makes two
  concurrent workers converge instead of one failing mid-DETACH.

DETACH is deliberately the non-CONCURRENT form, so the whole purge commits or
rolls back with the claiming transaction (CONCURRENTLY cannot run inside one, and
a half-applied destructive act is the worst outcome available). The price is a
brief ACCESS EXCLUSIVE lock on the parent — which is also why the purge sweep is
daily at most.

Half 2 — the policy becomes a choice
------------------------------------
``retention_policies`` already existed, and nothing read or wrote it: no service,
no route, no test. A table of policies that nobody can query or set is not a
policy, so:

* ``status`` defaults to ``'paused'``, not ``'active'``. An unanswered question
  now deletes nothing. Note the ORM metadata in ``app/modules/privacy/models.py``
  still says ``server_default="active"``; that is metadata only — SQLAlchemy
  omits a server-defaulted column from the INSERT, so the database value wins and
  a new row is inert. Correcting the model text is the privacy module's one-line
  change; deliberately NOT done here, because that file is not this task's to
  touch and the fail-safe direction is the database's.
* ``CHECK`` constraints bound ``status`` and ``retention_days`` (1..3650). A
  policy that means "delete everything" was always one typo away, and
  ``RetentionWorker`` already refuses non-positive values — the refusal now has
  a database-side counterpart. Both are added ``NOT VALID``: existing rows are
  left alone rather than deleted by a migration, and the worker's own guard is
  what protects them until an operator looks.
* ``UNIQUE (tenant_id, data_class)`` after collapsing duplicates. Duplicates were
  a contradiction, not a history: two rows for one store meant "the policy" had
  two answers, and the worker would apply both. The survivor is the most recently
  updated one, which is the latest expressed choice. This is the one place the
  migration deletes rows, and it deletes *policy definitions*, never tenant data.
* What is NOT enforced: an allowlist of ``data_class`` values. New stores are
  added by code, not by data — an unknown class is skipped by the worker and
  refused by the purge path, and a CHECK here would need to be edited on every
  feature while adding no safety.

Note on the aggregate's owner: ``retention_policies`` is FORCE RLS. A SECURITY
DEFINER function can see across tenants only because its owner is RLS-exempt (the
migration role in this project). If it is ever installed under a role that is
not, the aggregate sees no policies, every tenant looks un-chosen, and no month
is ever dropped — a silent no-op, never a silent delete.

Money, days and zones: nothing here crosses JSON, and no timezone is resolved.
Partition bounds are UTC months by construction; the merchant-calendar day that
analytics buckets by stays in ``analytics/timekit.py``.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f7a2c9d4e8b1"
down_revision: str | None = "e3b7d2a9c4f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept byte-identical to ``app.core.partitioning.LEGACY_SNAPSHOT_TABLE``.
LEGACY_SNAPSHOT_TABLE = "ai_usage_pre_partition"
DEFAULT_PARTITION = "ai_usage_default"
PARENT = "public.ai_usage"
DATA_CLASS = "ai_usage"

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# ---------------------------------------------------------------------------
# The maintenance functions. One statement per op.execute(): migrations run
# through asyncpg, whose extended protocol rejects multiple commands per
# execute (see b2c3d4e5f6a7). REVOKE and the conditional GRANT are therefore
# separate statements, and the GRANT is a DO block because `sales_app` is
# created by scripts/provision.py, which may run before or after migrations.
# ---------------------------------------------------------------------------

_ENSURE_ONE_SIG = "public.partitioning_ensure_partition(text, date)"
_ENSURE_SIG = "public.partitioning_ensure_months(text, integer)"
_PURGE_SIG = "public.partitioning_purge_month(text, date)"
_GATE_SIG = "public.retention_drop_horizon(text)"

_ENSURE_ONE_FN = """
CREATE OR REPLACE FUNCTION public.partitioning_ensure_partition(
    p_parent text, p_month date)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    parent_name text;
    part_name   text;
    -- `regclass`, never `oid`: these DDL statements interpolate the relation with
    -- %s (an `%I` on a dotted name would quote it into one impossible
    -- identifier), and %s on an oid prints a NUMBER where a table NAME belongs.
    -- regclass' output function prints the name, schema-qualified only when the
    -- pinned search_path cannot see it — which it always can, from here.
    part_ref    regclass;
    -- The guard reaches format() as an ARGUMENT, never spliced into the format
    -- string: inlined, its own quotes terminate the literal and the whole block
    -- fails to parse (that exact bug is documented in b2c3d4e5f6a7).
    guard       text := $g$NULLIF(current_setting('app.tenant_id', true), '')::uuid$g$;
BEGIN
    IF p_parent IS NULL OR p_month IS NULL
       OR date_trunc('month', p_month) <> p_month THEN
        RAISE EXCEPTION 'partitioning_ensure_partition: % is not a month start', p_month
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    -- Allowlist in SQL, not only in Python: a caller with EXECUTE must still not
    -- be able to point this function at somebody else's table.
    IF p_parent <> 'public.ai_usage' THEN
        RAISE EXCEPTION 'partitioning_ensure_partition: % is not a partitioned table '
                        'this database maintains', p_parent
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    SELECT c.relname INTO parent_name
      FROM pg_class c WHERE c.oid = to_regclass(p_parent);
    IF parent_name IS NULL THEN
        RAISE EXCEPTION 'partitioning_ensure_partition: % does not exist', p_parent
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    part_name := parent_name || '_' || to_char(p_month, 'YYYY_MM');
    IF to_regclass('public.' || part_name) IS NOT NULL THEN
        RETURN NULL;  -- already there: this whole function is idempotent
    END IF;

    EXECUTE format(
        'CREATE TABLE %I PARTITION OF %s FOR VALUES FROM (%L) TO (%L)',
        part_name, to_regclass(p_parent), p_month, (p_month + INTERVAL '1 month')::date
    );
    part_ref := to_regclass('public.' || part_name);

    -- A partition is an ordinary table that the app role inserts into: the
    -- parent's row-security settings and policy are not something this repo is
    -- willing to bet inheritance on, so they are asserted here. Re-running the
    -- statements is harmless, which is why DROP POLICY IF EXISTS comes first.
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %s TO sales_app',
                       part_ref);
    END IF;
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', part_ref);
    EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', part_ref);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %s', part_ref);
    EXECUTE format(
        'CREATE POLICY tenant_isolation ON %s USING (tenant_id = %s) WITH CHECK (tenant_id = %s)',
        part_ref, guard, guard
    );
    RETURN part_name;
END
$fn$;
"""

_PARTITIONING_ENSURE_PARTITION_REVOKE = f"REVOKE ALL ON FUNCTION {_ENSURE_ONE_SIG} FROM PUBLIC;"
_PARTITIONING_ENSURE_PARTITION_GRANT = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
        GRANT EXECUTE ON FUNCTION public.partitioning_ensure_partition(text, date)
            TO sales_app;
    END IF;
END $$;
"""

_ENSURE_FN = """
CREATE OR REPLACE FUNCTION public.partitioning_ensure_months(
    p_parent text, p_months_ahead integer)
RETURNS text[]
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    created text[] := '{}';
    month_start date;
    one text;
BEGIN
    IF p_parent <> 'public.ai_usage' THEN
        RAISE EXCEPTION 'partitioning_ensure_months: % is not a partitioned table '
                        'this database maintains', p_parent
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_months_ahead IS NULL OR p_months_ahead < 0 OR p_months_ahead > 24 THEN
        RAISE EXCEPTION 'partitioning_ensure_months: months_ahead must be 0..24, got %',
                        p_months_ahead
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    FOR month_start IN
        SELECT gs::date
          FROM generate_series(
                   date_trunc('month', now()),
                   (date_trunc('month', now())
                        + make_interval(months => p_months_ahead))::date,
                   '1 month') AS gs
    LOOP
        one := public.partitioning_ensure_partition(p_parent, month_start);
        IF one IS NOT NULL THEN
            created := array_append(created, one);
        END IF;
    END LOOP;
    RETURN created;
END
$fn$;
"""

_PARTITIONING_ENSURE_MONTHS_REVOKE = f"REVOKE ALL ON FUNCTION {_ENSURE_SIG} FROM PUBLIC;"
_PARTITIONING_ENSURE_MONTHS_GRANT = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
        GRANT EXECUTE ON FUNCTION public.partitioning_ensure_months(text, integer)
            TO sales_app;
    END IF;
END $$;
"""

_DROP_GATE_FN = """
CREATE OR REPLACE FUNCTION public.retention_drop_horizon(p_data_class text)
RETURNS TABLE(tenant_count bigint, missing_policies bigint, max_days integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
BEGIN
    -- Counts and one aggregate horizon, and nothing else: this is the only way
    -- the purge can learn that EVERY tenant consented without leaking which
    -- tenant chose what. FORCE RLS hides other tenants' rows from any ordinary
    -- session, and it must stay that way.
    SELECT count(*) INTO tenant_count
      FROM public.tenants WHERE is_active;

    SELECT count(*) INTO missing_policies
      FROM public.tenants t
     WHERE t.is_active
       AND NOT EXISTS (
             SELECT 1 FROM public.retention_policies r
              WHERE r.tenant_id = t.id
                AND r.data_class = p_data_class
                AND r.status = 'active'
                AND r.retention_days > 0
           );

    SELECT max(r.retention_days) INTO max_days
      FROM public.retention_policies r
     WHERE r.data_class = p_data_class
       AND r.status = 'active'
       AND r.retention_days > 0;

    RETURN NEXT;
END
$fn$;
"""

_RETENTION_DROP_HORIZON_REVOKE = f"REVOKE ALL ON FUNCTION {_GATE_SIG} FROM PUBLIC;"
_RETENTION_DROP_HORIZON_GRANT = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
        GRANT EXECUTE ON FUNCTION public.retention_drop_horizon(text) TO sales_app;
    END IF;
END $$;
"""

_PURGE_FN = """
CREATE OR REPLACE FUNCTION public.partitioning_purge_month(
    p_parent text, p_month date)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    part_name    text;
    data_class   text;
    tenant_total bigint;
    missing      bigint;
    horizon      integer;
BEGIN
    IF p_parent IS NULL OR p_month IS NULL
       OR date_trunc('month', p_month) <> p_month THEN
        RAISE EXCEPTION 'partitioning_purge_month: % is not a month start', p_month
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_parent <> 'public.ai_usage' THEN
        RAISE EXCEPTION 'partitioning_purge_month: % is not a table this database may purge',
                        p_parent
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    data_class := 'ai_usage';

    -- Floor, enforced HERE and not only in the Python plan: no caller — a buggy
    -- sweep, a script, a person with psql and EXECUTE — may reach a month the
    -- PII map still protects (13 months for ai_usage metrics).
    IF (p_month + INTERVAL '1 month')
       > (date_trunc('month', now()) - INTERVAL '13 months') THEN
        RAISE EXCEPTION 'partitioning_purge_month: month % is inside the 13-month floor',
                        p_month
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    -- Consent, also here: the month is shared by every tenant because §56
    -- partitions by time and never by tenant, so one tenant that never chose
    -- (or chose `paused`) keeps the whole month. The longest chosen horizon is
    -- the binding one for the same reason; a shorter one is served by the
    -- row-level worker, which can honour it per tenant.
    SELECT g.tenant_count, g.missing_policies, g.max_days
      INTO tenant_total, missing, horizon
      FROM public.retention_drop_horizon(data_class) g;
    IF tenant_total IS NULL OR tenant_total = 0 THEN
        RAISE EXCEPTION 'partitioning_purge_month: no active tenants to consent'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF missing > 0 THEN
        RAISE EXCEPTION 'partitioning_purge_month: % of % active tenants never chose a '
                        'retention policy for %', missing, tenant_total, data_class
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF horizon IS NULL OR horizon <= 0 THEN
        RAISE EXCEPTION 'partitioning_purge_month: non-positive retention horizon %',
                        horizon
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF (p_month + INTERVAL '1 month')::date
       > ((now() AT TIME ZONE 'UTC')::date - horizon) THEN
        RAISE EXCEPTION 'partitioning_purge_month: month % is inside the longest chosen '
                        'horizon (%)', p_month, horizon
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    part_name := (SELECT relname FROM pg_class WHERE oid = to_regclass(p_parent))
                 || '_' || to_char(p_month, 'YYYY_MM');
    -- The default partition's name can never match this shape, so an unroutable
    -- row is unreachable from here by construction. Refused again out loud.
    IF part_name LIKE '%_default' THEN
        RAISE EXCEPTION 'partitioning_purge_month: % is the default partition', part_name
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF to_regclass('public.' || part_name) IS NULL THEN
        RETURN NULL;  -- already gone; another worker won
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_inherits
                    WHERE inhrelid = to_regclass('public.' || part_name)
                      AND inhparent = to_regclass(p_parent)) THEN
        RAISE EXCEPTION 'partitioning_purge_month: % is not an attached partition of %',
                        part_name, p_parent
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    -- Two tenants' recurring rows can reach the same shared month at the same
    -- time; FOR UPDATE SKIP LOCKED only protects a single row. This lock makes
    -- the second worker wait and then find nothing, instead of aborting the
    -- whole claim batch with "partition does not exist".
    PERFORM pg_advisory_xact_lock(
        hashtext('partitioning_purge:' || p_parent || ':' || p_month::text));
    IF to_regclass('public.' || part_name) IS NULL THEN
        RETURN NULL;
    END IF;

    -- Non-concurrent on purpose: DETACH then DROP must commit or roll back as one
    -- act with the claiming transaction. The cost is a brief ACCESS EXCLUSIVE
    -- lock on the parent, which is why the sweep that calls this runs daily.
    EXECUTE format('ALTER TABLE %s DETACH PARTITION %s',
                   to_regclass(p_parent), to_regclass('public.' || part_name));
    EXECUTE format('DROP TABLE %s', to_regclass('public.' || part_name));
    RETURN part_name;
END
$fn$;
"""

_PARTITIONING_PURGE_MONTH_REVOKE = f"REVOKE ALL ON FUNCTION {_PURGE_SIG} FROM PUBLIC;"
_PARTITIONING_PURGE_MONTH_GRANT = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
        GRANT EXECUTE ON FUNCTION public.partitioning_purge_month(text, date) TO sales_app;
    END IF;
END $$;
"""


def upgrade() -> None:
    # ---- Half 2 first: the policy surface becomes a decision, inert by default.
    op.execute("ALTER TABLE public.retention_policies ALTER COLUMN status SET DEFAULT 'paused'")
    op.execute(
        "ALTER TABLE public.retention_policies ADD CONSTRAINT retention_policies_status_allowed "
        "CHECK (status IN ('active', 'paused')) NOT VALID"
    )
    op.execute(
        "ALTER TABLE public.retention_policies ADD CONSTRAINT retention_policies_days_bounded "
        "CHECK (retention_days >= 1 AND retention_days <= 3650) NOT VALID"
    )
    # One answer per (tenant, store). The survivor is the latest expressed
    # choice; the losers are contradictory duplicates, not history.
    op.execute(
        "DELETE FROM public.retention_policies WHERE id NOT IN ("
        "SELECT id FROM (SELECT id, row_number() OVER ("
        "PARTITION BY tenant_id, data_class ORDER BY updated_at DESC, id"
        ") AS n FROM public.retention_policies) d WHERE d.n = 1)"
    )
    op.create_index(
        "uq_retention_policies_tenant_class",
        "retention_policies",
        ["tenant_id", "data_class"],
        unique=True,
    )

    # ---- Half 1: rename -> partitioned parent -> copy. No in-place PARTITION BY.
    op.execute(f"ALTER TABLE public.ai_usage RENAME TO {LEGACY_SNAPSHOT_TABLE}")
    # Index names are schema-global, so the snapshot's must move out of the way
    # before the parent can own the canonical names again. Constraint names are
    # per-table and stay put.
    op.execute(
        """
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN SELECT indexname FROM pg_indexes
                      WHERE schemaname = 'public'
                        AND tablename = 'ai_usage_pre_partition'
            LOOP
                EXECUTE format('ALTER INDEX public.%I RENAME TO %I',
                               r.indexname, 'legacy_' || r.indexname);
            END LOOP;
        END $$;
        """
    )
    # LIKE carries the column list, NOT NULLs, server defaults, CHECKs, statistics
    # and comments, so the shape cannot drift from the table it replaces. It says
    # EXCLUDING INDEXES for a hard reason, not tidiness: `INCLUDING ALL` also
    # means `INCLUDING INDEXES`, and "Indexes, PRIMARY KEY, UNIQUE, and EXCLUDE
    # constraints on the original table will be created on the new table" — the
    # snapshot's PRIMARY KEY (id) has no `period_date`, and Postgres refuses that
    # on a partitioned table ("insufficient columns in the PRIMARY KEY constraint
    # definition"). Keys and foreign keys are therefore always this statement's
    # output, never LIKE's, and are re-declared below in their own words.
    op.execute(
        f"""
        CREATE TABLE public.ai_usage (
            LIKE public.{LEGACY_SNAPSHOT_TABLE} INCLUDING ALL EXCLUDING INDEXES
        ) PARTITION BY RANGE (period_date)
        """
    )
    # id alone cannot be unique across months, so the key grows the partition
    # column. THIS is the invariant the conversion buys, and it is documented in
    # app/core/partitioning.py rather than hidden: ai_usage.id is no longer
    # globally unique at the database level.
    op.execute(
        "ALTER TABLE public.ai_usage ADD CONSTRAINT ai_usage_pkey "
        "PRIMARY KEY (id, period_date)"
    )
    # The natural key already contains period_date, which is exactly why this
    # table can be partitioned without breaking ai/usage.py's upsert.
    op.execute(
        "ALTER TABLE public.ai_usage ADD CONSTRAINT uq_ai_usage_tenant_period_agent "
        "UNIQUE (tenant_id, period_date, agent_id)"
    )
    op.execute(
        "ALTER TABLE public.ai_usage ADD CONSTRAINT ai_usage_tenant_id_fkey "
        "FOREIGN KEY (tenant_id) REFERENCES public.tenants (id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE public.ai_usage ADD CONSTRAINT ai_usage_agent_id_fkey "
        "FOREIGN KEY (agent_id) REFERENCES public.agents (id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE public.ai_usage ADD CONSTRAINT ai_usage_workspace_id_fkey "
        "FOREIGN KEY (workspace_id) REFERENCES public.workspaces (id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE public.ai_usage ADD CONSTRAINT ai_usage_location_id_fkey "
        "FOREIGN KEY (location_id) REFERENCES public.locations (id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX ix_ai_usage_tenant_id ON public.ai_usage (tenant_id)")
    op.execute(
        "CREATE INDEX ix_ai_usage_tenant_period ON public.ai_usage (tenant_id, period_date)"
    )
    op.execute("CREATE INDEX ix_ai_usage_workspace_id ON public.ai_usage (workspace_id)")
    op.execute("CREATE INDEX ix_ai_usage_location_id ON public.ai_usage (location_id)")
    op.execute("ALTER TABLE public.ai_usage ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.ai_usage FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.ai_usage")
    op.execute(
        f"CREATE POLICY tenant_isolation ON public.ai_usage "
        f"USING (tenant_id = {_TENANT_GUARD}) WITH CHECK (tenant_id = {_TENANT_GUARD})"
    )
    # The safety net, and a deliberate trade: an insert whose month does not
    # exist yet lands here instead of failing a live agent run. The cost is that
    # a month which accumulated rows in `ai_usage_default` can no longer be
    # carved out (Postgres refuses to create a partition when the default
    # already holds rows belonging to it), which is why the recurring
    # `partition.ensure_months` sweep runs daily and pre-creates three months.
    op.execute(f"CREATE TABLE public.{DEFAULT_PARTITION} PARTITION OF public.ai_usage DEFAULT")
    # A partition is a real table, and RLS is NOT inherited by it (a query can
    # address a child directly, and `FORCE` is per relation). The month children
    # get this from `partitioning_ensure_partition`, which is the only way a
    # child is ever created from here on; this one is created by hand, so it is
    # said by hand too. Grants are not repeated: `scripts/provision.py` sets
    # ALTER DEFAULT PRIVILEGES for the migration role on schema public, which is
    # what every other table in this repo relies on.
    op.execute(f"ALTER TABLE public.{DEFAULT_PARTITION} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{DEFAULT_PARTITION} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{DEFAULT_PARTITION}")
    op.execute(
        f"CREATE POLICY tenant_isolation ON public.{DEFAULT_PARTITION} "
        f"USING (tenant_id = {_TENANT_GUARD}) WITH CHECK (tenant_id = {_TENANT_GUARD})"
    )

    op.execute(_ENSURE_ONE_FN)
    op.execute(_PARTITIONING_ENSURE_PARTITION_REVOKE)
    op.execute(_PARTITIONING_ENSURE_PARTITION_GRANT)
    op.execute(_ENSURE_FN)
    op.execute(_PARTITIONING_ENSURE_MONTHS_REVOKE)
    op.execute(_PARTITIONING_ENSURE_MONTHS_GRANT)
    op.execute(_DROP_GATE_FN)
    op.execute(_RETENTION_DROP_HORIZON_REVOKE)
    op.execute(_RETENTION_DROP_HORIZON_GRANT)
    op.execute(_PURGE_FN)
    op.execute(_PARTITIONING_PURGE_MONTH_REVOKE)
    op.execute(_PARTITIONING_PURGE_MONTH_GRANT)

    # Every historical month, then three ahead of the calendar, created through
    # the same function the worker will use from here on — one implementation of
    # "what a partition is", not a migration shape and a runtime shape.
    op.execute(
        f"""
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN
                SELECT gs::date AS m
                  FROM generate_series(
                           (SELECT COALESCE(date_trunc('month', MIN(period_date)),
                                            date_trunc('month', now()))
                              FROM public.{LEGACY_SNAPSHOT_TABLE}),
                           (date_trunc('month', now()) + INTERVAL '3 months')::date,
                           '1 month') AS gs
            LOOP
                PERFORM public.partitioning_ensure_partition('public.ai_usage', r.m);
            END LOOP;
        END $$;
        """
    )
    op.execute(f"INSERT INTO public.ai_usage SELECT * FROM public.{LEGACY_SNAPSHOT_TABLE}")
    op.execute(
        "COMMENT ON TABLE public.ai_usage IS '§56 monthly RANGE partition on period_date, "
        "maintained by partitioning_ensure_months and partitioning_purge_month'"
    )
    op.execute(
        f"COMMENT ON TABLE public.{LEGACY_SNAPSHOT_TABLE} IS 'f7a2c9d4e8b1 pre-partition "
        "snapshot of ai_usage: the rollback copy, kept until an operator retires it'"
    )


def downgrade() -> None:
    # Functions first: nothing else may be left holding a reference while the
    # tables they maintain disappear.
    for signature in (_PURGE_SIG, _GATE_SIG, _ENSURE_SIG, _ENSURE_ONE_SIG):
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    # Move everything back, including the counters a post-upgrade upsert
    # incremented (the snapshot's PRIMARY KEY is (id), so this converges on one
    # row per id again). Data whose month was already purged is not recoverable
    # by a downgrade — that is what the snapshot is for up to that point, and
    # why the purge sweep's consent gates are worth the argument they cost.
    op.execute(
        f"""
        INSERT INTO public.{LEGACY_SNAPSHOT_TABLE}
        SELECT * FROM public.ai_usage
        ON CONFLICT (id) DO UPDATE SET
            tokens_in = EXCLUDED.tokens_in,
            tokens_out = EXCLUDED.tokens_out,
            cost = EXCLUDED.cost,
            model_calls = EXCLUDED.model_calls
        """
    )
    op.execute(f"DROP TABLE IF EXISTS {PARENT}")
    op.execute(
        """
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN SELECT indexname FROM pg_indexes
                      WHERE schemaname = 'public'
                        AND tablename = 'ai_usage_pre_partition'
                        AND indexname LIKE 'legacy_%'
            LOOP
                EXECUTE format('ALTER INDEX public.%I RENAME TO %I',
                               r.indexname, substring(r.indexname from 8));
            END LOOP;
        END $$;
        """
    )
    op.execute(f"ALTER TABLE public.{LEGACY_SNAPSHOT_TABLE} RENAME TO ai_usage")
    op.execute("DROP INDEX IF EXISTS public.uq_retention_policies_tenant_class")
    op.execute(
        "ALTER TABLE public.retention_policies "
        "DROP CONSTRAINT IF EXISTS retention_policies_days_bounded"
    )
    op.execute(
        "ALTER TABLE public.retention_policies "
        "DROP CONSTRAINT IF EXISTS retention_policies_status_allowed"
    )
    op.execute(
        "ALTER TABLE public.retention_policies ALTER COLUMN status SET DEFAULT 'active'"
    )
    # Collapsed duplicate policy rows are NOT re-created: they were a
    # contradiction, and a rollback does not restore contradictions.
