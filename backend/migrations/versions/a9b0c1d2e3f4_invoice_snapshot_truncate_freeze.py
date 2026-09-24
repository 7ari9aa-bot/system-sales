"""§53–54 — freeze the billing snapshot against TRUNCATE as well as UPDATE/DELETE

Revision ID: a9b0c1d2e3f4
Revises: f7a2c9d4e8b1
Create Date: 2026-09-24

The hole this closes
--------------------
``e7a8b9c0d1e2`` made a closed period immutable BY THE DATABASE with a
``BEFORE UPDATE OR DELETE`` row trigger on ``invoices``, and said so: the
guarantee has to hold against writers the application never sees. It does — for
those two statements. It holds for nothing else, because PostgreSQL's third way
of emptying a table never reaches a row trigger:

    TRUNCATE TABLE invoices;

The PostgreSQL TRUNCATE page is explicit that only *truncate* triggers fire —
no row triggers, no rules, no cascaded deletes — and warns that it should
"therefore be used with care" for exactly that reason. So one statement,
executed by any role holding the TRUNCATE privilege, erases EVERY closed billing
period at once and leaves no row behind to audit, while the row guard that was
supposed to be the database rule watches nothing at all. A period is not
immutable while it is one statement from optional.

That privilege is not theoretical for the runtime role.
``scripts/provision.py::setup_app_role`` does

    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sales_app

and "ALL PRIVILEGES" on a table is ``SELECT INSERT UPDATE DELETE TRUNCATE
REFERENCES TRIGGER`` — so ``sales_app``, the role the API and the workers
connect as, can truncate billing today. Nothing in the application issues
TRUNCATE (see ``tests/test_snapshot_truncate_freeze.py``), which is precisely the
kind of statement "no code does it" was never enough to protect.

Two halves, because each covers the other's bypass
--------------------------------------------------
**(1) A ``BEFORE TRUNCATE`` statement-level trigger that always raises.** This is
the half that binds roles that hold every privilege: a trigger fires whatever
your grants are, it fires for the table owner and for the migration role, and a
``GRANT`` cannot hand the capability back. It is therefore also the durable half
— ``provision.py`` re-issues its blanket grant on every run, so the privilege
revoke below would be quietly undone without it.

**(2) ``REVOKE TRUNCATE ON public.invoices FROM sales_app``.** A permission
denial happens at parse time, before any trigger machinery, so this half keeps
refusing the statement on a database where someone has dropped or disabled the
trigger — and it makes the freeze visible to an operator auditing grants rather
than only to one reading trigger definitions. The two objects are deliberately
independent: neither one's loss reopens the hole by itself.

**What neither half can bind, said out loud.** Both halves are complete for every
role that does not own the table — which is every role the product uses. The
OWNER of `invoices` (`postgres`/`supabase_admin`, the migration role) holds its
own table privileges implicitly, so a REVOKE cannot bind it, and it can drop or
disable the trigger before truncating; a superuser can additionally
`SET session_replication_role = replica` and skip non-origin triggers, or
`DROP TABLE invoices` outright, which no trigger on that table can ever refuse.
That is the same trust boundary `e7a8b9c0d1e2` accepted: migrations and the
admin role are a reviewed code path, and the rule here is written against the
role that is NOT reviewed — the one the API and the workers connect as.

**Why the revoke is only TRUNCATE.** Privileges are row-blind. Revoking UPDATE
or DELETE would freeze the ordinary invoice lifecycle that ``e7a8b9c0d1e2``
went out of its way to leave alone (``status`` draft -> open -> paid -> void,
``issued_at``/``due_at``/``paid_at``, and the ``ON DELETE SET NULL`` cascades
from ``subscriptions``/``workspaces``/``locations`` that UPDATE
``subscription_id``/``workspace_id``/``location_id`` on every invoice a torn
down node touched). The column-level variant cannot help either: PostgreSQL
unions column privileges with the table-level grant, so
``REVOKE UPDATE (total)`` is a no-op while ``GRANT ALL`` stands. TRUNCATE is the
one statement on this table that is never legitimate for any row, which is what
makes revoking it safe.

**Why no escape hatch, unlike the row guard.** ``e7a8b9c0d1e2`` lets the
mutation through while the owning tenant is being deleted, because the FK
cascade makes that an UPDATE/DELETE of every snapshot the tenant owns. A
TRUNCATE is never a cascade: ``invoices`` is a plain table here (not on the
partitioning allowlist, so ``app/core/partitioning.py`` cannot drop it as a
partition either) and no referential action truncates a table. Tenant
offboarding deletes with ``DELETE FROM tenants``, which the row guard already
permits. ``TRUNCATE tenants CASCADE`` would truncate this table too, and is now
refused — deliberately: erasing every billing period in one statement is not
what offboarding means, and the hint says to delete the tenant instead.

Guarding what CI's plain Postgres does not have
----------------------------------------------
``sales_app`` is created by ``scripts/provision.py``, and CI runs
``alembic upgrade head`` BEFORE provisioning it, so on a fresh database the role
does not exist when this migration executes and an unguarded REVOKE aborts the
deploy with ``role "sales_app" does not exist``. It is therefore issued inside a
DO block conditioned on ``pg_roles``, the same idiom ``b2c3d4e5f6a7`` (granting
``resolve_channel_tenant``) and ``f1a2b3c4d5e6`` (revoking from anon) use. When
the role is absent, statement (2) is a no-op and the durable half — the trigger —
still lands; ``provision.py`` applies the identical REVOKE right after its own
blanket grant, so a database reaches the same ACL whichever order it was built
in.

Idempotency and one statement per execute
-----------------------------------------
``CREATE OR REPLACE FUNCTION`` and ``DROP TRIGGER IF EXISTS`` make the whole
migration a no-op on a database that already ran it. Each ``op.execute()``
carries exactly one statement — asyncpg's extended-query protocol rejects
multiple commands in a single call.
"""
from __future__ import annotations

