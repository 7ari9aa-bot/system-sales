"""invoices — freeze a closed billing snapshot in the DATABASE, not by convention

Spec §53–54: a closed billing period is an IMMUTABLE snapshot. `close_period`
already refuses to write a second snapshot for the same period
(`uq_invoices_tenant_period`, revision b3c4d5e6f7a8), but nothing stopped an
UPDATE or a DELETE of a row that was already frozen. Immutability was therefore
"no code currently does that" — a convention, and one a direct SQL client (a
psql session, a backfill script, a Stripe reconciliation job) does not share.

This adds the missing half: a BEFORE UPDATE OR DELETE row trigger on
`invoices` that raises for a frozen snapshot. It is a DATABASE rule because the
guarantee has to hold for writers the application never sees; the same reason
the unique constraint lives here rather than in `close_period`.

**Why the rule is NARROW rather than blanket.** A blanket trigger on every
`invoices` row would also freeze the ordinary invoice lifecycle: `status` moves
draft -> open -> paid -> void, `issued_at`/`due_at`/`paid_at` are stamped, and a
provider-created row (`Invoice.provider`, e.g. Stripe) is updated by its webhook
handler. `invoices` has carried `status`/`issued_at`/`paid_at`/`provider_ref`
since the first schema revision precisely because those rows DO change.

The discriminator is the period: `close_period` is the only writer that sets
`period_start`/`period_end`, and those columns are what make a row a *period
snapshot* rather than an invoice. So:

* `period_start IS NOT NULL` -> a frozen snapshot: UPDATE and DELETE are refused.
* `period_start IS NULL` -> an ordinary invoice (legacy rows, provider rows):
  its lifecycle is untouched by this migration.

**Why the referential-action escape is required.** `invoices.tenant_id` is
`ON DELETE CASCADE` (model_kit), and `subscriptions`/`workspaces`/`locations`
all reference it `ON DELETE SET NULL`. A blanket refusal would therefore make
tenant offboarding — and every CI teardown that does `DELETE FROM tenants` —
fail on the first snapshot it owns, because the cascade is a DELETE of the
snapshot and the SET NULL is an UPDATE of it. Those are not edits of the frozen
content; they are the removal of the tenant that owns it.

The guard allows the mutation when EITHER of two independent probes says an
owner is being deleted. Two probes, not one, because either alone is an
assumption about how PostgreSQL executes referential actions, and the failure
mode of a wrong assumption is a broken deploy:

* the owning `tenants` row is already gone — `ON DELETE CASCADE` runs after the
  parent row is deleted, so a direct `DELETE FROM invoices` against a live
  tenant still fails this probe; and
* `pg_trigger_depth() > 1` — every `ON DELETE CASCADE` / `SET NULL` is executed
  by a referential-integrity trigger, while a direct client statement reaches
  this trigger at depth 1. This probe does not consult `tenants` at all, which
  matters because `tenants` is one of the tables RLS keeps being extended to;
  if it ever gains a policy, the existence probe would silently read "gone" and
  turn the guard into a no-op.

Both probes are false for a direct `UPDATE invoices` / `DELETE FROM invoices`,
which is the case the guarantee is about.

`tenants` deliberately carries no RLS today (see `_NO_TENANT_TABLES` in
scripts/provision.py), so the existence probe is not blinded. It runs as the
invoker, like the rest of the trigger.

**Deploy safety.** The runtime role is `sales_app` and it does NOT have
BYPASSRLS; nothing here revokes a privilege or is `SECURITY DEFINER`, so no
statement applies to the migration role itself. Both `CREATE OR REPLACE
FUNCTION` and `DROP TRIGGER IF EXISTS` make the migration idempotent, so it is a
no-op on a database where it has already run.

One statement per `op.execute()` — asyncpg's extended-query protocol rejects
multiple commands in a single call.
"""
from __future__ import annotations

from alembic import op

revision: str = "e7a8b9c0d1e2"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None

#: The guard, kept in one place so the downgrade drops exactly what upgrade made.
_GUARD_FN = "invoices_frozen_snapshot_guard"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.{_GUARD_FN}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $guard$
        BEGIN
            -- Not a period snapshot: an ordinary invoice keeps its lifecycle
            -- (draft -> open -> paid -> void), including provider-created rows.
            IF OLD.period_start IS NULL THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;

            -- An owner is being deleted: this is an ON DELETE CASCADE /
            -- SET NULL, not an edit of the snapshot. Two probes — see the
            -- module docstring for why one is not enough.
            IF NOT EXISTS (
                SELECT 1 FROM public.tenants WHERE id = OLD.tenant_id
            ) OR pg_trigger_depth() > 1 THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;

            RAISE EXCEPTION
                'invoice % is a frozen billing snapshot (period % .. %) and cannot be %',
                OLD.id, OLD.period_start, OLD.period_end, TG_OP
                USING HINT = 'a closed period is immutable by design';
        END
        $guard$;
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_GUARD_FN} ON public.invoices")
    op.execute(
        f"""
        CREATE TRIGGER {_GUARD_FN}
        BEFORE UPDATE OR DELETE ON public.invoices
        FOR EACH ROW
        EXECUTE FUNCTION public.{_GUARD_FN}()
        """
    )


def downgrade() -> None:
    """Drop the trigger and its function.

    Removing the guard restores the previous (convention-only) behaviour: the
    unique constraint still prevents a second snapshot for a period, but a row
    that is already frozen can be edited again. Nothing else depends on either
    object.
    """
    op.execute(f"DROP TRIGGER IF EXISTS {_GUARD_FN} ON public.invoices")
    op.execute(f"DROP FUNCTION IF EXISTS public.{_GUARD_FN}()")
