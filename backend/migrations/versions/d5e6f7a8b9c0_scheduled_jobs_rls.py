"""scheduled_jobs: enable the RLS that production already has

Review N-10, and the real reason the scheduler bug survived so long.

The migration `b2c3d4e5f6a7` lists `scheduled_jobs` in `_RLS_EXEMPT` ("system
plumbing, no tenant rows read cross-tenant by design") and `scripts/provision.py`
does the same. **Production does not agree**: `scheduled_jobs` there has
`relrowsecurity` AND `relforcerowsecurity` true with a `tenant_isolation` policy
on both USING and WITH CHECK.

That divergence is what hid the bug:

* In CI the table has **no RLS at all**, so `ensure_recurring_jobs`'s unbound
  INSERT succeeded and any test of it would pass.
* In production the table is FORCE RLS, so the same INSERT was rejected by
  WITH CHECK — 40 violations in the logs — and the scheduler never ran a single
  sweep.

A test can only catch a production failure if CI's schema matches production's.
This migration makes them agree, in the direction that keeps the isolation: RLS
stays ON and the worker binds a tenant per transaction (which is how
`retention_worker` and the job runner already work). The alternative — dropping
RLS to match the docs — would trade a real isolation guarantee for a comment.

Idempotent by construction: production already has all three, so every statement
here is a no-op there and the effective change is on fresh databases like CI.
"""
from __future__ import annotations

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOTE: one statement per op.execute() — asyncpg's extended-query protocol
    # rejects multiple commands in a single execute().
    #
    # Both tables are FORCE RLS in production but were excluded here, which is
    # the divergence this migration closes. `webhook_events` is currently
    # unreachable (nothing constructs a WebhookEvent), so aligning it changes no
    # behaviour today — it removes the trap for whoever wires the webhook store.
    for table in ("scheduled_jobs", "webhook_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # Postgres has no CREATE POLICY IF NOT EXISTS, so guard on pg_policies.
        # The policy body matches what production already carries, so applying
        # this there changes nothing.
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = '{table}'
                      AND policyname = 'tenant_isolation'
                ) THEN
                    CREATE POLICY tenant_isolation ON {table}
                    USING (
                        tenant_id = (NULLIF(current_setting('app.tenant_id', true), ''))::uuid
                    )
                    WITH CHECK (
                        tenant_id = (NULLIF(current_setting('app.tenant_id', true), ''))::uuid
                    );
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    """Deliberately does not drop the policy or disable RLS.

    Reverting would restore the CI/production divergence that hid N-10, and
    would remove a tenant-isolation guarantee from a table that holds every
    tenant's scheduled work. Roll back the schema, not the isolation.
    """
    pass