from alembic import op

revision: str = "a9b0c1d2e3f4"
down_revision: str | None = "f7a2c9d4e8b1"
branch_labels = None
depends_on = None

#: The guard, named so the downgrade drops exactly what the upgrade made.
_GUARD_FN = "invoices_truncate_guard"

#: The role the API and the workers connect as (``scripts/provision.py``).
_APP_ROLE = "sales_app"

#: The privilege statement, spelled once so provision.py's copy of it can be
#: compared against this one character for character
#: (tests/test_snapshot_truncate_freeze.py).
TRUNCATE_REVOKE_SQL = f"REVOKE TRUNCATE ON public.invoices FROM {_APP_ROLE}"

_GUARD_FN_SQL = f"""
CREATE OR REPLACE FUNCTION public.{_GUARD_FN}()
RETURNS trigger
LANGUAGE plpgsql
AS $truncate$
BEGIN
    -- No OLD/NEW here: this is a statement trigger, and it fires for every
    -- TRUNCATE of the table, including the owner's. `invoices` holds the frozen
    -- period snapshots of spec §53–54, and one TRUNCATE erases all of them
    -- without touching a single row trigger.
    RAISE EXCEPTION 'cannot TRUNCATE invoices: closed billing periods are immutable snapshots'
        USING HINT = 'offboard a tenant with DELETE FROM tenants, or re-close the period as a new snapshot';
    RETURN NULL;
END
$truncate$;
"""

_CREATE_TRIGGER_SQL = f"""
CREATE TRIGGER {_GUARD_FN}
BEFORE TRUNCATE ON public.invoices
FOR EACH STATEMENT
EXECUTE FUNCTION public.{_GUARD_FN}()
"""

_REVOKE_SQL = f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN
        EXECUTE '{TRUNCATE_REVOKE_SQL}';
    END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(_GUARD_FN_SQL)
    op.execute(f"DROP TRIGGER IF EXISTS {_GUARD_FN} ON public.invoices")
    op.execute(_CREATE_TRIGGER_SQL)
    op.execute(_REVOKE_SQL)


def downgrade() -> None:
    """Restore the pre-migration posture: drop the guard, give the privilege back.

    What CANNOT come back: any snapshot row destroyed by a TRUNCATE between
    upgrade and downgrade. A TRUNCATE is not logged anywhere this database can
    replay from — the point of the guard was that no trace of the erased rows
    survives — so a downgrade performed after such an event restores the
    ABILITY to erase the rest, not the rows. Recovering those means a restore
    from backup, and that is stated rather than papered over.

    Re-granting TRUNCATE to the app role is the honest reversal of a privilege
    revoke (unlike `f1a2b3c4d5e6`, whose downgrade refuses to re-open a
    credential leak): it was granted by a blanket provision statement, it is
    what every other table in this schema allows, and holding it back would
    leave `invoices` quietly special in a way no test would notice.
    """
    op.execute(f"DROP TRIGGER IF EXISTS {_GUARD_FN} ON public.invoices")
    op.execute(f"DROP FUNCTION IF EXISTS public.{_GUARD_FN}()")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN
                EXECUTE 'GRANT TRUNCATE ON public.invoices TO {_APP_ROLE}';
            END IF;
        END $$;
        """
    )
