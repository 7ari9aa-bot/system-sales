"""workflow_versions gains tenancy: tenant_id, backfill, FORCE RLS (§A/RLS sweep)

Revision ID: a1f2c3d4e5b6
Revises: e6f7a8b9c0d1
Create Date: 2026-09-24

``workflow_versions`` is the ONLY table in the automation domain with no
``tenant_id`` (``workflows``, ``workflow_executions``, ``workflow_failures`` all
carry one). That is not cosmetic. The b2c3d4e5f6a7 RLS sweep is DYNAMIC — it
selects ``information_schema.columns WHERE column_name = 'tenant_id'`` — so it
walked straight past this table, and ``workflow_versions`` today has no policy
of any kind. Consequence: ``GET /workflows/{id}/versions`` runs
``SELECT ... FROM workflow_versions WHERE workflow_id = :id`` with no tenant
predicate, and is isolated ONLY by the ``WorkflowService.get()`` call in front
of it. One forgotten ``await`` and every tenant's workflow definitions — the
steps, conditions and integration references in the JSONB — read as public
infrastructure. The golden rule: RLS reflects ownership, not the caller's memory.

Why the backfill ABORTS rather than defaults
--------------------------------------------
The UPDATE joins the parent ``workflow``. A row with no parent cannot be
assigned. It could be ``SET tenant_id = NULL``-and-continue (impossible: the
column becomes NOT NULL), skipped (a row no tenant can ever see, and FORCE RLS
makes its own owner blind to it), or guessed (a coin flip, and a wrong flip is
a CROSS-TENANT READ — the one failure mode this whole file exists to prevent).
So: count the survivors and ``RAISE EXCEPTION`` with sample ids. That cannot
happen by ordinary means — ``workflow_id`` is ``ON DELETE CASCADE``, so deleting
the workflow deletes its snapshots — which is exactly why it must be loud: an
orphan is evidence of a row written outside the constraint (a bad restore, a
hand-run script), and the operator must reconcile it before the schema starts
promising isolation it cannot deliver. ``RAISE`` aborts the transaction, so
nothing is half-applied.

Why the unique (workflow_id, version) changes KIND
--------------------------------------------------
It already existed — as a unique INDEX named ``uq_workflow_versions_workflow_version``.
The name is preserved so nothing that targets it breaks; only the kind changes,
to a named UNIQUE CONSTRAINT. A constraint is visible in ``pg_constraint``, can
be a FK target, and — the reason that matters HERE — is droppable by a name that
resolves on the way down. An unnamed index-only uniqueness is how O3 started.

Note on ordering: the FK to ``tenants`` and the index are created only AFTER the
backfill, and ``SET NOT NULL`` only after every row resolved a tenant, so the
constraints describe the data instead of hoping to match it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1f2c3d4e5b6"
down_revision: str | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Canonical guard, byte-identical to b2c3d4e5f6a7 / e171ee171ee0 / c166dd166dd1:
# an UNSET app.tenant_id yields NULL, which matches zero rows, instead of
# raising a cast error on every read.
_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

_UNIQUE_NAME = "uq_workflow_versions_workflow_version"
_FK_NAME = "fk_workflow_versions_tenant_id_tenants"
_IX_NAME = "ix_workflow_versions_tenant_id"

# ONE statement per op.execute(): these migrations run through asyncpg, whose
# extended-query protocol rejects multiple commands per execute. The body is a
# plain string, never an f-string or .format() target, because RAISE EXCEPTION
# uses '%' placeholders and the guard text contains single quotes.
_BACKFILL_SQL = """
DO $$
DECLARE
    orphan_count bigint;
    sample_ids   text;
BEGIN
    UPDATE public.workflow_versions wv
       SET tenant_id = w.tenant_id
      FROM public.workflows w
     WHERE w.id = wv.workflow_id
       AND wv.tenant_id IS NULL;

    SELECT count(*)
      INTO orphan_count
      FROM public.workflow_versions
     WHERE tenant_id IS NULL;

    IF orphan_count > 0 THEN
        SELECT string_agg(id::text, ', ' ORDER BY id)
          INTO sample_ids
          FROM (
                SELECT id FROM public.workflow_versions
                 WHERE tenant_id IS NULL
                 ORDER BY id
                 LIMIT 5
               ) s;
        RAISE EXCEPTION
            'workflow_versions tenancy backfill aborted: % snapshot row(s) have no parent workflow, so no tenant can be derived for them. Refusing to guess a tenant_id because a wrong one is a cross-tenant leak, and refusing to skip them because FORCE RLS would make them invisible to their own owner. Re-parent or delete these rows, then re-run. Sample ids: %',
            orphan_count, sample_ids;
    END IF;
END $$;
"""


def upgrade() -> None:
    # 1. Nullable first: a NOT NULL add on a populated table fails before any
    #    backfill can run, which would strand the deploy at step one.
    op.add_column(
        "workflow_versions",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # 2. Derive every row's tenant from its parent, loudly.
    op.execute(_BACKFILL_SQL)

    # 3. Only now is NOT NULL a statement about the data rather than a wish.
    op.alter_column(
        "workflow_versions",
        "tenant_id",
        existing_type=postgresql.UUID(as_uuid=True),
        existing_nullable=True,
        nullable=False,
    )

    # 4. Tenancy + lookup path.
    op.create_foreign_key(
        _FK_NAME,
        "workflow_versions",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(_IX_NAME, "workflow_versions", ["tenant_id"], unique=False)

    # 5. Uniqueness: index -> named constraint, same name, so the (workflow_id,
    #    version) contract survives the rename-free transition.
    op.drop_index(_UNIQUE_NAME, table_name="workflow_versions")
    op.create_unique_constraint(
        _UNIQUE_NAME, "workflow_versions", ["workflow_id", "version"]
    )

    # 6. The point of the column. ENABLE without FORCE would still let the
    #    table owner (the migration role) read across tenants.
    op.execute("ALTER TABLE public.workflow_versions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.workflow_versions FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.workflow_versions")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON public.workflow_versions
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )


def downgrade() -> None:
    # Reverse order. The policy goes first so no read can observe the column
    # vanishing underneath it.
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.workflow_versions")
    # NO FORCE, but RLS stays ENABLED: disabling tenant isolation is never a
    # rollback path anyone should want (same reasoning as b2c3d4e5f6a7).
    op.execute("ALTER TABLE public.workflow_versions NO FORCE ROW LEVEL SECURITY")

    op.drop_unique_constraint(_UNIQUE_NAME, "workflow_versions")
    op.create_index(_UNIQUE_NAME, "workflow_versions", ["workflow_id", "version"], unique=True)

    op.drop_index(_IX_NAME, table_name="workflow_versions")
    op.drop_constraint(_FK_NAME, "workflow_versions", type_="foreignkey")

    op.alter_column(
        "workflow_versions",
        "tenant_id",
        existing_type=postgresql.UUID(as_uuid=True),
        existing_nullable=False,
        nullable=True,
    )
    op.drop_column("workflow_versions", "tenant_id")
